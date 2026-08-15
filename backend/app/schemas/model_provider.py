# backend/app/schemas/model_provider.py
"""模型提供商相关 Pydantic 模型（docs/TECHv1.1.md §4.2 / §5.1 / PRD v1.1 §2.1）。

- ApiKeyInput：创建/更新提供商时提交的 API Key 项（key 明文 / 脱敏占位符均可）；
- ApiKeyRead：提供商详情中的 Key（脱敏，key_masked 只含首尾字符，绝不含明文或密文）；
- ModelItem：模型列表项（model_id + enabled）；
- ModelProviderCreate / ModelProviderUpdate：创建 / 更新提供商请求体；
- ModelProviderRead：提供商详情响应体；
- ProviderSummary：提供商列表摘要（不含任何 Key 信息）；
- ModelFetchResult / KeyDetectResult：获取模型 / 检测 Key 的响应体；
- ModelProviderCreateResponse：创建提供商响应（provider 详情 + 自动获取模型结果与提示）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# 提供商类型枚举（docs/TECHv1.1.md §4.2）
ModelProviderType = Literal[
    "openai", "anthropic", "deepseek", "kimi", "opencode_go", "custom", "other"
]


class ApiKeyInput(BaseModel):
    """创建/更新提供商时提交的 API Key 项。

    - key：新增 Key 时必须提供明文；更新未改动的 Key 可回传脱敏占位符
      （如 ``sk-a...3456``），服务端识别后复用旧密文；
    - key_id：更新已有 Key 时回传；新增可省略。
    """

    key: Optional[str] = None
    key_id: Optional[str] = None
    enabled: bool = True
    priority: int = Field(default=1, ge=1)


class ModelItem(BaseModel):
    """模型列表项（model_id + 启用状态）。"""

    model_id: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True


class ModelProviderCreate(BaseModel):
    """创建提供商请求体（docs/TECHv1.1.md §5.1）。"""

    name: str = Field(..., min_length=1, max_length=255)
    type: ModelProviderType
    base_url: Optional[str] = None
    api_keys: list[ApiKeyInput] = Field(default_factory=list)
    # 创建成功后是否自动获取模型列表（默认自动；失败不阻断创建，models 为空并提示）
    auto_fetch: bool = True


class ModelProviderUpdate(BaseModel):
    """更新提供商请求体：所有字段可选，仅更新显式传入的字段（exclude_unset）。

    - api_keys：一次全量替换（新增 / 删除 / 改优先级 / 换明文均在此处理，
      未改动的 Key 由前端回传脱敏占位符，服务端复用旧密文）；
    - models：一次全量替换（支持启停模型）。
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    type: Optional[ModelProviderType] = None
    base_url: Optional[str] = None
    api_keys: Optional[list[ApiKeyInput]] = None
    models: Optional[list[ModelItem]] = None


class ApiKeyRead(BaseModel):
    """提供商详情中的 API Key（脱敏，key_masked 只含首尾字符）。"""

    key_id: str
    key_masked: str
    enabled: bool
    priority: int
    available_models: list[str] = Field(default_factory=list)


class ModelProviderRead(BaseModel):
    """提供商详情响应体（api_keys 脱敏、models 含启用状态）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    scope: str = "global"
    base_url: Optional[str] = None
    is_default: bool = False
    api_keys: list[ApiKeyRead] = Field(default_factory=list)
    models: list[ModelItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProviderSummary(BaseModel):
    """提供商列表摘要（不含任何 Key 信息）。

    status 为派生状态：``ready``（有启用 Key，可用于生成）/ ``no_keys``（无启用 Key）。
    """

    id: str
    name: str
    type: str
    scope: str = "global"
    base_url: Optional[str] = None
    is_default: bool = False
    key_count: int = 0
    enabled_key_count: int = 0
    model_count: int = 0
    enabled_model_count: int = 0
    status: str = "no_keys"
    created_at: datetime
    updated_at: datetime


class ModelFetchResult(BaseModel):
    """获取模型列表结果（fetch-models / 创建时自动获取）。"""

    success: bool
    models: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)  # [{key_id, error}, ...]


class KeyDetectResult(BaseModel):
    """单个 Key 连接检测结果。"""

    key_id: str
    valid: bool
    error: Optional[str] = None
    model_count: int = 0


class ModelProviderCreateResponse(BaseModel):
    """创建提供商响应：provider 详情 + 自动获取模型的结果与提示。

    - auto_fetch 为 None：未触发获取（auto_fetch=false）；
    - auto_fetch.success 为 False：provider 已创建但 models 为空，
      message 提示「未获取到模型」。
    """

    provider: ModelProviderRead
    auto_fetch: Optional[ModelFetchResult] = None
    message: Optional[str] = None
