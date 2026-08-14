# FictionForge 技术约束文档（Tech Spec / Architecture Doc）

> 版本：v0.6（基于 MVP 新增功能）  
> 关联 PRD：FictionForge v0.2  
> 架构基础：纯本地 Web 应用（Python FastAPI + Vite/React + SQLite + Chroma）  
> 运行方式：源码运行，浏览器作为界面，Git 拉取更新  
> 状态：已根据用户确认整合所有决策

---

## 0. 变更摘要

1. **模型思维深度**：新增六档思维深度（无、自动、低、中等、高、极高），系统内部映射为 API 参数；**允许用户在高级设置中自定义不同模型的参数映射**（默认提供系统预设）。
2. **系统提示词自定义**：多模板管理，支持全局/项目级模板，会话切换与临时覆盖，占位符变量替换。
3. **对话工作台**：新增多轮对话创作模块，与现有“续写/重写”并存；对话消息独立存储，不写入生成记录。
4. **数据模型扩展**：新增 `PromptTemplate`、`Conversation`、`Message` 表；`Project` 增加默认模型配置与提示词模板字段。
5. **API 路由扩展**：新增对话管理、模板管理端点；续写/重写接口支持传入模型配置与提示词模板。

---

## 1. 架构总览

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
│  │ (React 构建) │  │  - projects   │  │  - LLM 客户端  │  │
│  │              │  │  - documents  │  │  - 文档解析    │  │
│  │              │  │  - cards      │  │  - 知识检索    │  │
│  │              │  │  - chapters   │  │  - 对话服务    │  │
│  │              │  │  - conversations│  │  - 思维深度映射│  │
│  │              │  │  - prompt_templates│  │  - 导出    │  │
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

## 2. 技术选型建议

### 2.1 后端（Python）

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

### 2.2 前端

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

### 2.3 开发与部署工具

| 类别 | 选型 | 理由 |
|------|------|------|
| 前端构建 | Vite | 快速构建，HMR |
| 后端依赖管理 | `pip` + `requirements.txt`（或 `pyproject.toml` + Poetry） | 简单，用户手动安装 |
| Git 更新 | 用户手动 `git pull` | 按用户要求 |
| 启动脚本 | `start.sh` / `start.bat`（仅启动服务，不安装依赖） | 提供方便启动 |
| 代码质量 | Ruff（lint）+ Black（format） | 保持代码整洁 |

---

## 3. 项目目录结构

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
│   │   │   ├── conversation.py         # 新增
│   │   │   ├── prompt_template.py      # 新增
│   │   │   ├── version.py
│   │   │   └── settings.py
│   │   ├── schemas/                    # Pydantic DTO
│   │   │   ├── __init__.py
│   │   │   ├── project.py
│   │   │   ├── document.py
│   │   │   ├── card.py
│   │   │   ├── chapter.py
│   │   │   ├── generation.py
│   │   │   ├── conversation.py         # 新增
│   │   │   ├── prompt_template.py      # 新增
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
│   │   │       ├── conversations.py    # 新增
│   │   │       ├── prompt_templates.py # 新增
│   │   │       ├── export.py
│   │   │       └── settings.py
│   │   ├── services/                   # 业务逻辑层
│   │   │   ├── llm/
│   │   │   │   ├── client.py           # 支持思维深度映射
│   │   │   │   ├── prompts.py          # 系统提示词渲染与占位符替换
│   │   │   │   └── stream.py
│   │   │   ├── embedding/
│   │   │   │   └── embedder.py
│   │   │   ├── parsing/
│   │   │   │   ├── extractor.py
│   │   │   │   └── chunker.py
│   │   │   ├── retrieval/
│   │   │   │   └── hybrid.py
│   │   │   ├── conversation.py         # 新增对话服务
│   │   │   ├── prompt_template.py      # 新增模板服务
│   │   │   ├── depth_mapping.py        # 新增思维深度映射逻辑
│   │   │   ├── export/
│   │   │   │   └── exporter.py
│   │   │   └── crypto/
│   │   │       └── api_key.py
│   │   └── utils/
│   │       ├── file_parser.py
│   │       └── logger.py
│   ├── alembic/                        # 数据库迁移
│   │   ├── env.py
│   │   └── versions/
│   ├── data/                           # 默认数据目录（运行时生成）
│   │   ├── fictionforge.db
│   │   ├── chroma/
│   │   ├── documents/
│   │   └── exports/
│   ├── requirements.txt
│   └── start.py
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/                        # Axios 实例与 API 函数
│   │   ├── components/
│   │   │   ├── editor/
│   │   │   ├── cards/
│   │   │   ├── documents/
│   │   │   ├── conversation/           # 新增对话组件
│   │   │   ├── settings/ModelPromptSettings.tsx  # 新增模型/提示词设置
│   │   │   └── layout/
│   │   ├── pages/
│   │   │   ├── ProjectList.tsx
│   │   │   ├── ProjectWorkspace.tsx
│   │   │   ├── KnowledgeBase.tsx
│   │   │   ├── DocumentParse.tsx
│   │   │   ├── ChapterEditor.tsx
│   │   │   ├── ConversationWorkspace.tsx  # 新增
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
├── start.bat
└── start.sh
```

---

## 4. 数据模型设计

使用 SQLAlchemy 2.0 定义模型。已确认的设计决策：

- 对话消息单独存储，不写入 `GenerationRecord`。
- 一次性续写/重写仍使用 `GenerationRecord`。
- 旧版生成记录兼容不考虑。

### 4.1 基础模型（不变）

```python
# backend/app/models/base.py
from datetime import datetime
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

