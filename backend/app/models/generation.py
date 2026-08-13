# backend/app/models/generation.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project
from .chapter import Chapter
from .knowledge_card import KnowledgeCard


class GenerationRecord(Base, TimestampMixin):
    __tablename__ = "generation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    generation_type: Mapped[str] = mapped_column(String(20))  # continue|rewrite|inspire|outline
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|streaming|completed|failed
    input_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    params_json: Mapped[dict] = mapped_column(JSON)
    output_candidates: Mapped[list] = mapped_column(JSON)  # 候选文本列表
    selected_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="generation_records")
    chapter: Mapped[Optional[Chapter]] = relationship(back_populates="generation_records")
    selected_cards: Mapped[list["GenerationCardLink"]] = relationship(back_populates="generation", cascade="all, delete-orphan")


class GenerationCardLink(Base):
    __tablename__ = "generation_card_links"

    generation_id: Mapped[str] = mapped_column(ForeignKey("generation_records.id", ondelete="CASCADE"), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id", ondelete="CASCADE"), primary_key=True)
    generation: Mapped[GenerationRecord] = relationship(back_populates="selected_cards")
    card: Mapped[KnowledgeCard] = relationship()
