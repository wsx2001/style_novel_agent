# FictionForge 技术约束文档（Tech Spec / Architecture Doc）

> 版本：v0.4  
> 关联 PRD：FictionForge v0.2  
> 最终架构：**纯本地 Python 后端 + Vite/React 前端 + SQLite + Chroma 嵌入式**  
> 运行方式：源码运行，浏览器作为界面，Git 拉取更新  
> 说明：本版根据最新澄清重构，完全移除云端依赖和桌面壳，聚焦本地 AI 写作工具的开发效率与隐私。

---

## 0. 架构总览

```
┌──────────────────────────────────────────────────────────┐
│                    用户浏览器（本地）                     │
│              http://127.0.0.1:8000                       │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP (FastAPI)
                         ▼
┌──────────────────────────────────────────────────────────┐
│              Python FastAPI 后端进程                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ 静态文件服务  │  │  API 路由     │  │  业务逻辑层     │  │
│  │  (React 构建) │  │  - projects   │  │  - LLM 客户端  │  │
│  │              │  │  - documents  │  │  - 文档解析    │  │
│  │              │  │  - cards      │  │  - 知识检索    │  │
│  │              │  │  - chapters   │  │  - 导出        │  │
│  │              │  │  - generation │  │  - 加密        │  │
│  └──────────────┘  └──────────────┘  └────────┬────────┘  │
│                                                │           │
│                          ┌─────────────────────┼─────────┐ │
│                          │  SQLite 数据库      │         │ │
│                          │  Chroma 向量库      │         │ │
│                          │  本地文件系统       │         │ │
│                          └─────────────────────┴─────────┘ │
└──────────────────────────────────────────────────────────┘
```

**核心特征**：
- 前端为 Vite + React 单页应用，构建产物由 FastAPI 静态托管。
- 后端使用 FastAPI 提供 REST API，所有业务逻辑均在 Python 中完成。
- 数据存储：SQLite（关系数据）+ Chroma 嵌入式（向量）+ 本地文件系统（文档原文件、导出文件）。
- API Key 使用 AES-256-GCM 加密后存入 SQLite，主密钥保存在本地配置文件中（权限限制），不通过环境变量传递。
- 用户通过 Git 克隆/拉取项目源码，手动安装依赖，运行启动脚本即可。

---

## 1. 技术选型建议

### 1.1 后端（Python）

| 类别 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | AI 生态丰富，开发效率高 |
| Web 框架 | FastAPI + Uvicorn | 高性能、自动生成 OpenAPI 文档、支持异步 |
| 数据验证 | Pydantic v2 | 与 FastAPI 深度集成，类型安全 |
| ORM | SQLAlchemy 2.0（async） + Alembic | 成熟稳定，支持异步，迁移工具完善 |
| 数据库 | SQLite（WAL 模式） | 本地单文件，零配置，适合单用户 |
| 向量数据库 | Chroma 嵌入式模式（`chromadb` PersistentClient） | 轻量，Python 原生，无需单独服务 |
| LLM 客户端 | `openai` Python SDK | 支持所有 OpenAI-compatible API（OpenAI、DeepSeek、Kimi、Moonshot 等），可自定义 `base_url` |
| 流式处理 | `httpx`（异步）或 `openai` SDK 的流式接口 | 用于 SSE 流式生成 |
| 文档解析 | `python-docx`（docx）、`markdown` 库（md）、纯文本（txt） | 提取纯文本 |
| 加密 | `cryptography` 库（AESGCM） | API Key 加密存储 |
| 日志 | Python `logging` + `rich` | 本地日志输出，方便调试 |
| 配置管理 | `pydantic-settings` | 从环境变量或配置文件加载全局配置 |

### 1.2 前端

| 类别 | 选型 | 理由 |
|------|------|------|
| 框架 | Vite + React 18 + TypeScript | 轻量快速，构建产物小 |
| UI | Tailwind CSS + shadcn/ui（可选） | 现代 UI，开发效率高 |
| 状态管理 | Zustand + TanStack Query | 适合复杂客户端状态与 API 缓存 |
| 富文本编辑器 | Milkdown（Markdown 编辑器） | 数据格式为 Markdown，符合存储与导出需求 |
| 文件上传 | React Dropzone | 文档导入拖拽 |
| Markdown 渲染 | `react-markdown` + `remark-gfm` | 预览与展示 |
| API 请求 | Axios 或原生 `fetch` | 本地 API，无需复杂封装 |
| 路由 | React Router v6 | 前端路由管理 |

