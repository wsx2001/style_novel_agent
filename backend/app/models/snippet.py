# backend/app/models/snippet.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .document import Document
from .knowledge_card import KnowledgeCard


class KnowledgeSnippet(Base, TimestampMixin):
    __tablename__ = "knowledge_snippets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[Optional[str]] = mapped_column(ForeignKey("knowledge_cards.id", ondelete="SET NULL"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    start_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    document: Mapped[Document] = relationship(back_populates="snippets")
    card: Mapped[Optional[KnowledgeCard]] = relationship(back_populates="snippets")
