# backend/app/models/model_provider.py
from __future__ import annotations

from typing import Optional
from uuid import uuid4

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ModelProvider(Base, TimestampMixin):
    """模型提供商：集中管理多个 API Key 与模型列表（docs/TECHv1.1.md §4.2）。

    - api_keys_json 为 list[dict]：每条含 key_id / api_key_encrypted（AES-GCM Base64，
      与旧 ApiKeyConfig.encrypted_key 同格式同主密钥，可直接迁移）/ enabled / priority / available_models。
    - models_json 为 list[dict]：每条含 model_id / enabled / supports_1m_context（是否支持 1M
      上下文，开启后文档解析对 ≤1MB 文件整篇喂入 LLM）。
    - scope：提供商作用域，V1.1 恒为 global（项目级 Key 迁移后统一转为全局提供商）。
    """

    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))  # openai|anthropic|deepseek|kimi|opencode_go|custom|other
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 自定义兼容接口地址，可选
    scope: Mapped[str] = mapped_column(String(20), default="global")  # 提供商作用域

    # 多个 API Key 信息（实际为 list，见类 docstring）
    api_keys_json: Mapped[list] = mapped_column(JSON, default=list)
    # 合并后的模型列表（实际为 list，见类 docstring）
    models_json: Mapped[list] = mapped_column(JSON, default=list)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否全局默认提供商