### 1.3 开发与部署工具

| 类别 | 选型 | 理由 |
|------|------|------|
| 前端构建 | Vite | 快速构建，HMR |
| 后端依赖管理 | `pip` + `requirements.txt`（或 `pyproject.toml` + Poetry） | 简单，用户手动安装 |
| Git 更新 | 用户手动 `git pull` | 按用户要求 |
| 启动脚本 | `start.sh` / `start.bat`（仅启动服务，不安装依赖） | 提供方便启动 |
| 代码质量 | Ruff（lint）+ Black（format） | 保持代码整洁 |

---

## 2. 项目目录结构

```
fictionforge/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                     # FastAPI 入口
│   │   ├── config.py                   # 全局配置（pydantic-settings）
│   │   ├── database.py                 # SQLAlchemy engine / session
│   │   ├── models/                     # SQLAlchemy 模型
│   │   │   ├── __init__.py
│   │   │   ├── project.py
│   │   │   ├── document.py
│   │   │   ├── knowledge_card.py
│   │   │   ├── chapter.py
│   │   │   ├── generation.py
│   │   │   ├── version.py
│   │   │   └── settings.py
│   │   ├── schemas/                    # Pydantic DTO
│   │   │   ├── __init__.py
│   │   │   ├── project.py
│   │   │   ├── document.py
│   │   │   ├── card.py
│   │   │   ├── chapter.py
│   │   │   ├── generation.py
│   │   │   └── common.py
│   │   ├── api/                        # API 路由
│   │   │   ├── __init__.py
│   │   │   ├── deps.py                 # 依赖注入
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── projects.py
│   │   │       ├── documents.py
│   │   │       ├── cards.py
│   │   │       ├── chapters.py
│   │   │       ├── generations.py
│   │   │       ├── export.py
│   │   │       └── settings.py
│   │   ├── services/                   # 业务逻辑层
│   │   │   ├── llm/
│   │   │   │   ├── client.py           # OpenAI-compatible 客户端封装
│   │   │   │   ├── prompts.py          # Prompt 模板
│   │   │   │   └── stream.py           # 流式处理
│   │   │   ├── embedding/
│   │   │   │   └── embedder.py         # Embedding 调用
│   │   │   ├── parsing/
│   │   │   │   ├── extractor.py        # LLM 抽取知识卡
│   │   │   │   └── chunker.py          # 文本分块
│   │   │   ├── retrieval/
│   │   │   │   └── hybrid.py           # Chroma 向量检索 + 关键词检索
│   │   │   ├── export/
│   │   │   │   └── exporter.py         # 导出为 json/txt/docx/markdown
│   │   │   └── crypto/
│   │   │       └── api_key.py          # AES-GCM 加密/解密
│   │   └── utils/
│   │       ├── file_parser.py          # txt/md/docx 文件读取
│   │       └── logger.py
│   ├── alembic/                        # 数据库迁移
│   │   ├── env.py
│   │   └── versions/
│   ├── data/                           # 默认数据目录（运行时生成）
│   │   ├── fictionforge.db
│   │   ├── chroma/                     # Chroma 持久化目录
│   │   ├── documents/                  # 文档原文件
│   │   └── exports/
│   ├── requirements.txt
│   └── start.py                        # 启动脚本（不装依赖）
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/                        # Axios 实例与 API 函数
│   │   ├── components/
│   │   │   ├── editor/
│   │   │   ├── cards/
│   │   │   ├── documents/
│   │   │   └── layout/
│   │   ├── pages/
│   │   │   ├── ProjectList.tsx
│   │   │   ├── ProjectWorkspace.tsx
│   │   │   ├── KnowledgeBase.tsx
│   │   │   ├── DocumentParse.tsx
│   │   │   ├── ChapterEditor.tsx
│   │   │   └── Settings.tsx
│   │   ├── store/
│   │   └── types/
│   ├── public/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── .gitignore
├── README.md
├── start.bat                           # Windows 启动脚本
└── start.sh                            # Linux/Mac 启动脚本
```

---

## 3. 环境变量清单

由于是本地应用，环境变量仅用于基础配置，不包含敏感信息。所有敏感配置（API Key）均通过应用内设置界面加密存储。

**.env 示例（可选，也可使用 config.py 默认值）**：

