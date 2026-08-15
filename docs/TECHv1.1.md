# FictionForge 技术约束文档（Tech Spec / Architecture Doc）

> 版本：v0.7（整合 PRD v1.1 增量）  
> 关联 PRD：FictionForge v0.2 + v1.1 模型提供商管理与项目级模型切换  
> 架构基础：纯本地 Web 应用（Python FastAPI + Vite/React + SQLite + Chroma）  
> 运行方式：源码运行，浏览器作为界面，Git 拉取更新  
> 状态：已根据用户确认整合所有决策

---

## 0. 变更摘要

1. **模型提供商管理**：新增 `ModelProvider` 实体，支持多提供商、每提供商多 API Key、自动获取/手动添加模型列表、启用/禁用模型、默认提供商设置。
2. **项目级模型切换**：项目可覆盖全局默认提供商和模型；对话工作台顶部支持快捷切换，切换后插入系统消息；生成记录记录实际使用的提供商和模型。
3. **数据模型扩展**：新增 `ModelProvider` 表；`Project`、`Conversation`、`GenerationRecord` 增加相关字段；移除旧的 `ApiKeyConfig` 表。
4. **API 路由扩展**：新增模型提供商管理端点，更新项目/对话/生成接口以支持模型选择。
5. **思维深度映射**：继续支持用户自定义映射，并根据实际模型类型自动适配参数。

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
│  │              │  │  - model-providers│  │  - 模型管理  │  │
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
- API Key 使用 AES-256-GCM 加密后存入 SQLite（在 `ModelProvider` 的 JSON 字段中），主密钥保存在本地配置文件中（权限限制），不通过环境变量传递。
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

在 v0.6 基础上新增模型提供商相关组件：

```
fictionforge/
├── backend/
│   ├── app/
│   │   ├── models/
│   │   │   ├── model_provider.py          # 新增
│   │   │   ├── project.py                 # 修改（增加默认提供商/模型字段）
│   │   │   ├── conversation.py            # 修改（增加当前提供商/模型字段）
│   │   │   ├── generation.py              # 修改（增加提供商/模型字段）
│   │   │   └── ...
│   │   ├── schemas/
│   │   │   ├── model_provider.py          # 新增
│   │   │   ├── project.py                 # 修改
│   │   │   ├── conversation.py            # 修改
│   │   │   ├── generation.py              # 修改
│   │   │   └── ...
│   │   ├── api/v1/
│   │   │   ├── model_providers.py         # 新增
│   │   │   ├── projects.py                # 修改（支持默认模型字段）
│   │   │   ├── conversations.py           # 修改（支持模型参数）
│   │   │   ├── generations.py             # 修改（记录模型）
│   │   │   └── ...
│   │   ├── services/
│   │   │   ├── llm/
│   │   │   │   ├── client.py              # 修改：支持多 Key 选择与模型切换
│   │   │   │   ├── prompts.py
│   │   │   │   └── stream.py
│   │   │   ├── model_provider.py          # 新增：提供商管理服务（获取模型列表、Key 检测等）
│   │   │   └── ...
│   │   └── utils/
│   │       └── ...
│   ├── alembic/
│   │   └── versions/
│   │       └── xxxx_add_model_provider.py  # 新增迁移
│   └── ...
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── settings/
│   │   │   │   ├── ModelProviderManagement.tsx   # 新增：模型提供商管理页面组件
│   │   │   │   ├── ModelProviderForm.tsx         # 新增：添加/编辑提供商弹窗
│   │   │   │   └── ...
│   │   │   ├── conversation/
│   │   │   │   ├── ModelSwitcher.tsx             # 新增：对话工作台模型切换下拉
│   │   │   │   └── ...
│   │   │   └── ...
│   │   ├── pages/
│   │   │   ├── Settings.tsx                      # 修改：增加模型提供商标签页
│   │   │   ├── ProjectSettings.tsx               # 修改：增加模型设置区域
│   │   │   ├── ConversationWorkspace.tsx         # 修改：顶部加入模型切换
│   │   │   └── ...
│   │   └── ...
│   └── ...
└── ...
```

---

## 4. 数据模型设计

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

### 4.2 模型提供商模型（新增）

