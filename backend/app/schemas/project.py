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
    # V1：项目默认模型配置 / 默认提示词模板（docs/TECHv1.md §4.2 / §5.8）
    default_model_config: Optional[dict] = None
    default_prompt_template_id: Optional[str] = None
    # V1.1：项目默认提供商与模型（null 表示继承全局默认，docs/TECHv1.1.md §5.2）
    default_provider_id: Optional[str] = None
    default_model_id: Optional[str] = None


class ProjectRead(ProjectBase):
    """项目响应体（含 id / 时间戳 / cover_path；V1 起含默认模型配置与默认模板）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    cover_path: Optional[str] = None
    # V1：项目默认模型配置与默认提示词模板（docs/TECHv1.md §4.2）
    default_model_config: dict = Field(default_factory=dict)
    default_prompt_template_id: Optional[str] = None
    # V1.1：项目默认提供商与模型（docs/TECHv1.1.md §4.3）
    default_provider_id: Optional[str] = None
    default_model_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
