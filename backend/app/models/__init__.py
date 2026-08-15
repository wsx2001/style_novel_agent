"""SQLAlchemy 模型包：导入所有模型以注册到 Base.metadata。

导入顺序保证无循环依赖：base -> model_provider -> project -> document
-> knowledge_card -> snippet -> chapter -> generation -> version -> settings
-> prompt_template -> conversation
"""
from .base import Base, TimestampMixin
from .model_provider import ModelProvider
from .project import Project
from .document import Document
from .knowledge_card import KnowledgeCard
from .snippet import KnowledgeSnippet
from .chapter import Chapter, ChapterKnowledgeCard
from .generation import GenerationRecord, GenerationCardLink
from .version import VersionSnapshot
from .settings import ProjectSettings, AppConfig
from .prompt_template import PromptTemplate
from .conversation import Conversation, Message

__all__ = [
    "Base",
    "TimestampMixin",
    "ModelProvider",
    "Project",
    "Document",
    "KnowledgeCard",
    "KnowledgeSnippet",
    "Chapter",
    "ChapterKnowledgeCard",
    "GenerationRecord",
    "GenerationCardLink",
    "VersionSnapshot",
    "ProjectSettings",
    "AppConfig",
    "PromptTemplate",
    "Conversation",
    "Message",
]