```python
# backend/app/models/model_provider.py
from typing import Optional
from sqlalchemy import String, Text, Boolean, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin

class ModelProvider(Base, TimestampMixin):
    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))  # openai | anthropic | deepseek | kimi | opencode_go | custom | other
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 可选，适用于自定义兼容接口

    # 存储多个 API Key 的信息，结构见下文
    api_keys_json: Mapped[dict] = mapped_column(JSON, default=list)  # 实际为 list
    # 合并后的模型列表，结构见下文
    models_json: Mapped[dict] = mapped_column(JSON, default=list)    # 实际为 list

    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否全局默认提供商
```

**`api_keys_json` 结构示例**：

```json
[
  {
    "key_id": "key_1",
    "api_key_encrypted": "AES-GCM加密后的Base64字符串",
    "enabled": true,
    "priority": 1,
    "available_models": ["gpt-4o", "gpt-4o-mini"]
  },
  {
    "key_id": "key_2",
    "api_key_encrypted": "AES-GCM加密后的Base64字符串",
    "enabled": true,
    "priority": 2,
    "available_models": ["gpt-4o"]
  }
]
```

**`models_json` 结构示例**：

```json
[
  {"model_id": "gpt-4o", "enabled": true},
  {"model_id": "gpt-4o-mini", "enabled": true},
  {"model_id": "gpt-3.5-turbo", "enabled": false}
]
```

### 4.3 项目模型（修改）

在原有 `Project` 模型基础上增加：

```python
# backend/app/models/project.py (片段)
from sqlalchemy import String, Text, ForeignKey, JSON

class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cover_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # 新增字段
    default_provider_id: Mapped[Optional[str]] = mapped_column(ForeignKey("model_providers.id", ondelete="SET NULL"), nullable=True)
    default_model_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # 模型 ID 字符串

    # 原有字段
    default_model_config: Mapped[dict] = mapped_column(JSON, default=lambda: {"depth": "auto", "temperature": 0.7, "max_tokens": 2048})
    default_prompt_template_id: Mapped[Optional[str]] = mapped_column(ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True)

    # 关系
    default_provider: Mapped[Optional["ModelProvider"]] = relationship()
    # ... 其他关系
```

### 4.4 对话模型（修改）

在 `Conversation` 模型上增加当前使用的提供商和模型字段（用于记住用户在会话中最后选择的模型）：

```python
# backend/app/models/conversation.py (片段)
class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    model_config: Mapped[dict] = mapped_column(JSON, default=lambda: {"depth": "auto", "temperature": 0.7, "max_tokens": 2048})
    system_prompt_template_id: Mapped[Optional[str]] = mapped_column(ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True)
    system_prompt_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 新增字段
    current_provider_id: Mapped[Optional[str]] = mapped_column(ForeignKey("model_providers.id", ondelete="SET NULL"), nullable=True)
    current_model_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # 关系
    current_provider: Mapped[Optional["ModelProvider"]] = relationship()
    # ... 其他关系
```

### 4.5 生成记录模型（修改）

在 `GenerationRecord` 中增加实际使用的提供商和模型字段：

```python
# backend/app/models/generation.py (片段)
class GenerationRecord(Base, TimestampMixin):
    __tablename__ = "generation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    generation_type: Mapped[str] = mapped_column(String(20))  # continue|rewrite|inspire|outline
    status: Mapped[str] = mapped_column(String(20), default="pending")
    input_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    params_json: Mapped[dict] = mapped_column(JSON)
    output_candidates: Mapped[list] = mapped_column(JSON)
    selected_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 新增字段
    provider_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # 实际使用的提供商 ID
    model_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)    # 实际使用的模型 ID

    # 关系
    provider: Mapped[Optional["ModelProvider"]] = relationship()
    # ... 其他关系
```

### 4.6 全局设置（AppConfig 表）

全局设置存储在 `app_configs` 表中，新增以下键值：

- `global_default_provider_id`: 字符串，默认提供商 ID
- `global_default_model_id`: 字符串，默认模型 ID

原有的 `global_default_model_config` 和 `global_default_prompt_template_id` 继续保留。

**注意**：旧的 `ApiKeyConfig` 模型被移除，所有 API Key 管理统一到 `ModelProvider` 中。

