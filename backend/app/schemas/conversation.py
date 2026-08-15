# backend/app/schemas/conversation.py
"""对话相关 Pydantic 模型（docs/TECHv1.md §5.6 / §4.4）。

- ConversationCreate：POST /projects/{id}/conversations 请求体
- ConversationUpdate：PATCH /conversations/{id} 请求体（所有字段可选，仅更新显式传入的字段）
- ConversationRead：对话响应体（from_attributes 直接序列化 ORM）
- ConversationDetailRead：对话详情响应体（含消息列表）
- MessageRead：消息响应体
- MessageSendRequest：POST /conversations/{id}/messages 请求体

注意：Pydantic v2 中 `model_config` 是保留属性名，不能用作字段名。
因此对话的 model_config 在 Python 侧命名为 conversation_config，
通过 validation_alias / serialization_alias 保持对外 JSON 键仍为 model_config。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# 对话默认模型配置（与模型 / 全局默认一致，docs/TECHv1.md §4.4）
DEFAULT_CONVERSATION_MODEL_CONFIG = {
    "depth": "auto",
    "temperature": 0.7,
    "max_tokens": 2048,
}

# Pydantic 保留 `model_config` 作配置属性，不能作为字段名。因此 Python 侧字段承接名统一为
# conversation_config，validation_alias 允许请求体以 model_config 键写入、
# ORM 序列化时读取 Conversation.model_config；serialization_alias 保证响应 JSON 键为 model_config。
# 每个类各自内联 Field（不跨模型复用 FieldInfo 实例）。


class ConversationCreate(BaseModel):
    """创建对话请求体（docs/TECHv1.md §5.6）。"""

    model_config = ConfigDict(populate_by_name=True)

    title: Optional[str] = None  # 缺省由服务层置为"新对话"
    chapter_id: Optional[str] = None
    conversation_config: Optional[dict] = Field(
        default=None,
        validation_alias=AliasChoices("model_config", "conversation_config"),
        serialization_alias="model_config",
    )
    system_prompt_template_id: Optional[str] = None


class ConversationUpdate(BaseModel):
    """更新对话请求体：所有字段可选，仅更新显式传入的字段（exclude_unset）。"""

    model_config = ConfigDict(populate_by_name=True)

    title: Optional[str] = None
    conversation_config: Optional[dict] = Field(
        default=None,
        validation_alias=AliasChoices("model_config", "conversation_config"),
        serialization_alias="model_config",
    )
    system_prompt_template_id: Optional[str] = None
    system_prompt_override: Optional[str] = None


class MessageRead(BaseModel):
    """消息响应体（from_attributes 直接序列化 ORM Message）。

    存储列名为 metadata（模型属性 message_metadata），响应 JSON 键对外统一为 metadata。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    message_metadata: dict = Field(default_factory=dict, serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


class ConversationRead(BaseModel):
    """对话响应体（from_attributes 直接序列化 ORM Conversation）。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str
    chapter_id: Optional[str] = None
    title: str
    conversation_config: dict = Field(
        default_factory=lambda: dict(DEFAULT_CONVERSATION_MODEL_CONFIG),
        validation_alias=AliasChoices("model_config", "conversation_config"),
        serialization_alias="model_config",
    )
    system_prompt_template_id: Optional[str] = None
    system_prompt_override: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailRead(ConversationRead):
    """对话详情响应体（含消息列表，docs/TECHv1.md §5.6）。"""

    messages: list[MessageRead] = Field(default_factory=list)


class MessageSendRequest(BaseModel):
    """发送消息请求体（POST /conversations/{id}/messages）。"""

    content: str = Field(..., min_length=1, max_length=20000)