```env
# FictionForge 本地后端配置
HOST=127.0.0.1
PORT=8000
LOG_LEVEL=INFO
DATA_DIR=./data                     # 数据目录（相对或绝对路径）
DATABASE_URL=sqlite:///./data/fictionforge.db
CHROMA_PERSIST_DIR=./data/chroma
FRONTEND_DIST=../frontend/dist      # 前端构建产物路径
```

**说明**：
- `DATA_DIR` 默认为后端运行目录下的 `data` 文件夹，可通过环境变量覆盖。
- API Key 不在环境变量中配置，而是通过应用内“设置”界面输入，加密后存入 SQLite。
- 主加密密钥保存在 `DATA_DIR/secret.key`（权限 600），若文件不存在则首次启动自动生成。

---

## 4. 数据模型设计

使用 SQLAlchemy 2.0（类型注解）定义模型。以下为精简但完整的模型代码，可直接用于项目。

```python
# backend/app/models/base.py
from datetime import datetime
from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

```python
# backend/app/models/project.py
from __future__ import annotations
from typing import Optional
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
```

```python
# backend/app/models/document.py
from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project

class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))  # txt | md | docx
    file_size: Mapped[int] = mapped_column(Integer)
    content_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|parsing|parsed|imported|failed
    parse_threshold: Mapped[str] = mapped_column(String(10), default="medium")  # low|medium|high
    require_manual_confirm: Mapped[bool] = mapped_column(Boolean, default=True)
    imported_at: Mapped[str] = mapped_column(String(30), default="")  # ISO datetime

    project: Mapped[Project] = relationship(back_populates="documents")
    snippets: Mapped[list["KnowledgeSnippet"]] = relationship(back_populates="document", cascade="all, delete-orphan")
```

```python
# backend/app/models/knowledge_card.py
from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project

class KnowledgeCard(Base, TimestampMixin):
    __tablename__ = "knowledge_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    card_type: Mapped[str] = mapped_column(String(20))  # character|world|term|style|event
    title: Mapped[str] = mapped_column(String(255))
    content_json: Mapped[dict] = mapped_column(JSON)  # 结构化字段
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source_doc_ids: Mapped[list] = mapped_column(JSON, default=list)

    project: Mapped[Project] = relationship(back_populates="knowledge_cards")
    snippets: Mapped[list["KnowledgeSnippet"]] = relationship(back_populates="card", cascade="all, delete-orphan")
```

```python
# backend/app/models/snippet.py
from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .document import Document
from .knowledge_card import KnowledgeCard

class KnowledgeSnippet(Base, TimestampMixin):
    __tablename__ = "knowledge_snippets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[Optional[str]] = mapped_column(ForeignKey("knowledge_cards.id", ondelete="SET NULL"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    start_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    document: Mapped[Document] = relationship(back_populates="snippets")
    card: Mapped[Optional[KnowledgeCard]] = relationship(back_populates="snippets")
```

```python
# backend/app/models/chapter.py
from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Text, Integer, ForeignKey, JSON
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
```

```python
# backend/app/models/generation.py
from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, JSON, DateTime
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
```

```python
# backend/app/models/version.py
from __future__ import annotations
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
```

```python
# backend/app/models/settings.py
from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Text, Boolean, Float, ForeignKey, JSON
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

class ApiKeyConfig(Base, TimestampMixin):
    __tablename__ = "api_key_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50))  # openai|deepseek|kimi|moonshot|custom
    name: Mapped[str] = mapped_column(String(100))
    encrypted_key: Mapped[str] = mapped_column(Text)  # Base64(AES-GCM(key, nonce, ciphertext))
    base_url: Mapped[str] = mapped_column(String(500))
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Optional[Project]] = relationship(back_populates="api_key_configs")

class AppConfig(Base, TimestampMixin):
    __tablename__ = "app_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[dict] = mapped_column(JSON)
