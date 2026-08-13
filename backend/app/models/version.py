# backend/app/models/version.py
from __future__ import annotations
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .chapter import Chapter


class VersionSnapshot(Base, TimestampMixin):
    __tablename__ = "version_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(String(255), default="")

    chapter: Mapped[Chapter] = relationship(back_populates="version_snapshots")
