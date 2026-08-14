# backend/app/schemas/settings.py
"""设置相关 Pydantic 模型（docs/TECH.md §5.6）。

- ApiKeyConfigCreate：保存 API Key 请求体（api_key 明文，后端加密存储）
- ApiKeyConfigRead：API Key 响应体（key_masked 为脱敏后的 key，不暴露明文）
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