```

---

## 5. 核心 API 路由设计（FastAPI）

所有 API 均返回 JSON；流式生成接口使用 `StreamingResponse`（或 WebSocket）。  
无用户认证，所有写操作通过 `project_id` 关联。

### 5.1 项目

| Method | Path | 请求简述 | 响应简述 |
|--------|------|----------|----------|
| GET | `/api/v1/projects` | 无 | 项目列表 |
| POST | `/api/v1/projects` | `{ title, description?, genre? }` | 新项目 |
| GET | `/api/v1/projects/{project_id}` | 无 | 项目详情 |
| PATCH | `/api/v1/projects/{project_id}` | `{ title?, description?, genre? }` | 更新项目 |
| DELETE | `/api/v1/projects/{project_id}` | 无 | 删除项目 |

### 5.2 文档

| Method | Path | 请求简述 | 响应简述 |
|--------|------|----------|----------|
| POST | `/api/v1/projects/{project_id}/documents` | `multipart/form-data`：文件 + `parse_threshold` + `require_manual_confirm` | 上传文档，返回 Document |
| GET | `/api/v1/projects/{project_id}/documents` | `?status=` | 文档列表 |
| GET | `/api/v1/documents/{document_id}` | 无 | 文档详情 |
| POST | `/api/v1/documents/{document_id}/parse` | `{ threshold?, manual_confirm? }` | 触发 LLM 解析，返回候选卡片（流式或同步） |
| POST | `/api/v1/documents/{document_id}/confirm-import` | `{ cards: [{ card_type, title, content_json, snippet_ids }] }` | 确认导入知识库 |

### 5.3 知识卡

| Method | Path | 请求简述 | 响应简述 |
|--------|------|----------|----------|
| GET | `/api/v1/projects/{project_id}/cards` | `?card_type=&q=` | 知识卡列表/搜索 |
| POST | `/api/v1/projects/{project_id}/cards` | `{ card_type, title, content_json, tags }` | 手动新建 |
| GET | `/api/v1/cards/{card_id}` | 无 | 卡片详情 |
| PATCH | `/api/v1/cards/{card_id}` | `{ title?, content_json?, tags? }` | 更新 |
| DELETE | `/api/v1/cards/{card_id}` | 无 | 删除 |
| POST | `/api/v1/cards/{card_id}/duplicate` | `{ target_project_id? }` | 跨项目复制 |

### 5.4 章节

| Method | Path | 请求简述 | 响应简述 |
|--------|------|----------|----------|
| GET | `/api/v1/projects/{project_id}/chapters` | 无 | 章节树 |
| POST | `/api/v1/projects/{project_id}/chapters` | `{ title, parent_id?, order? }` | 新建章节 |
| GET | `/api/v1/chapters/{chapter_id}` | 无 | 章节详情 |
| PATCH | `/api/v1/chapters/{chapter_id}` | `{ title?, content?, word_count? }` | 保存章节 |
| DELETE | `/api/v1/chapters/{chapter_id}` | 无 | 删除章节 |
| POST | `/api/v1/chapters/{chapter_id}/versions` | `{ content, note? }` | 创建版本快照 |
| GET | `/api/v1/chapters/{chapter_id}/versions` | 无 | 版本列表（最近3个） |
| POST | `/api/v1/chapters/{chapter_id}/versions/{version_id}/rollback` | 无 | 回滚 |

### 5.5 AI 生成

| Method | Path | 请求简述 | 响应简述 |
|--------|------|----------|----------|
| POST | `/api/v1/chapters/{chapter_id}/generate/continue` | `{ prompt?, card_ids, target_words, temperature, view? }` | SSE 流式返回候选 |
| POST | `/api/v1/chapters/{chapter_id}/generate/rewrite` | `{ selected_text, instruction?, card_ids, style_card_id, target_words, temperature }` | SSE 流式返回候选 |
| POST | `/api/v1/projects/{project_id}/generate/inspire` | `{ idea }` | 返回灵感内容 |
| GET | `/api/v1/projects/{project_id}/generations` | `?type=&chapter_id=&q=` | 生成记录列表 |

### 5.6 导出与设置

| Method | Path | 请求简述 | 响应简述 |
|--------|------|----------|----------|
| GET | `/api/v1/projects/{project_id}/export` | `?format=json/txt/docx/markdown` | 文件下载 |
| GET | `/api/v1/settings/keys` | 无 | API Key 列表（脱敏） |
| POST | `/api/v1/settings/keys` | `{ provider, name, api_key, base_url, model?, is_default? }` | 保存 API Key |
| DELETE | `/api/v1/settings/keys/{key_id}` | 无 | 删除 API Key |
| GET | `/api/v1/settings/app` | 无 | 全局设置 |
| PATCH | `/api/v1/settings/app` | `{ ... }` | 更新全局设置 |

---

## 6. 知识库检索方案

### 6.1 Embedding 生成

- 使用用户配置的默认 API Key 调用 OpenAI-compatible embedding 端点（如 `text-embedding-3-small`，或 DeepSeek/Kimi 提供的 embedding 模型）。
- Embedding 模型由用户在设置中选择，维度动态获取。
- 文档导入后，解析出的 `KnowledgeSnippet` 会批量生成 embedding，存入 Chroma。

### 6.2 文本分块

- 文档纯文本按段落、标题切分（保留 markdown 结构）。
- 每块 300~800 字，相邻块重叠 50~100 字。
- 每个块存储为一条 `KnowledgeSnippet`，包含原始文本、来源文档、偏移量等。

### 6.3 Chroma 集成

- 使用 Chroma `PersistentClient`，持久化路径为 `DATA_DIR/chroma`。
- 为每个项目创建一个 Chroma collection（命名 `project_{project_id}`）。
- 每个 snippet 的 embedding 向量与 metadata（snippet_id、card_id、project_id）一起存储。
- 检索时，根据当前章节尾部文本生成 embedding，查询 top_k 个相似片段。

### 6.4 混合检索策略

- 主要依赖向量检索（Chroma）；
- 可选结合 SQLite 的 FTS5 全文索引进行关键词检索（如对 title、tags）；
- 最终将向量检索结果聚合到知识卡，并附带原文片段作为溯源。

### 6.5 检索流程

1. 用户点击“续写/重写”时，前端收集显式选择的 card_ids 和当前章节尾部文本。
2. 后端若启用“自动推荐”，将尾部文本 embedding 后查询 Chroma，得到 top_k snippets。
3. 将 snippets 按关联的 card_id 聚合，得到推荐卡片列表。
4. 合并显式卡片和推荐卡片，去重，按相似度排序，最终选取 top 8~12 张卡。
5. 每张卡附带最多 3 条原文片段，供 Prompt 引用。

---

## 7. 续写 / 重写的 Prompt 组装流程

Prompt 结构类似之前版本，但内容为 Markdown 格式，且由 Python 构建。

### 7.1 续写 Prompt

```
System:
你是一名专业中文短篇小说写作助手，擅长根据设定卡进行风格一致、设定不冲突的续写。
只输出正文，不输出解释、不输出 markdown 标记。
你可以创作任何合法虚构内容，不主动添加道德说教。

