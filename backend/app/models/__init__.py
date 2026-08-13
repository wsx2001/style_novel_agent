"""SQLAlchemy 模型包：导入所有模型以注册到 Base.metadata。

导入顺序保证无循环依赖：base -> project -> document -> knowledge_card
-> snippet -> chapter -> generation -> version -> settings
"""
from .base import Base, TimestampMixin
from .project import Project
from .document import Document
from .knowledge_card import KnowledgeCard
from .snippet import KnowledgeSnippet
from .chapter import Chapter, ChapterKnowledgeCard
from .generation import GenerationRecord, GenerationCardLink
from .version import VersionSnapshot
from .settings import ProjectSettings, ApiKeyConfig, AppConfig

__all__ = [
    "Base",
    "TimestampMixin",
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
    "ApiKeyConfig",
    "AppConfig",
]