---

## 5. 核心 API 路由设计

所有 API 均返回 JSON；流式生成接口使用 `StreamingResponse`（或 SSE）。无用户认证，所有写操作通过 `project_id` 关联。

### 5.1 模型提供商管理（新增）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/model-providers` | 列出所有提供商，包含名称、类型、Key数量、模型数量、默认标记等摘要信息 |
| POST | `/api/v1/model-providers` | 创建提供商，请求体包含 `name`, `type`, `base_url?`, `api_keys`（数组，每个含 key、enabled、priority） |
| GET | `/api/v1/model-providers/{provider_id}` | 获取提供商详情，包含 api_keys（脱敏）和 models 列表 |
| PATCH | `/api/v1/model-providers/{provider_id}` | 更新提供商信息（名称、base_url、api_keys、models 启用状态等） |
| DELETE | `/api/v1/model-providers/{provider_id}` | 删除提供商 |
| POST | `/api/v1/model-providers/{provider_id}/fetch-models` | 触发使用所有启用 Key 获取模型列表（合并去重），返回获取结果 |
| POST | `/api/v1/model-providers/{provider_id}/detect` | 检测所有 Key 连接状态（逐个检测），返回每个 Key 的状态 |
| POST | `/api/v1/model-providers/{provider_id}/keys/{key_id}/detect` | 检测单个 Key 连接状态 |

**创建提供商时请求体示例**：

```json
{
  "name": "我的Opencode",
  "type": "opencode_go",
  "base_url": "",
  "api_keys": [
    {"key": "sk-xxx", "enabled": true, "priority": 1},
    {"key": "sk-yyy", "enabled": true, "priority": 2}
  ]
}
```

创建成功后，系统自动尝试获取模型列表（异步或同步），并将结果返回。若获取失败，提供商仍创建成功，但模型列表为空，并提示“未获取到模型”。

**更新提供商时，可以修改 `api_keys`（新增/删除/修改优先级）和 `models` 的启用状态。**

### 5.2 项目设置中的模型配置（修改）

项目更新接口 `PATCH /api/v1/projects/{project_id}` 现在接受以下额外字段：

```json
{
  "default_provider_id": "provider_uuid",
  "default_model_id": "gpt-4o"
}
```

若 `default_provider_id` 为 `null`，表示继承全局默认；若 `default_model_id` 为 `null`，表示使用提供商的默认模型（若提供商有设置默认模型，否则提示用户选择）。

### 5.3 对话管理（修改）

- 创建对话 `POST /api/v1/projects/{project_id}/conversations` 可接收 `current_provider_id` 和 `current_model_id`（可选），若不传则继承项目或全局默认。
- 发送消息 `POST /api/v1/conversations/{conversation_id}/messages` 请求体中增加可选字段 `provider_id`、`model_id`，用于临时指定本次生成使用的模型（优先级最高）。若不传，则使用会话的 `current_provider_id/current_model_id`，再回退到项目默认，最后全局默认。
- 当请求中指定了新的 `provider_id/model_id` 或与当前会话不同，系统自动更新会话的 `current_provider_id/current_model_id`，并在对话中插入一条系统消息“模型已切换为：{提供商} · {模型}”（该消息也存储为 `Message` 记录）。

### 5.4 生成接口（修改）

续写、重写、灵感生成接口 `POST /api/v1/chapters/{chapter_id}/generate/continue`、`POST /api/v1/chapters/{chapter_id}/generate/rewrite`、`POST /api/v1/projects/{project_id}/generate/inspire` 请求体中增加可选字段：

```json
{
  "provider_id": "uuid",
  "model_id": "model-name",
  "model_config": {...}
}
```

若不传，则使用项目默认或全局默认。生成完成后，`GenerationRecord` 中记录实际的 `provider_id` 和 `model_id`。

### 5.5 全局设置接口（修改）

`GET /api/v1/settings/app` 返回全局设置，包含：
- `global_default_provider_id`
- `global_default_model_id`
- `global_default_model_config`
- `global_default_prompt_template_id`
- `depth_mapping_config`

`PATCH /api/v1/settings/app` 可更新上述字段。