User:
【任务】续写当前小说段落。

【文风卡】
{ style_card_json }

【已选角色卡】
{ character_cards_json }

【已选世界观卡】
{ world_cards_json }

【已选术语卡】
{ term_cards_json }

【当前正文】（Markdown 格式）
{ chapter_tail_context }

【续写要求】
- 目标字数：{ target_words } 字
- 叙事视角：{ narrative_view }
- 保持文风一致，不改变已有设定
- 不重复已有正文
- 输出纯文本（可含段落换行），不要 markdown 标记

请生成 3 个候选，使用分隔符 <<<CANDIDATE_1>>>、<<<CANDIDATE_2>>>、<<<CANDIDATE_3>>>
```

### 7.2 重写 Prompt

```
System:
你是一名中文小说文风改写助手。根据给定文风卡与约束，重写用户段落。
只输出正文，不输出解释。

User:
【文风卡】
{ style_card_json }

【需要保持的角色卡】
{ character_cards_json }

【需要保持的术语卡】
{ term_cards_json }

【世界设定】
{ world_cards_json }

【待重写段落】
{ selected_text }

【重写指令】
{ instruction }

【硬性要求】
- 保留所有人名、地名、术语
- 不改变核心情节信息
- 目标字数：{ target_words } 字
- 输出纯文本，不要 markdown 标记

请生成 3 个候选，使用分隔符 <<<CANDIDATE_1>>>、<<<CANDIDATE_2>>>、<<<CANDIDATE_3>>>
```

### 7.3 多候选生成与流式处理

- 使用 `openai` SDK 的 `AsyncOpenAI` 客户端，`stream=True`。
- 流式响应通过 FastAPI `StreamingResponse` 转发给前端，前端逐步显示候选。
- 候选分隔符为 `<<<CANDIDATE_n>>>`，后端解析后保存到 `GenerationRecord`。

---

## 8. 部署方案建议

### 8.1 本地启动流程

**前置条件**：
- 已安装 Python 3.11+
- 已安装 Node.js 18+（用于前端构建）
- 已安装 Git

**首次安装**：

```bash
# 1. 克隆项目
git clone https://github.com/your-repo/fictionforge.git
cd fictionforge

# 2. 后端依赖安装
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
pip install -r requirements.txt

