# backend/app/schemas/settings.py
"""设置相关 Pydantic 模型（docs/TECH.md §5.6；V1 全局设置与深度映射，docs/TECHv1.md §5.8 / §8.1）。

- ApiKeyConfigCreate：保存 API Key 请求体（api_key 明文，后端加密存储）
- ApiKeyConfigRead：API Key 响应体（key_masked 为脱敏后的 key，不暴露明文）
- GlobalAppConfigRead / GlobalAppConfigUpdate：全局设置（GET/PATCH /settings/app）
- DepthMappingUpdate：思维深度映射更新（PATCH /settings/depth-mapping）
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ApiProvider = Literal["openai", "deepseek", "kimi", "moonshot", "custom"]


class ApiKeyConfigCreate(BaseModel):
    """保存 API Key 请求体。"""

    provider: ApiProvider
    name: str = Field(..., min_length=1, max_length=100)
    api_key: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1, max_length=500)
    model: Optional[str] = Field(default=None, max_length=100)
    is_default: bool = False


class ApiKeyConfigRead(BaseModel):
    """API Key 响应体（key 已脱敏）。"""

    id: str
    provider: ApiProvider
    name: str
    key_masked: str
    base_url: str
    model: Optional[str]
    is_default: bool
    created_at: datetime
    updated_at: datetime


class GlobalAppConfigRead(BaseModel):
    """GET /settings/app 响应体（从 AppConfig 表读取，docs/TECHv1.md §5.8）。

    global_default_prompt_template_id 为字符串（空串表示未设置全局默认模板）。
    """

    global_default_model_config: dict = Field(default_factory=dict)
    global_default_prompt_template_id: str = ""


class GlobalAppConfigUpdate(BaseModel):
    """PATCH /settings/app 请求体：所有字段可选，仅更新显式传入的字段。

    global_default_prompt_template_id 传空串表示清除全局默认模板；
    global_default_model_config 传空对象表示清除全局默认模型配置。
    """

    global_default_model_config: Optional[dict] = None
    global_default_prompt_template_id: Optional[str] = None


class DepthMappingUpdate(BaseModel):
    """PATCH /settings/depth-mapping 请求体（docs/TECHv1.md §8.1）。

    仅更新显式传入的字段（partial update）：default 与 model_overrides 均可省略，
    省略的字段保留 AppConfig 中既有值。
    """

    default: Optional[dict] = None
    model_overrides: Optional[dict] = None