### 4.2 项目模型（扩展）

```python
# backend/app/models/project.py
from typing import Optional
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

    # 新增：默认模型配置（深度、温度、max_tokens）
    default_model_config: Mapped[dict] = mapped_column(JSON, default=lambda: {"depth": "auto", "temperature": 0.7, "max_tokens": 2048})
    # 新增：默认提示词模板 ID（可空）
    default_prompt_template_id: Mapped[Optional[str]] = mapped_column(ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True)

    documents: Mapped[list["Document"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    knowledge_cards: Mapped[list["KnowledgeCard"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    generation_records: Mapped[list["GenerationRecord"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    api_key_configs: Mapped[list["ApiKeyConfig"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    settings: Mapped[Optional["ProjectSettings"]] = relationship(back_populates="project", cascade="all, delete-orphan", uselist=False)
    prompt_templates: Mapped[list["PromptTemplate"]] = relationship(back_populates="project", cascade="all, delete-orphan")
```

### 4.3 提示词模板模型（新增）

```python
# backend/app/models/prompt_template.py
from typing import Optional
from sqlalchemy import String, Text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project

class PromptTemplate(Base, TimestampMixin):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)  # 可含 {{VARIABLE}} 占位符
    scope: Mapped[str] = mapped_column(String(20))  # "global" 或 "project"
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # 系统内置模板不可删除

    project: Mapped[Optional[Project]] = relationship(back_populates="prompt_templates")
```

### 4.4 对话模型（新增）

```python
# backend/app/models/conversation.py
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from .project import Project
from .chapter import Chapter

class Conversation(Base, TimestampMixin):
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
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")

class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text)
    metadata: Mapped[dict] = mapped_column(JSON, default=dict)  # 可存 token 用量、模型等

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
```

### 4.5 其余模型（不变）

`Document`, `KnowledgeCard`, `KnowledgeSnippet`, `Chapter`, `GenerationRecord`, `VersionSnapshot`, `ProjectSettings`, `ApiKeyConfig`, `AppConfig` 均与 MVP 一致，此处不再重复列出。

**注意**：`AppConfig` 中全局默认模型配置和默认提示词模板 ID 将存储在 `app_configs` 表中，键分别为 `global_default_model_config` 和 `global_default_prompt_template_id`。

---

## 5. 核心 API 路由设计

所有 API 均返回 JSON；流式生成接口使用 `StreamingResponse`（或 SSE）。无用户认证，所有写操作通过 `project_id` 关联。

