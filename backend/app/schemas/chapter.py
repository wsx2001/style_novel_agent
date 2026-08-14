# backend/app/schemas/chapter.py
"""章节相关 Pydantic 模型（docs/TECH.md §5.4）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ChapterCreate(BaseModel):
    """新建章节请求体。"""

    title: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[str] = None
    order: int = Field(default=0, ge=0)


class ChapterRead(BaseModel):
    """章节响应体（含 id / 正文 / 字数 / 时间戳）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    parent_id: Optional[str]
    title: str
    order: int
    content: str
    status: str
    word_count: int
    created_at: datetime
    updated_at: datetime


class ChapterUpdate(BaseModel):
    """更新章节请求体（所有字段可选）。"""

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: Optional[str] = None
    word_count: Optional[int] = Field(default=None, ge=0)
