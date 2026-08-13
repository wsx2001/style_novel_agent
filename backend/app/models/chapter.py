# backend/app/models/chapter.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project


class Chapter(Base, TimestampMixin):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    order: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, default="")  # Markdown
    status: Mapped[str] = mapped_column(String(20), default="draft")
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="chapters")
    children: Mapped[list["Chapter"]] = relationship(back_populates="parent", cascade="all")
    parent: Mapped[Optional["Chapter"]] = relationship(back_populates="children", remote_side="[Chapter.id]")
    generation_records: Mapped[list["GenerationRecord"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    version_snapshots: Mapped[list["VersionSnapshot"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    selected_cards: Mapped[list["ChapterKnowledgeCard"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class ChapterKnowledgeCard(Base):
    """章节与知识卡的多对多关联（章节写作时选中的设定卡）。

    注：TECH.md §4 在 Chapter.selected_cards 中引用了该模型但未给出定义，
    此处按 GenerationCardLink 的写法补齐，否则映射器配置会失败。
    """
    __tablename__ = "chapter_knowledge_cards"

    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id", ondelete="CASCADE"), primary_key=True)

    chapter: Mapped["Chapter"] = relationship(back_populates="selected_cards")
    card: Mapped["KnowledgeCard"] = relationship()
