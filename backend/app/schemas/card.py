# backend/app/schemas/card.py
"""知识卡相关 Pydantic 模型（docs/TECH.md §5.3）。

- CardCreate：手动新建知识卡
- CardRead：卡片响应体（from_attributes 直接序列化 ORM 模型）
- CardUpdate：卡片更新字段（部分可选，供后续 PATCH 使用）
- ConfirmImportRequest / ConfirmImportResponse：确认导入请求 / 响应
- SnippetChunkRead：确认导入前的文档分块预览
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .document import CardType


class CardCreate(BaseModel):
    """手动新建知识卡请求体。"""

    card_type: CardType
    title: str = Field(..., min_length=1, max_length=255)
    content_json: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class CardRead(BaseModel):
    """知识卡响应体（含 id / 时间戳 / 来源文档）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    card_type: CardType
    title: str
    content_json: dict
    tags: list[str]
    source_doc_ids: list[str]
    created_at: datetime
    updated_at: datetime


class CardUpdate(BaseModel):
    """更新知识卡请求体（所有字段可选，未传字段保持不变）。"""

    card_type: Optional[CardType] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content_json: Optional[dict] = None
    tags: Optional[list[str]] = None


class ConfirmImportCard(BaseModel):
    """确认导入的单个卡片：内容 + 关联片段 id（片段 id 来自文档分块预览）。"""

    card_type: CardType
    title: str = Field(..., min_length=1, max_length=255)
    content_json: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    snippet_ids: list[str] = Field(default_factory=list)


class ConfirmImportRequest(BaseModel):
    """确认导入请求体：卡片列表 +（可选）覆盖 embedding 模型。"""

    cards: list[ConfirmImportCard]
    embedding_model: Optional[str] = None


class ConfirmImportResponse(BaseModel):
    """确认导入响应：创建的卡片 + 写入 Chroma 的片段数。"""

    cards: list[CardRead]
    snippet_count: int


class SnippetChunkRead(BaseModel):
    """文档分块预览（确认导入前的片段，含标签与偏移）。"""

    id: str
    text: str
    tags: list[str]
    start: int
    end: int
