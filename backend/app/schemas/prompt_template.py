# backend/app/schemas/prompt_template.py
"""提示词模板相关 Pydantic 模型（docs/TECHv1.md §5.7 / §4.3）。

- PromptTemplateCreate：POST /prompt-templates 请求体（name/content/scope/project_id?）
- PromptTemplateUpdate：PATCH /prompt-templates/{id} 请求体（仅更新显式传入的字段）
- PromptTemplateDuplicate：POST /prompt-templates/{id}/duplicate 请求体
- PromptTemplateRead：模板响应体（from_attributes 直接序列化 ORM）

scope 使用 Literal 限定 global / project，非法值由 FastAPI 返回 422；
scope 与 project_id 的搭配关系（project 必须有 project_id、global 不应有）在服务层校验，
API 层将其映射为 400。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# 模板作用域：global（全局）/ project（项目级）
PromptTemplateScope = Literal["global", "project"]


class PromptTemplateCreate(BaseModel):
    """创建模板请求体（docs/TECHv1.md §5.7）。"""

    name: str = Field(..., min_length=1, max_length=255)
    content: str
    scope: PromptTemplateScope
    project_id: Optional[str] = None  # scope=project 时必填


class PromptTemplateUpdate(BaseModel):
    """更新模板请求体：所有字段可选，仅更新显式传入的字段（exclude_unset）。

    project_id 不可通过更新修改（跨作用域复制请使用 /duplicate）。
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: Optional[str] = None
    scope: Optional[PromptTemplateScope] = None


class PromptTemplateDuplicate(BaseModel):
    """复制模板请求体（POST /prompt-templates/{id}/duplicate）。"""

    new_name: str = Field(..., min_length=1, max_length=255)
    scope: PromptTemplateScope
    project_id: Optional[str] = None  # scope=project 时必填


class PromptTemplateRead(BaseModel):
    """模板响应体（from_attributes 直接序列化 ORM PromptTemplate）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    content: str
    scope: str
    project_id: Optional[str] = None
    is_system: bool
    created_at: datetime
    updated_at: datetime
