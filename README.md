# FictionForge（小说工坊）

本地 AI 小说写作工具：以 AI 辅助续写、改写、多轮对话为核心，配合项目管理、文档解析、知识库检索与章节导出，全程本地运行、数据不出本机。

> 当前版本：V1（v0.2.0）。产品需求见 [docs/PRDv1.md](docs/PRDv1.md)，技术约束见 [docs/TECHv1.md](docs/TECHv1.md)。

## 功能一览

- **项目管理**：新建 / 编辑 / 删除项目；导出章节为 `txt` / `md` / `json` / `docx`。
- **章节编辑器**：富文本编辑，AI **续写** / **重写选中**（一次流式生成 3 个候选，可切换并回填）。
- **文档解析**：导入文档自动分章、提取知识卡。
- **知识库**：人物 / 世界观 / 术语 / 文风 / 事件五类知识卡，Chroma 向量检索，生成时自动引用。
- **对话工作台**：多轮创作对话，SSE 流式回复，消息历史持久化。
- **模型设置**：六档思维深度（无 / 自动 / 低 / 中等 / 高 / 极高）+ 随机性滑块 + 最大输出长度，可在全局、项目、会话三个层级设置，后续消息自动生效。
- **系统提示词模板**：全局 / 项目多模板管理，支持复制、占位符变量（`{{KNOWLEDGE_BASE}}`、`{{CURRENT_CHAPTER}}`、`{{STYLE_CARD}}`），内置系统「自动模板」不可删除。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy 2.0（async）· SQLite（aiosqlite）· Alembic · Chroma |
| 前端 | Node.js 20+ · Vite · React 19 · TypeScript · Tailwind CSS |
| 运行 | 纯本地 Web 应用，浏览器即界面（默认 `http://127.0.0.1:8000`） |

## 目录结构

```
style_noval_agent/
├── README.md            # 本文件
├── start.cmd            # 快速启动（双击或在终端运行）
├── stop.cmd             # 快速关闭（在另一个终端运行）
├── docs/                # 需求与架构文档（PRD / TECH）
├── backend/             # FastAPI 后端
│   ├── app/             #   应用代码（api / models / services）
│   ├── alembic/         #   数据库迁移
│   ├── scripts/         #   验证脚本（verify_*.py，可独立运行）
│   ├── start.py         #   启动入口（初始化数据库 + 启动服务 + 打开浏览器）
│   ├── requirements.txt
│   └── venv/            #   Python 虚拟环境（本地生成，不入库）
└── frontend/            # Vite + React 前端
    ├── src/
    ├── package.json
    ├── node_modules/    # 依赖（本地安装，不入库）
    └── dist/            # 构建产物（启动时自动构建，不入库）
```

## 环境要求

- Python 3.11+
- Node.js 20+（含 npm）
- Windows 11 / 10（脚本为 `.cmd` 批处理）

## 首次安装

```bash
# 1. 后端：创建虚拟环境并安装依赖
cd backend
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..

# 2. 前端：安装依赖（首次启动脚本也会自动构建，此步仅为安装依赖）
cd frontend
npm install
cd ..
```

> 数据库迁移由 `start.py` 启动时自动执行（幂等）；如需手动执行：`cd backend && venv\Scripts\python.exe -m alembic upgrade head`。

## 快速启动 / 关闭

在项目根目录 `style_noval_agent\` 下：

### 启动

```bash
start.cmd
```

或直接双击 `start.cmd`。脚本会：

1. 检查端口 8000 是否被占用（已占用则提示先关闭）；
2. 若 `frontend\dist` 缺失，自动执行 `npm run build` 构建前端；
3. 启动后端并自动打开浏览器 `http://127.0.0.1:8000`。

**此窗口需保持运行**（后端在前台运行）。常用参数：

| 命令 | 作用 |
|---|---|
| `start.cmd` | 使用已有构建产物启动；无构建产物时自动构建 |
| `start.cmd rebuild` | 强制重新构建前端后再启动 |
| `start.cmd skip-build` | 跳过构建检查，直接启动 |

### 关闭

在**另一个**终端中运行：

```bash
stop.cmd
```

脚本会查找占用端口 8000 的服务进程并强制结束。也可直接在被占用终端按 `Ctrl+C`。

> 端口默认 8000。若在 `backend\.env` 中修改了 `PORT`，请同步修改 `stop.cmd` 顶部 `set "PORT=..."`。

## 首次使用

1. 启动后浏览器打开应用；
2. 进入 **设置** 页，添加 API Key（自定义 provider，填写 `base_url` / `model` / `api_key`，AES-GCM 加密存储），供文档解析、向量化与 AI 生成使用；
3. 在 **设置** 页调整全局默认模型配置与系统提示词模板（全局默认深度「自动」，内置「自动模板」）；
4. 新建项目 → 章节 / 文档 / 知识库 / 对话 中开始创作。

## 验证

后端内置独立验证脚本（`backend/scripts/verify_*.py`），使用临时 SQLite + 模拟 LLM 客户端，不发起真实网络请求。在 `backend/` 下运行：

```bash
venv\Scripts\python.exe scripts\verify_settings_api.py          # 全局设置（23 项断言）
venv\Scripts\python.exe scripts\verify_prompt_templates_api.py  # 模板 CRUD/复制/保护（36）
venv\Scripts\python.exe scripts\verify_prompt_template.py       # 模板渲染/优先级（34）
venv\Scripts\python.exe scripts\verify_conversation.py          # 对话/流式/历史（49）
venv\Scripts\python.exe scripts\verify_conversation_sse_http.py # 对话 HTTP/SSE 层（13）
venv\Scripts\python.exe scripts\verify_project_defaults_api.py  # 项目默认配置（11）
venv\Scripts\python.exe scripts\verify_generation_config.py     # 续写/重写参数（41）
venv\Scripts\python.exe scripts\verify_depth_mapping.py         # 思维深度映射（39）
```

前端构建与检查：

```bash
cd frontend
npm run build   # tsc -b && vite build
npm run lint    # oxlint
```

## 配置项（可选）

后端读取环境变量或 `backend/.env`（参考 [docs/TECHv1.md](docs/TECHv1.md)）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HOST` | `127.0.0.1` | 监听地址 |
| `PORT` | `8000` | 监听端口 |
| `DATA_DIR` | `./data` | 数据目录（DB、Chroma、导出文件） |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/fictionforge.db` | 数据库连接串 |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | 向量库目录 |
| `FRONTEND_DIST` | `../frontend/dist` | 前端静态产物目录 |

## 相关文档

- [产品需求 V1](docs/PRDv1.md) · [技术约束 V1](docs/TECHv1.md)
- 历史 MVP 版本：[docs/PRD.md](docs/PRD.md) · [docs/TECH.md](docs/TECH.md)
