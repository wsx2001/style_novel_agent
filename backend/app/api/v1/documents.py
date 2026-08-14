# backend/app/api/v1/documents.py
"""文档上传与查询 API（docs/TECH.md §5.2）。

- POST /api/v1/projects/{project_id}/documents      上传文档（multipart）
- GET  /api/v1/projects/{project_id}/documents      文档列表（?status= 过滤）
- GET  /api/v1/documents/{document_id}              文档详情
- POST /api/v1/documents/{document_id}/parse        触发 LLM 抽取设定（同步，结果暂存）
- GET  /api/v1/documents/{document_id}/chunks       文档分块预览（确认导入前）
- POST /api/v1/documents/{document_id}/confirm-import 确认导入：建卡片/片段并写向量库
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...database import get_db
from ...models import ApiKeyConfig, Document, KnowledgeCard, KnowledgeSnippet, Project
from ...schemas.card import (
    ConfirmImportRequest,
    ConfirmImportResponse,
    SnippetChunkRead,
)
from ...schemas.document import CandidateCard, DocumentParseRequest, DocumentRead
from ...services.crypto.api_key import decrypt_api_key
from ...services.embedding.embedder import Embedder
from ...services.llm.client import create_client
from ...services.parsing.chunker import chunk_document
from ...services.parsing.extractor import extract_candidates
from ...services.retrieval.hybrid import HybridRetriever
from ...utils.file_parser import parse_file_content

router = APIRouter(prefix="/api/v1", tags=["documents"])

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


async def _find_api_key_config(db: AsyncSession, project_id: str) -> ApiKeyConfig | None:
    """查找可用的 API Key 配置：优先项目级默认，其次项目级任意，再回退全局。"""
    scoped = await db.execute(
        select(ApiKeyConfig)
        .where(ApiKeyConfig.project_id == project_id)
        .order_by(ApiKeyConfig.is_default.desc(), ApiKeyConfig.created_at)
    )
    config = scoped.scalars().first()
    if config is not None:
        return config
    global_result = await db.execute(
        select(ApiKeyConfig)
        .where(ApiKeyConfig.project_id.is_(None))
        .order_by(ApiKeyConfig.is_default.desc(), ApiKeyConfig.created_at)
    )
    return global_result.scalars().first()


@router.post(
    "/documents/{document_id}/parse",
    response_model=list[CandidateCard],
    summary="触发 LLM 抽取设定（同步；结果暂存到文档，不直接写入知识库）",
)
async def parse_document(
    document_id: str,
    payload: DocumentParseRequest,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """读取文档 + 项目 API Key，分块调用 LLM 抽取设定，候选卡片暂存于文档记录。"""
    document = await _get_document_or_404(document_id, db)

    config = await _find_api_key_config(db, document.project_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先在设置中配置 API Key",
        )
    try:
        api_key = decrypt_api_key(config.encrypted_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"API Key 解密失败：{exc}",
        ) from exc

    client = create_client(api_key=api_key, base_url=config.base_url, model=config.model)
    threshold = payload.threshold or document.parse_threshold

    try:
        candidates = await extract_candidates(
            document.content_text, client, threshold=threshold
        )
    except Exception as exc:
        document.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM 抽取失败：{exc}",
        ) from exc

    # 结果暂存到文档记录，不直接写入 KnowledgeCard
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
    await db.refresh(document)
    return candidates


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

    # 远程 embedding：优先使用项目/全局配置的 API Key；无配置则回退本地哈希向量
    embedder = None
    config = await _find_api_key_config(db, document.project_id)
    if config is not None:
        try:
            api_key = decrypt_api_key(config.encrypted_key)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"API Key 解密失败：{exc}",
            ) from exc
        embedder = Embedder(
            api_key=api_key,
            base_url=config.base_url,
            model=payload.embedding_model,
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
