# backend/app/api/v1/documents.py
"""文档上传与查询 API（docs/TECH.md §5.2）。

- POST /api/v1/projects/{project_id}/documents      上传文档（multipart）
- GET  /api/v1/projects/{project_id}/documents      文档列表（?status= 过滤）
- GET  /api/v1/documents/{document_id}              文档详情
- POST /api/v1/documents/{document_id}/parse        触发 LLM 抽取设定（SSE 流式，含分块进度；结果暂存）
- GET  /api/v1/documents/{document_id}/chunks       文档分块预览（确认导入前）
- POST /api/v1/documents/{document_id}/confirm-import 确认导入：建卡片/片段并写向量库
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...database import get_db
from ...models import Document, KnowledgeCard, KnowledgeSnippet, Project
from ...schemas.card import (
    ConfirmImportRequest,
    ConfirmImportResponse,
    SnippetChunkRead,
)
from ...schemas.document import DocumentParseRequest, DocumentRead, ParseResultRead
from ...services.embedding.embedder import Embedder, FallbackEmbedder, LocalHashEmbedder
from ...services.llm.resolve import NoLLMConfigError, resolve_embedding, resolve_llm, resolve_supports_1m
from ...services.llm.stream import sse_event
from ...services.parsing.chunker import chunk_document
from ...services.parsing.extractor import (
    SAFE_SINGLE_UNIT_CHARS,
    SINGLE_UNIT_MAX_BYTES,
    stream_extract_candidates,
)
from ...services.retrieval.hybrid import HybridRetriever
from ...utils.file_parser import parse_file_content

router = APIRouter(prefix="/api/v1", tags=["documents"])

logger = logging.getLogger(__name__)

# 最大上传大小：10 MB
MAX_FILE_SIZE = 10 * 1024 * 1024

DocumentStatus = Literal["pending", "parsing", "parsed", "imported", "failed"]


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    """按 id 查询项目，不存在则抛 404。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


async def _get_document_or_404(document_id: str, db: AsyncSession) -> Document:
    """按 id 查询文档，不存在则抛 404。"""
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文档 {document_id} 不存在",
        )
    return document


def _single_unit_decision(file_size: int, content_text: str, supports_1m: bool) -> bool:
    """整篇喂入判定（docs/TECH.md §5.2）：文本足够小，或 ≤1MB 且模型开「1M 上下文」。

    纯函数，供测试与解析端点共用。
    """
    return (
        len((content_text or "").strip()) <= SAFE_SINGLE_UNIT_CHARS
        or (file_size <= SINGLE_UNIT_MAX_BYTES and supports_1m)
    )


