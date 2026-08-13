# backend/app/models/project.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cover_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    documents: Mapped[list["Document"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    knowledge_cards: Mapped[list["KnowledgeCard"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    generation_records: Mapped[list["GenerationRecord"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    api_key_configs: Mapped[list["ApiKeyConfig"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    settings: Mapped[Optional["ProjectSettings"]] = relationship(back_populates="project", cascade="all, delete-orphan", uselist=False)
