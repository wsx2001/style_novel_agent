# backend/app/api/v1/documents.py
"""文档上传与查询 API（docs/TECH.md §5.2）。

- POST /api/v1/projects/{project_id}/documents      上传文档（multipart）
- GET  /api/v1/projects/{project_id}/documents      文档列表（?status= 过滤）
- GET  /api/v1/documents/{document_id}              文档详情
- POST /api/v1/documents/{document_id}/parse        触发 LLM 解析（后续实现）
- POST /api/v1/documents/{document_id}/confirm-import 确认导入（后续实现）
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
from ...models import Document, Project
from ...schemas.document import DocumentRead
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
