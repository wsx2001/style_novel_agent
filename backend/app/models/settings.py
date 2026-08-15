# backend/app/models/settings.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Boolean, Float, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project


class ProjectSettings(Base, TimestampMixin):
    __tablename__ = "project_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    auto_parse_confirm: Mapped[bool] = mapped_column(Boolean, default=True)
    default_temperature: Mapped[float] = mapped_column(Float, default=0.8)
    default_max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    default_view: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    project: Mapped[Project] = relationship(back_populates="settings")


class AppConfig(Base, TimestampMixin):
    __tablename__ = "app_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[dict] = mapped_column(JSON)
