# backend/app/schemas/generation.py
"""AI 生成相关 Pydantic 模型（docs/TECH.md §5.5）。

- ContinueRequest：续写请求（POST /chapters/{id}/generate/continue）
- RewriteRequest：重写请求（POST /chapters/{id}/generate/rewrite）
- InspireRequest：灵感生成请求（POST /projects/{id}/generate/inspire）
- GenerationRead：生成记录响应体（from_attributes 直接序列化 ORM 模型）
- InspireResponse：灵感生成响应体（简单实现，同步返回）
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

GenerationType = Literal["continue", "rewrite", "inspire", "outline"]
GenerationStatus = Literal["pending", "streaming", "completed", "failed"]


class ContinueRequest(BaseModel):
    """续写请求体（docs/TECH.md §5.5）。"""

    prompt: Optional[str] = None  # 额外续写要求
    card_ids: list[str] = Field(default_factory=list)
    target_words: int = Field(default=500, ge=50, le=5000)
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    view: Optional[str] = None  # 叙事视角（第一人称/第三人称等）
    candidate_count: int = Field(default=3, ge=1, le=5)


class RewriteRequest(BaseModel):
    """重写请求体（docs/TECH.md §5.5）。"""

    selected_text: str = Field(..., min_length=1)
    instruction: Optional[str] = None
    card_ids: list[str] = Field(default_factory=list)
    style_card_id: Optional[str] = None
    target_words: int = Field(default=500, ge=50, le=5000)
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    candidate_count: int = Field(default=3, ge=1, le=5)


class InspireRequest(BaseModel):
    """灵感生成请求体（简单实现，docs/TECH.md §5.5）。"""

    idea: str = Field(..., min_length=1, max_length=500)
    temperature: float = Field(default=0.9, ge=0.0, le=2.0)


class GenerationRead(BaseModel):
    """生成记录响应体（含 id / 时间戳 / 候选文本）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    chapter_id: Optional[str]
    generation_type: GenerationType
    status: GenerationStatus
    input_text: Optional[str]
    params_json: dict
    output_candidates: list[str]
    selected_output: Optional[str]
    created_at: datetime
    updated_at: datetime


class InspireResponse(BaseModel):
    """灵感生成响应体（简单实现）。"""

    id: str
    content: str
