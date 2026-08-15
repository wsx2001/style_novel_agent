# backend/app/schemas/settings.py
"""设置相关 Pydantic 模型（docs/TECH.md §5.6；V1 全局设置与深度映射，docs/TECHv1.md §5.8 / §8.1；
V1.1 新增全局默认提供商/模型，docs/TECHv1.1.md §5.5）。

- GlobalAppConfigRead / GlobalAppConfigUpdate：全局设置（GET/PATCH /settings/app）
- DepthMappingUpdate：思维深度映射更新（PATCH /settings/depth-mapping）

注：V1.1 起旧 API Key 管理（ApiKeyConfig）已迁移到 ModelProvider，/settings/keys 端点移除。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GlobalAppConfigRead(BaseModel):
    """GET /settings/app 响应体（从 AppConfig 表读取，docs/TECHv1.md §5.8 / TECHv1.1.md §5.5）。

    global_default_prompt_template_id 为字符串（空串表示未设置全局默认模板）；
    global_default_provider_id / global_default_model_id 为空串表示未设置全局默认提供商/模型。
    """

    global_default_model_config: dict = Field(default_factory=dict)
    global_default_prompt_template_id: str = ""
    global_default_provider_id: str = ""
    global_default_model_id: str = ""


class GlobalAppConfigUpdate(BaseModel):
    """PATCH /settings/app 请求体：所有字段可选，仅更新显式传入的字段。

    global_default_prompt_template_id 传空串表示清除全局默认模板；
    global_default_model_config 传空对象表示清除全局默认模型配置；
    global_default_provider_id / global_default_model_id 传空串表示清除全局默认提供商/模型。
    """

    global_default_model_config: Optional[dict] = None
    global_default_prompt_template_id: Optional[str] = None
    global_default_provider_id: Optional[str] = None
    global_default_model_id: Optional[str] = None


class DepthMappingUpdate(BaseModel):
    """PATCH /settings/depth-mapping 请求体（docs/TECHv1.md §8.1）。

    仅更新显式传入的字段（partial update）：default 与 model_overrides 均可省略，
    省略的字段保留 AppConfig 中既有值。
    """

    default: Optional[dict] = None
    model_overrides: Optional[dict] = None
