# backend/app/models/document.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))  # txt | md | docx
    file_size: Mapped[int] = mapped_column(Integer)
    content_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|parsing|parsed|imported|failed
    parse_threshold: Mapped[str] = mapped_column(String(10), default="medium")  # low|medium|high
    require_manual_confirm: Mapped[bool] = mapped_column(Boolean, default=True)
    imported_at: Mapped[str] = mapped_column(String(30), default="")  # ISO datetime
    parse_result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # LLM 抽取候选卡片暂存

    project: Mapped[Project] = relationship(back_populates="documents")
    snippets: Mapped[list["KnowledgeSnippet"]] = relationship(back_populates="document", cascade="all, delete-orphan")