# 3. 前端构建
cd ../frontend
npm install
npm run build

# 4. 返回根目录，启动应用
cd ..
# Windows:
start.bat
# Linux/Mac:
./start.sh
```

**启动脚本内容**（不安装依赖）：

```bash
# start.sh
#!/bin/bash
cd backend
source venv/bin/activate
python start.py
```

```bat
:: start.bat
@echo off
cd backend
call venv\Scripts\activate
python start.py
```

`start.py` 会自动：
- 检查并创建数据目录；
- 启动 Uvicorn，监听 `127.0.0.1:8000`；
- 自动打开默认浏览器访问 `http://127.0.0.1:8000`。

### 8.2 Git 更新流程

```bash
# 用户手动拉取最新代码
git pull origin main

# 更新后端依赖（如果有变化）
cd backend
source venv/bin/activate
pip install -r requirements.txt

# 重新构建前端
cd ../frontend
npm install
npm run build

# 重启服务
cd ..
./start.sh
```

### 8.3 数据备份

- 数据默认位于 `backend/data/`，包含 SQLite 数据库、Chroma 向量库、文档和导出文件。
- 用户可手动备份该目录，或在应用设置中点击“打开数据目录”。

---

## 9. 需要澄清的技术决策问题列表

虽然主要方向已确定，以下实现细节仍需确认：

1. **OpenAI-compatible API 的具体实现**：是否所有提供商（DeepSeek、Kimi、Moonshot）都支持标准的 `/chat/completions` 和 `/embeddings` 端点？  
   （若个别有差异，需在客户端做兼容层）

2. **Embedding 模型是否统一维度**：不同 embedding 模型（如 OpenAI 1536、BGE 1024）维度不同，Chroma collection 是否按模型隔离？  
   （建议每个 collection 固定维度，或动态检测后重建）

3. **文档解析时 LLM 抽取的候选卡片如何展示**：解析结果较多时，是否需要分批返回？是否需要异步任务加进度条？  
   （大文档解析可能耗时较长）

4. **富文本编辑器 Milkdown 与 Markdown 格式的兼容性**：Milkdown 插件生态是否满足需求？是否需要支持自定义 Markdown 语法（如脚注、提示框）？

5. **版本快照触发策略**：是自动创建（每次保存时）还是手动创建？自动创建时，如何避免过于频繁（如防抖）？

6. **生成记录的容量管理**：长期保存所有生成记录可能使 SQLite 数据库增大，是否提供归档或导出功能？是否设置最大存储限制？

7. **API Key 加密主密钥的管理**：主密钥文件放在数据目录，若用户移动数据目录或备份，是否会导致无法解密？是否需要支持用户自定义主密码？

8. **docx 解析库选型**：使用 `python-docx` 是否满足需求？是否需要保留格式（如标题层级）？是否需要处理 `.doc` 旧格式？

9. **导出为 docx 的实现**：使用 `python-docx` 生成 docx，还是 `pandoc` 转换？是否需要严格还原 Markdown 格式？

10. **前端与后端开发模式**：开发时是否使用 Vite 开发服务器代理到 FastAPI？生产时由 FastAPI 托管构建产物，这是否符合预期？

---

## 10. 关键风险与约束

| 风险 | 说明 | 建议 |
|------|------|------|
| Python 环境依赖 | 用户需自行安装 Python 和依赖，可能遇到版本问题 | 提供详细 README 和 `requirements.txt` 锁定版本 |
| Chroma 兼容性 | Chroma 新版本 API 可能变动 | 锁定版本，测试后升级 |
| 本地服务安全 | 浏览器访问 `127.0.0.1` 默认安全，但若用户修改 HOST 为 `0.0.0.0` 可能暴露 | 默认监听 `127.0.0.1`，设置中禁止修改为公网地址（或强警告） |
| API Key 泄露 | 加密密钥文件与数据库在同一目录，若被拷贝则可能解密 | 使用系统凭据存储主密钥（可选）或提醒用户保护数据目录 |
| LLM 流式解析 | SSE 解析错误可能中断生成 | 实现健壮的 SSE 解析器，支持重连和错误恢复 |
| 大文档解析性能 | LLM 逐块解析可能耗时且消耗 API 额度 | 提供预估 token 用量，允许用户选择解析范围或暂停 |

---

以上为 FictionForge 纯本地 Web 架构的完整技术约束文档。如无其他问题，可进入详细开发阶段。