### 5.6 其他路由（不变）

文档、知识卡、章节、提示词模板、导出等路由保持不变，但需注意删除或弃用旧的 `ApiKeyConfig` 相关路由（如果有）。

---

## 6. 知识库检索方案（不变）

与之前版本完全一致。检索时使用当前选定的 Embedding 模型（由生成时使用的提供商和模型决定，或单独配置）。细节略。

---

## 7. 续写 / 重写 / 对话 Prompt 组装流程

### 7.1 系统提示词渲染（不变）

模板来源优先级、占位符替换规则与 v0.6 一致。

### 7.2 模型选择与多 Key 策略

在每次生成前，系统按以下顺序确定实际使用的提供商和模型：

1. 请求中显式指定的 `provider_id` + `model_id`。
2. 对话会话的 `current_provider_id` + `current_model_id`。
3. 项目的 `default_provider_id` + `default_model_id`。
4. 全局默认的 `global_default_provider_id` + `global_default_model_id`。

确定提供商后，从该提供商的 `api_keys_json` 中选择一个可用的 Key：
- 优先选择优先级高、启用状态、且 `available_models` 包含目标模型的 Key。
- 如果所有 Key 的 `available_models` 都不包含目标模型，则选择第一个可用 Key 并直接尝试调用，若失败则尝试下一个。
- 若所有 Key 均失败，返回错误。

**注意**：`available_models` 可能过时，因此在调用失败并返回“模型不存在”错误时，系统会标记该 Key 的该模型不可用，并尝试其他 Key。同时，可以触发后台刷新该 Key 的模型列表。

### 7.3 思维深度映射

与 v0.6 相同：系统根据用户选择的思维深度等级和实际模型类型，在 `depth_mapping_config` 中查找适用的参数映射。若模型不支持某些参数，自动降级，并在 UI 提示。

### 7.4 实际 Prompt 构建

- 系统提示词从模板渲染获得。
- 用户消息内容与之前相同（续写/重写/对话）。
- 在对话模式中，当切换模型时，会插入一条系统消息（`role: "system"`）到消息列表中，内容为“模型已切换为：{提供商} · {模型}”。该消息也会作为历史消息发送给模型。

---

## 8. 部署方案

### 8.1 本地启动

- 用户手动安装 Python 3.11+、Node.js 18+、Git。
- 克隆仓库，后端创建虚拟环境并安装依赖，前端构建。
- 启动 `start.py`（Windows 下为 `start.bat`），自动打开浏览器。

### 8.2 Git 更新

- 用户执行 `git pull` 拉取最新代码。
- 若后端依赖变化，需重新 `pip install -r requirements.txt`。
- 若前端变化，需重新 `npm run build`。
- 重启服务。

### 8.3 数据备份

- 数据目录 `backend/data/` 包含 SQLite、Chroma、文档、导出文件，用户可手动备份或通过设置打开目录。

---

## 9. 剩余风险与开放项

1. **模型列表自动获取的稳定性**：不同提供商对 `/models` 端点的支持程度不同，Opencode Go 等自定义服务可能未实现。需要处理超时、返回格式差异。
2. **多 Key 并发与限流**：多 Key 选择策略简单顺序尝试，未实现并发或智能负载均衡。可能遇到限流问题。
3. **模型可用性缓存**：`available_models` 可能过期，需要定期刷新或在失败时更新。
4. **思维深度映射与模型能力匹配**：用户自定义映射可能与实际模型能力不匹配，导致 API 错误。需要前端提示。
5. **旧数据迁移**：移除 `ApiKeyConfig` 表后，如果用户有旧数据，需要提供迁移脚本将旧 Key 转换为新 `ModelProvider` 格式。
6. **安全性**：多个 API Key 加密存储，但解密密钥仍保存在本地。需确保数据目录权限合理。

---

## 10. 总结

本文档完整描述了基于 PRD v1.1 增量的技术设计，包括模型提供商管理、项目级模型切换、对话工作台快捷切换、生成记录追溯等。所有设计符合纯本地、隐私优先、用户自带 API Key 的原则，技术栈保持一致。

开发团队可依据此文档进行详细编码。如有未覆盖的细节，可在开发过程中进一步澄清。