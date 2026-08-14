# backend/app/api/v1/chapters.py
"""章节 API（docs/TECH.md §5.4）。

- GET    /api/v1/projects/{project_id}/chapters   章节列表（按 order 排序）
- POST   /api/v1/projects/{project_id}/chapters   新建章节
- GET    /api/v1/chapters/{chapter_id}            章节详情
- PATCH  /api/v1/chapters/{chapter_id}            更新章节（title/content/word_count）
- DELETE /api/v1/chapters/{chapter_id}            删除章节
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import Chapter, Project
from ...schemas.chapter import ChapterCreate, ChapterRead, ChapterUpdate

router = APIRouter(prefix="/api/v1", tags=["chapters"])

# CJK 字符区间（含扩展 A）
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
# 英文单词 / 数字串（中英文混排时按词计，标点不计）
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def count_words(text: str) -> int:
    """统计正文字数：CJK 每字计 1，英文单词/数字按词计。"""
    return len(_CJK_RE.findall(text)) + len(_WORD_RE.findall(text))


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    """按 id 查询项目，不存在则抛 404。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


async def _get_chapter_or_404(chapter_id: str, db: AsyncSession) -> Chapter:
    """按 id 查询章节，不存在则抛 404。"""
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"章节 {chapter_id} 不存在",
        )
    return chapter


@router.get(
    "/projects/{project_id}/chapters",
    response_model=list[ChapterRead],
    summary="章节列表（按 order 升序）",
)
async def list_chapters(
    project_id: str, db: AsyncSession = Depends(get_db)
) -> list[Chapter]:
    await _get_project_or_404(project_id, db)
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.order, Chapter.created_at)
    )
    return list(result.scalars().all())


@router.post(
    "/projects/{project_id}/chapters",
    response_model=ChapterRead,
    status_code=status.HTTP_201_CREATED,
    summary="新建章节",
)
async def create_chapter(
    project_id: str,
    payload: ChapterCreate,
    db: AsyncSession = Depends(get_db),
) -> Chapter:
    await _get_project_or_404(project_id, db)
    chapter = Chapter(
        project_id=project_id,
        title=payload.title,
        parent_id=payload.parent_id,
        order=payload.order,
    )
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.get("/chapters/{chapter_id}", response_model=ChapterRead, summary="章节详情")
async def get_chapter(
    chapter_id: str, db: AsyncSession = Depends(get_db)
) -> Chapter:
    return await _get_chapter_or_404(chapter_id, db)


@router.patch("/chapters/{chapter_id}", response_model=ChapterRead, summary="更新章节")
async def update_chapter(
    chapter_id: str,
    payload: ChapterUpdate,
    db: AsyncSession = Depends(get_db),
) -> Chapter:
    chapter = await _get_chapter_or_404(chapter_id, db)
    data = payload.model_dump(exclude_unset=True)
    if "content" in data and data["content"] is not None:
        data["word_count"] = count_words(data["content"])
    for field, value in data.items():
        setattr(chapter, field, value)
    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.delete(
    "/chapters/{chapter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除章节",
)
async def delete_chapter(chapter_id: str, db: AsyncSession = Depends(get_db)) -> None:
    chapter = await _get_chapter_or_404(chapter_id, db)
    await db.delete(chapter)
    await db.commit()