### 5.1 项目（不变）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/projects` | 项目列表 |
| POST | `/api/v1/projects` | 新建项目 |
| GET | `/api/v1/projects/{project_id}` | 项目详情 |
| PATCH | `/api/v1/projects/{project_id}` | 更新项目 |
| DELETE | `/api/v1/projects/{project_id}` | 删除项目 |

### 5.2 文档（不变）

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/projects/{project_id}/documents` | 上传文档 |
| GET | `/api/v1/projects/{project_id}/documents` | 文档列表 |
| GET | `/api/v1/documents/{document_id}` | 文档详情 |
| POST | `/api/v1/documents/{document_id}/parse` | 触发 LLM 解析 |
| POST | `/api/v1/documents/{document_id}/confirm-import` | 确认导入知识卡 |

### 5.3 知识卡（不变）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/projects/{project_id}/cards` | 知识卡列表 |
| POST | `/api/v1/projects/{project_id}/cards` | 手动新建知识卡 |
| GET | `/api/v1/cards/{card_id}` | 卡片详情 |
| PATCH | `/api/v1/cards/{card_id}` | 更新卡片 |
| DELETE | `/api/v1/cards/{card_id}` | 删除卡片 |
| POST | `/api/v1/cards/{card_id}/duplicate` | 跨项目复制 |

### 5.4 章节（不变）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/projects/{project_id}/chapters` | 章节树 |
| POST | `/api/v1/projects/{project_id}/chapters` | 新建章节 |
| GET | `/api/v1/chapters/{chapter_id}` | 章节详情 |
| PATCH | `/api/v1/chapters/{chapter_id}` | 保存章节 |
| DELETE | `/api/v1/chapters/{chapter_id}` | 删除章节 |
| POST | `/api/v1/chapters/{chapter_id}/versions` | 创建版本快照 |
| GET | `/api/v1/chapters/{chapter_id}/versions` | 版本列表 |
| POST | `/api/v1/chapters/{chapter_id}/versions/{version_id}/rollback` | 回滚 |

### 5.5 AI 生成（更新）

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/chapters/{chapter_id}/generate/continue` | 续写（支持传入 model_config 和 system_prompt_template_id） |
| POST | `/api/v1/chapters/{chapter_id}/generate/rewrite` | 重写（同上） |
| POST | `/api/v1/projects/{project_id}/generate/inspire` | 灵感生成（同样支持新参数） |
| GET | `/api/v1/projects/{project_id}/generations` | 生成记录列表 |

请求体示例（续写）：

```json
{
  "card_ids": ["uuid1", "uuid2"],
  "target_words": 500,
  "view": "third_person",
  "model_config": {
    "depth": "medium",
    "temperature": 0.7,
    "max_tokens": 2048
  },
  "system_prompt_template_id": "template_id"
}
```

### 5.6 对话管理（新增）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/projects/{project_id}/conversations` | 列出项目下所有对话 |
| POST | `/api/v1/projects/{project_id}/conversations` | 创建新对话，请求可含 `title`, `chapter_id?`, `model_config?`, `system_prompt_template_id?` |
| GET | `/api/v1/conversations/{conversation_id}` | 获取对话详情（含消息列表） |
| PATCH | `/api/v1/conversations/{conversation_id}` | 更新对话标题、模型配置、提示词模板等 |
| DELETE | `/api/v1/conversations/{conversation_id}` | 删除对话 |
| POST | `/api/v1/conversations/{conversation_id}/messages` | 发送用户消息，触发 AI 回复（流式，只生成一个回复） |
| GET | `/api/v1/conversations/{conversation_id}/messages` | 获取消息历史 |

### 5.7 提示词模板管理（新增）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/prompt-templates?scope=global/project&project_id=` | 列出可用模板（同一列表，标签区分全局/项目） |
| POST | `/api/v1/prompt-templates` | 创建模板，请求包含 `name`, `content`, `scope`, `project_id?` |
| GET | `/api/v1/prompt-templates/{template_id}` | 获取模板详情 |
| PATCH | `/api/v1/prompt-templates/{template_id}` | 更新模板 |
| DELETE | `/api/v1/prompt-templates/{template_id}` | 删除模板（系统默认模板不可删） |
| POST | `/api/v1/prompt-templates/{template_id}/duplicate` | 复制模板 |