def _parse_result_payload(document: Document) -> Optional[dict]:
    """从文档暂存结果构建「查询已解析结果」响应体；无结果返回 None。

    纯函数，供测试复用：仅当状态为 parsed 且存在候选时返回。
    """
    result = document.parse_result_json or {}
    if document.status != "parsed" or not result.get("candidates"):
        return None
    # 历史存量可能把 manual_confirm 存为 null（解析请求未传该字段时），
    # 而 ParseResultRead.manual_confirm 为非空 bool，直接返回会校验 500；
    # 此处回退文档级默认（require_manual_confirm）。
    manual_confirm = result.get("manual_confirm")
    return {
        "candidates": result.get("candidates", []),
        "threshold": result.get("threshold", document.parse_threshold),
        "manual_confirm": (
            document.require_manual_confirm if manual_confirm is None else manual_confirm
        ),
        "extracted_at": result.get("extracted_at"),
    }


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="上传文档（提取纯文本，status=pending，不自动解析）",
)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    parse_threshold: Literal["low", "medium", "high"] = Form("medium"),
    require_manual_confirm: bool = Form(True),
    db: AsyncSession = Depends(get_db),
) -> Document:
    """接收 multipart/form-data，保存原文件并提取纯文本到 Document 记录。"""
    await _get_project_or_404(project_id, db)

    content_bytes = await file.read()
    if len(content_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件超过 10MB 上限（当前 {len(content_bytes)} 字节）",
        )

    # 提取纯文本（不支持的扩展名/损坏文档 → 400）
    filename = file.filename or ""
    try:
        file_type, text = await parse_file_content(filename, content_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    document = Document(
        project_id=project_id,
        filename=filename or "unnamed",
        file_type=file_type,
        file_size=len(content_bytes),
        content_text=text,
        status="pending",
        parse_threshold=parse_threshold,
        require_manual_confirm=require_manual_confirm,
        imported_at=datetime.utcnow().replace(microsecond=0).isoformat(),
    )
    db.add(document)
    await db.flush()  # 先拿到 document.id，用于命名保存的原文件

    # 保存原文件到 data/documents/，命名 {id}{扩展名}（模型无 file_path 字段，按 id 反查）
    docs_dir = settings.data_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or f".{file_type}"
    (docs_dir / f"{document.id}{ext}").write_bytes(content_bytes)

    await db.commit()
    await db.refresh(document)
    return document


@router.get(
    "/projects/{project_id}/documents",
    response_model=list[DocumentRead],
    summary="文档列表（按创建时间倒序，?status= 过滤）",
)
async def list_documents(
    project_id: str,
    document_status: DocumentStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    await _get_project_or_404(project_id, db)
    stmt = select(Document).where(Document.project_id == project_id)
    if document_status is not None:
        stmt = stmt.where(Document.status == document_status)
    result = await db.execute(stmt.order_by(Document.created_at.desc()))
    return list(result.scalars().all())


@router.get("/documents/{document_id}", response_model=DocumentRead, summary="文档详情")
async def get_document(
    document_id: str, db: AsyncSession = Depends(get_db)
) -> Document:
    return await _get_document_or_404(document_id, db)


@router.post(
    "/documents/{document_id}/parse",
    summary="触发 LLM 抽取设定（SSE 流式，含分块进度；结果暂存到文档，不直接写入知识库）",
    responses={
        200: {
            "description": "SSE 事件流（progress / done / error）",
        }
    },
)
async def parse_document(
    document_id: str,
    payload: DocumentParseRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """读取文档 + 解析提供商/模型，按章节单元并发调用 LLM 抽取设定。

    SSE 帧（docs/TECH.md §5.2）：
        event: progress  data: {"index", "total", "label", "status": "start"|"done"|"error"|"skipped", "result"?}
        event: done      data: {"candidates": [...]}
        event: error     data: {"message": "..."}

    流开始前置 status="parsing"，结束置 "parsed"（成功）或 "failed"（失败/中断）。
    """
    document = await _get_document_or_404(document_id, db)

    try:
        resolved = await resolve_llm(db, project_id=document.project_id)
    except NoLLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    client = resolved.client
    threshold = payload.threshold or document.parse_threshold

    # 整篇解析判定（docs/TECH.md §5.2）：任何模型都安全的保守字符阈值，
    # 或「≤1MB 且模型按 1M 上下文」——模型设置开关（模型提供商表单内该模型
    # 的 supports_1m_context，或「模型设置」抽屉的 use_1m_context）开启时整篇
    # 单次喂入 LLM，模型可见全文上下文；整篇调用失败时 extractor 自动回退分块解析。
    supports_1m = await resolve_supports_1m(
        db, resolved.provider, resolved.model_id, project_id=document.project_id
    )
    single_unit = _single_unit_decision(document.file_size, document.content_text, supports_1m)

    # 解析开始前置状态，前端列表据此显示「解析中」并禁用重复解析
    document.status = "parsing"
    await db.commit()

    async def event_stream():
        candidates: list[dict] = []
        try:
            async for frame in stream_extract_candidates(
                document.content_text,
                client,
                threshold=threshold,
                single_unit=single_unit,
            ):
                if frame["event"] == "error":
                    document.status = "failed"
                    await db.commit()
                    yield sse_event("error", frame["data"])
                    return
                if frame["event"] == "done":
                    candidates = frame["data"]["candidates"]
                yield sse_event(frame["event"], frame["data"])
        except BaseException:
            # 客户端断开等取消场景：尽力把状态复位为失败，避免卡在「解析中」
            try:
                document.status = "failed"
                await db.commit()
            except BaseException:
                logger.warning("文档解析状态复位失败（document=%s）", document_id)
            raise

        # 流正常结束：结果暂存到文档记录，不直接写入 KnowledgeCard
        document.parse_result_json = {
            "candidates": candidates,
            "threshold": threshold,
            "manual_confirm": payload.manual_confirm,
            "extracted_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        }
        if payload.manual_confirm is not None:
            document.require_manual_confirm = payload.manual_confirm
        document.status = "parsed"
        await db.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/documents/{document_id}/parse-result",
    response_model=ParseResultRead,
    summary="查询已解析结果（解析完成后前端恢复候选卡片，刷新后仍可确认导入）",
)
async def get_document_parse_result(
    document_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """返回解析完成后暂存在 Document.parse_result_json 的候选结果。

    文档状态为 parsed 且存在候选时返回；否则抛 404（尚未解析或已无暂存结果）。
    """
    document = await _get_document_or_404(document_id, db)
    payload = _parse_result_payload(document)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文档 {document_id} 尚无解析结果",
        )
    return payload


@router.get(
    "/documents/{document_id}/chunks",
    response_model=list[SnippetChunkRead],
    summary="文档分块预览（确认导入前查看片段 id / 文本 / 标签）",
)
async def preview_document_chunks(
    document_id: str, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """将文档按段落分块并返回预览，片段 id 稳定为 {document_id}:{index}。"""
    document = await _get_document_or_404(document_id, db)
    return [
        {
            "id": f"{document.id}:{index}",
            "text": chunk["text"],
            "tags": chunk["tags"],
            "start": chunk["start"],
            "end": chunk["end"],
        }
        for index, chunk in enumerate(chunk_document(document.content_text))
    ]


@router.post(
    "/documents/{document_id}/confirm-import",
    response_model=ConfirmImportResponse,
    summary="确认导入：创建知识卡与片段，生成 embedding 写入 Chroma",
)
async def confirm_import(
    document_id: str,
    payload: ConfirmImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """确认导入知识库：

    1. 分块文档 → KnowledgeSnippet 记录（按稳定 id 幂等，已存在则复用）；
    2. 创建 KnowledgeCard，并按卡片 snippet_ids 关联片段；
    3. 为全部片段生成 embedding 写入 Chroma（无 API Key 时回退本地哈希向量）；
    4. 更新 Document.status = imported。
    """
    document = await _get_document_or_404(document_id, db)

    # 远程 embedding：优先使用项目/全局解析的提供商 Key；无配置则回退本地哈希向量。
    # 有 Key 时用 FallbackEmbedder 包一层：远程调用失败（如提供商缺少该模型 404）
    # 自动回退本地哈希，避免在失败后再建第二个 Chroma 客户端（同路径二次打开会
    # 触发段错误、拖垮后端进程）。
    embedder = None
    try:
        provider, decrypted_key = await resolve_embedding(
            db, project_id=document.project_id
        )
    except NoLLMConfigError:
        provider, decrypted_key = None, None
    if provider is not None and decrypted_key:
        embedder = FallbackEmbedder(
            remote=Embedder(
                api_key=decrypted_key,
                base_url=provider.base_url or None,
                model=payload.embedding_model,
            ),
            local=LocalHashEmbedder(),
        )
    retriever = HybridRetriever(embedder=embedder)

    # 1. 分块 → snippets（id 稳定，幂等复用）
    chunks = chunk_document(document.content_text)
    snippet_ids: list[str] = []
    snippet_by_id: dict[str, KnowledgeSnippet] = {}
    for index, chunk in enumerate(chunks):
        snippet_id = f"{document.id}:{index}"
        snippet = await db.get(KnowledgeSnippet, snippet_id)
        if snippet is None:
            snippet = KnowledgeSnippet(
                id=snippet_id,
                project_id=document.project_id,
                document_id=document.id,
                text=chunk["text"],
                tags=chunk["tags"],
                start_offset=chunk["start"],
                end_offset=chunk["end"],
            )
            db.add(snippet)
        snippet_by_id[snippet_id] = snippet
        snippet_ids.append(snippet_id)

    # 2. 创建卡片并关联片段
    cards: list[KnowledgeCard] = []
    for item in payload.cards:
        card = KnowledgeCard(
            project_id=document.project_id,
            card_type=item.card_type,
            title=item.title,
            content_json=item.content_json,
            tags=item.tags,
            source_doc_ids=[document.id],
        )
        db.add(card)
        cards.append(card)
        await db.flush()  # 拿到 card.id 用于关联片段
        for ref_id in item.snippet_ids:
            snippet = snippet_by_id.get(ref_id)
            if snippet is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"snippet_id {ref_id!r} 不存在，请先通过 /chunks 获取片段 id",
                )
            if snippet.card_id is None:
                snippet.card_id = card.id

    # 3. embedding 写入 Chroma
    embed_payload = [
        {
            "id": snippet_id,
            "text": snippet_by_id[snippet_id].text,
            "tags": snippet_by_id[snippet_id].tags,
            "document_id": document.id,
            "card_id": snippet_by_id[snippet_id].card_id,
        }
        for snippet_id in snippet_ids
    ]
    try:
        snippet_count = await retriever.upsert_snippets(
            document.project_id, embed_payload
        )
    except Exception as exc:
        # 远程 embedding 已由 FallbackEmbedder 兜底；此处仍失败（如 Chroma 写入
        # 维度不一致 / 磁盘错误）时给出明确错误，解析结果暂存于 parse_result_json，
        # 用户可修正后重新导入。
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"embedding 存储失败：{exc}",
        ) from exc

    # 4. 更新文档状态
    document.status = "imported"
    document.imported_at = datetime.utcnow().replace(microsecond=0).isoformat()
    await db.commit()
    for card in cards:
        await db.refresh(card)
    return {"cards": cards, "snippet_count": snippet_count}
