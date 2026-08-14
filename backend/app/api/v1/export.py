# backend/app/api/v1/export.py
"""导出 API（docs/TECH.md §5.6）。

- GET /api/v1/projects/{project_id}/export?format=txt|markdown|json|docx  导出项目并下载
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import Chapter, Project
from ...services.export.exporter import ExportFormat, export_project

router = APIRouter(prefix="/api/v1", tags=["export"])

# 各格式的 Content-Type
_MEDIA_TYPES: dict[ExportFormat, str] = {
    "txt": "text/plain; charset=utf-8",
    "markdown": "text/markdown; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get(
    "/projects/{project_id}/export",
    summary="导出项目（?format=txt|markdown|json|docx）",
    response_class=FileResponse,
)
async def export_project_file(
    project_id: str,
    format: ExportFormat = Query(default="markdown"),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """导出项目全部章节为指定格式，返回文件下载。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.order, Chapter.created_at)
    )
    chapters = list(result.scalars().all())
    path = export_project(project, chapters, format)
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES[format],
        filename=path.name,
    )
