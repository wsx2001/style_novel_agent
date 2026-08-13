# backend/app/models/knowledge_card.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project


class KnowledgeCard(Base, TimestampMixin):
    __tablename__ = "knowledge_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    card_type: Mapped[str] = mapped_column(String(20))  # character|world|term|style|event
    title: Mapped[str] = mapped_column(String(255))
    content_json: Mapped[dict] = mapped_column(JSON)  # 结构化字段
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source_doc_ids: Mapped[list] = mapped_column(JSON, default=list)

    project: Mapped[Project] = relationship(back_populates="knowledge_cards")
    snippets: Mapped[list["KnowledgeSnippet"]] = relationship(back_populates="card", cascade="all, delete-orphan")
