# backend/app/schemas/document.py
"""文档相关 Pydantic 模型（docs/TECH.md §5.2）。

- DocumentCreate：创建文档记录（内部构建，上传接口从 multipart 字段组装）
- DocumentRead：所有文档端点响应体（from_attributes 直接序列化 ORM 模型）
- DocumentParseRequest：触发解析请求体（POST /documents/{id}/parse，后续实现）
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

FileType = Literal["txt", "md", "docx"]
DocumentStatus = Literal["pending", "parsing", "parsed", "imported", "failed"]
ParseThreshold = Literal["low", "medium", "high"]


class DocumentCreate(BaseModel):
    """创建文档记录请求体。"""

    filename: str = Field(..., min_length=1, max_length=255)
    file_type: FileType
    file_size: int = Field(..., ge=0)
    content_text: str
    parse_threshold: ParseThreshold = "medium"
    require_manual_confirm: bool = True
    status: DocumentStatus = "pending"
    imported_at: str = ""


class DocumentRead(BaseModel):
    """文档响应体（含 id / 时间戳）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    filename: str
    file_type: FileType
    file_size: int
    content_text: str
    status: DocumentStatus
    parse_threshold: ParseThreshold
    require_manual_confirm: bool
    imported_at: str
    created_at: datetime
    updated_at: datetime


class DocumentParseRequest(BaseModel):
    """触发 LLM 解析请求体（docs/TECH.md §5.2 可选字段）。"""

    threshold: Optional[ParseThreshold] = None
    manual_confirm: Optional[bool] = None
