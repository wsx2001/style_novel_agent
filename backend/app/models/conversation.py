# backend/app/models/conversation.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project
from .chapter import Chapter


class Conversation(Base, TimestampMixin):
    """对话工作台会话：独立存储，消息不写入 GenerationRecord。"""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    model_config: Mapped[dict] = mapped_column(JSON, default=lambda: {"depth": "auto", "temperature": 0.7, "max_tokens": 2048})
    system_prompt_template_id: Mapped[Optional[str]] = mapped_column(ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True)
    system_prompt_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 会话级临时覆盖

    project: Mapped[Project] = relationship(back_populates="conversations")
    chapter: Mapped[Optional[Chapter]] = relationship()
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base, TimestampMixin):
    """对话消息：role 为 user / assistant / system。"""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text)
    message_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)  # 列名 metadata，存 token 用量、模型等

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
