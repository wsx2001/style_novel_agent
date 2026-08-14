# backend/app/schemas/project.py
"""项目相关 Pydantic 模型（docs/TECH.md §5.1）。

- ProjectCreate：POST /projects 请求体
- ProjectUpdate：PATCH /projects/{id} 请求体（所有字段可选，仅更新显式传入的字段）
- ProjectRead：所有项目端点响应体（from_attributes 直接序列化 ORM 模型）
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    """项目公共字段。"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    genre: Optional[str] = None


class ProjectCreate(ProjectBase):
    """创建项目请求体。"""


class ProjectUpdate(BaseModel):
    """更新项目请求体：title 非空，其余可省略或置空。"""

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    genre: Optional[str] = None


class ProjectRead(ProjectBase):
    """项目响应体（含 id / 时间戳 / cover_path）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    cover_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime
