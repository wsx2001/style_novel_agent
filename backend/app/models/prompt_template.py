# backend/app/models/prompt_template.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, Text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project


class PromptTemplate(Base, TimestampMixin):
    """系统提示词模板（全局或项目级，可含 {{VARIABLE}} 占位符）。"""

    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)  # 可含 {{VARIABLE}} 占位符
    scope: Mapped[str] = mapped_column(String(20))  # "global" 或 "project"
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # 系统内置模板不可删除

    # foreign_keys 消除歧义：projects 与 prompt_templates 存在两条外键路径
    # （PromptTemplate.project_id 与 Project.default_prompt_template_id），
    # 此处按 PromptTemplate.project_id 归属关联。
    project: Mapped[Optional[Project]] = relationship(
        back_populates="prompt_templates",
        foreign_keys="[PromptTemplate.project_id]",
    )
