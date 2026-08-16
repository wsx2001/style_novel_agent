# backend/app/models/project.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cover_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # V1 新增：默认模型配置（深度、温度、max_tokens）
    default_model_config: Mapped[dict] = mapped_column(JSON, default=lambda: {"depth": "auto", "temperature": 0.7, "max_tokens": 0})
    # V1 新增：默认提示词模板 ID（可空，删除模板时置空）
    default_prompt_template_id: Mapped[Optional[str]] = mapped_column(ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True)

    # V1.1 新增：默认提供商与模型（空表示继承全局默认）
    default_provider_id: Mapped[Optional[str]] = mapped_column(ForeignKey("model_providers.id", ondelete="SET NULL"), nullable=True)
    default_model_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # 模型 ID 字符串

    default_provider: Mapped[Optional["ModelProvider"]] = relationship()

    documents: Mapped[list["Document"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    knowledge_cards: Mapped[list["KnowledgeCard"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    generation_records: Mapped[list["GenerationRecord"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    settings: Mapped[Optional["ProjectSettings"]] = relationship(back_populates="project", cascade="all, delete-orphan", uselist=False)
    # foreign_keys 消除歧义：projects 与 prompt_templates 存在两条外键路径
    # （PromptTemplate.project_id 与 Project.default_prompt_template_id），
    # 此处集合按 PromptTemplate.project_id 归属关联。
    prompt_templates: Mapped[list["PromptTemplate"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        foreign_keys="PromptTemplate.project_id",
    )