### 5.8 导出与设置（不变/补充）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/projects/{project_id}/export` | 导出项目 |
| GET | `/api/v1/settings/keys` | API Key 列表（脱敏） |
| POST | `/api/v1/settings/keys` | 保存 API Key |
| DELETE | `/api/v1/settings/keys/{key_id}` | 删除 API Key |
| GET | `/api/v1/settings/app` | 全局设置（包含 global_default_model_config, global_default_prompt_template_id） |
| PATCH | `/api/v1/settings/app` | 更新全局设置 |
| GET | `/api/v1/settings/depth-mapping` | 获取思维深度映射配置（全局） |
| PATCH | `/api/v1/settings/depth-mapping` | 更新思维深度映射配置（允许用户自定义） |

---

## 6. 知识库检索方案（继承 MVP）

与 MVP 完全一致，不涉及新功能，此处不再重复。仅强调：

- 使用 Chroma 嵌入式作为向量库，持久化于 `backend/data/chroma`。
- 文本分块、Embedding、混合检索策略不变。
- 对话模式中若涉及知识库引用，使用相同的检索服务。

---

## 7. 续写 / 重写 / 对话 Prompt 组装流程

### 7.1 系统提示词渲染

- 系统提示词模板来源优先级：会话 `system_prompt_override` > 会话 `system_prompt_template_id` > 项目默认模板 > 全局默认模板。
- 占位符替换：支持 `{{KNOWLEDGE_BASE}}`、`{{CURRENT_CHAPTER}}`、`{{STYLE_CARD}}`、`{{USER_INPUT}}`、`{{PROJECT_INFO}}`、`{{CONVERSATION_HISTORY}}`。
- 模板渲染在 `services/llm/prompts.py` 中完成。

```python
def render_system_prompt(template_content: str, context: dict) -> str:
    for var, value in context.items():
        placeholder = "{{" + var + "}}"
        if placeholder in template_content:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, indent=2)
            template_content = template_content.replace(placeholder, str(value))
    return template_content
```

### 7.2 续写 / 重写

续写/重写仍然使用单次请求返回 3 个候选的方式（保留原有行为）。系统提示词从上述模板渲染获得，用户消息组装方式与 MVP 相同。

- 续写用户消息内容包含：文风卡、知识卡、当前正文、续写要求、候选分隔符指令。
- 重写用户消息内容包含：文风卡、角色/术语/世界卡、待重写段落、重写指令、候选分隔符指令。

### 7.3 对话模式

对话模式中，每次用户发送消息，系统将：

1. 渲染系统提示词（从模板或覆盖）。
2. 组装消息数组：`[system, ...history_messages, user_new_message]`。
3. 调用 LLM，流式返回一个 assistant 回复（不生成多候选）。
4. 将用户消息和 AI 回复存入 `Message` 表。

```python
def build_dialogue_messages(conversation, messages, user_input):
    system_prompt = get_effective_system_prompt(conversation)
    chat_messages = [{"role": "system", "content": system_prompt}]
    # 取最近 20 条消息
    for msg in messages[-20:]:
        chat_messages.append({"role": msg.role, "content": msg.content})
    chat_messages.append({"role": "user", "content": user_input})
    return chat_messages
```

---

## 8. 思维深度映射机制

### 8.1 用户可自定义映射

- 默认情况下，系统内置一套思维深度映射规则（针对不同模型类型定义通用参数调整）。
- 用户可通过「设置 → 模型/提示词 → 高级」编辑映射配置。映射配置存储于全局 `AppConfig` 中，键为 `depth_mapping_config`，结构如下：

```json
{
  "default": {
    "low": {"temperature": 0.9, "max_tokens": 1024},
    "medium": {"temperature": 0.7, "max_tokens": 2048},
    "high": {"temperature": 0.5, "max_tokens": 4096},
    "extreme": {"temperature": 0.3, "max_tokens": 8192}
  },
  "model_overrides": {
    "o1-mini": {
      "low": {"reasoning_effort": "low"},
      "medium": {"reasoning_effort": "medium"},
      "high": {"reasoning_effort": "high"},
      "extreme": {"reasoning_effort": "high", "max_tokens": 8192}
    },
    "deepseek-reasoner": {
      "low": {"thinking": {"type": "disabled"}},
      "medium": {"thinking": {"type": "enabled"}},
      "high": {"thinking": {"type": "enabled"}, "max_tokens": 4096}
    }
  }
}
```

- 当用户选择了某个模型和思维深度等级时，系统按以下顺序查找映射：
  1. `model_overrides` 中完全匹配的模型名称；
  2. `model_overrides` 中匹配模型前缀（如 `o1` 前缀）；
  3. `default` 映射。

- “自动”等级：系统根据上下文（上下文长度、知识卡数量）从 `low`、`medium`、`high` 中选择一个实际等级，再应用对应映射。规则为 MVP 简单规则：
  - 上下文长度 > 8000 或知识卡 > 8 → `high`
  - 上下文长度 > 4000 或知识卡 > 4 → `medium`
  - 否则 → `low`

- “无”等级：不设置任何额外参数，完全使用模型默认行为。

### 8.2 参数合并优先级

- 如果用户同时显式设置了 `temperature`、`max_tokens`（通过前端滑块或输入框），这些值将优先于映射规则中的默认值。
- 具体合并策略：映射规则仅作为缺省值，若请求中提供了对应参数，则覆盖映射值。

### 8.3 实现位置

- `services/llm/client.py` 中的 `apply_depth_config()` 函数负责加载映射配置，并生成最终的 API 参数字典。
- 映射配置可通过 API 读取和更新（`GET/PATCH /api/v1/settings/depth-mapping`）。

---

## 9. 部署方案

### 9.1 本地启动

- 用户手动安装 Python 3.11+、Node.js 18+、Git。
- 克隆仓库，后端创建虚拟环境并安装依赖，前端构建。
- 启动 `start.py`（Windows 下为 `start.bat`），自动打开浏览器。

### 9.2 Git 更新

- 用户执行 `git pull` 拉取最新代码。
- 若后端依赖变化，需重新 `pip install -r requirements.txt`。
- 若前端变化，需重新 `npm run build`。
- 重启服务。

### 9.3 数据备份

- 数据目录 `backend/data/` 包含 SQLite、Chroma、文档、导出文件，用户可手动备份或通过设置打开目录。

---

## 10. 剩余风险与开放项

尽管核心决策已确认，以下风险仍需在开发中关注：

1. **思维深度映射的用户自定义界面**：用户自定义映射需要提供友好的编辑界面，否则功能可能不被使用。前端需要实现一个映射编辑器，允许用户为不同模型或模型前缀配置各等级参数。
2. **不同模型对参数的支持差异**：即使用户自定义映射，仍需处理模型不支持参数的情况（如普通 chat 模型不支持 `reasoning_effort`）。后端需在调用前验证并过滤不支持的参数。
3. **Chroma 升级兼容性**：锁定 Chroma 版本，避免升级引入破坏性变化。
4. **对话上下文长度控制**：对话历史过多可能导致 token 超限。需要实现截断策略（如保留最近 N 条消息或摘要）。
5. **安全**：本地服务默认监听 `127.0.0.1`，但需在设置中禁止修改为 `0.0.0.0`，或提供强警告。

---

## 11. 总结

本文档完整描述了基于 MVP 的新增功能技术设计，包括模型思维深度（支持用户自定义映射）、系统提示词自定义、对话工作台。所有设计均符合纯本地、隐私优先、用户自带 API Key 的原则，且技术栈保持一致。

开发团队可依据此文档进行详细编码。如有未覆盖的细节，可在开发过程中进一步澄清。