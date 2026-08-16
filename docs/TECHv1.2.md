# FictionForge 技术约束文档（Tech Spec / Architecture Doc）

> 版本：v0.8（日志系统）
> 关联 PRD：FictionForge v0.2 运行日志与异常定位
> 架构基础：纯本地 Web 应用（Python FastAPI + Vite/React + SQLite + Chroma）
> 运行方式：源码运行，浏览器作为界面，Git 拉取更新
> 状态：已实现并测试

---

## 0. 变更摘要

1. **集中式日志系统**：新建 `backend/app/logging_config.py`，统一配置根日志器——控制台 + 滚动文件 `app.log`（全量）+ `error.log`（仅 ERROR+），UTF-8 编码。
2. **请求关联 ID（X-Request-ID）**：每个 API 请求分配/透传关联 ID，贯穿该请求的全部日志，实现「按 req ID 一键 grep 完整链路」的快速异常定位。
3. **全局异常兜底**：未捕获异常记录完整 traceback + 请求上下文，返回统一 500。
4. **前端错误上报**：浏览器端未捕获异常（window / unhandledrejection / React 渲染错误）静默上报后端，写入 `error.log`（带 `[frontend]` 前缀）。
5. **零新依赖**：全部使用 Python 标准库 `logging` 与浏览器原生事件，未引入 `rich` 等新包。

---

## 1. 日志系统设计

### 1.1 文件布局

```
backend/data/logs/
├── app.log        # 全量运行日志（默认 INFO+，含 API 请求、业务、访问日志）
├── app.log.1..5   # 超过 5MB 滚动备份（LOG_MAX_BYTES=5MB, LOG_BACKUP_COUNT=5）
├── error.log      # 仅 ERROR 级：直接翻这里定位异常
└── error.log.1..5
```

- 日志目录默认 `./data/logs`（随数据目录 `backend/data/` 一起备份）。
- `app.log` 与 `error.log` 均按大小滚动（5MB × 5 份），长期运行不无限膨胀。

### 1.2 日志格式

```
2026-08-16 19:19:30.897 | INFO  | app.http:173 | req=req-bcbc7b308cf8 | >> GET /api/v1/health
2026-08-16 19:19:30.899 | INFO  | app.http:208 | req=req-bcbc7b308cf8 | << GET /api/v1/health -> 200 (1ms)
2026-08-16 19:19:30.936 | ERROR | app.client:67 | req=req-1530153a9a6b | [frontend] window | client=- | url=- | message=... | stack=...
```

| 字段 | 含义 |
|------|------|
| 时间 | `秒.毫秒`，本地时间 |
| 级别 | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| `app.http:173` | logger 名:代码行号，跳转定位 |
| `req=<id>` | 请求关联 ID；无请求上下文时为 `-` |
| 消息 | 业务内容；异常自动追加完整 traceback |

### 1.3 级别分离

- `error.log` 恒为 ERROR+，只收录：HTTP ≥500 请求结束、`logger.exception()`、`logger.error()`、前端上报的错误。
- 大量 WARNING（如 LLM 调用失败回退、Chroma 检索失败）只进 `app.log`，不影响 `error.log` 纯净度。

### 1.4 噪音控制

`httpx` / `httpcore` / `openai` / `urllib3` / `asyncio` 等第三方日志器被压到 WARNING，避免每次 HTTP 请求的 INFO 噪音刷满 `app.log`。

---

## 2. 请求关联 ID（X-Request-ID）

### 2.1 机制

`RequestLoggingMiddleware`（纯 ASGI，`logging_config.py`）：

1. 请求到达时，优先透传客户端 `X-Request-ID` 头，否则生成 `req-<12位hex>`。
2. 写入 `contextvars.ContextVar("request_id")`，同步到当前请求的全部协程。
3. 记录 `>> 方法 路径`（开始）与 `<< 方法 路径 -> 状态码 (耗时ms)`（结束）；≥500 记 ERROR、≥400 记 WARNING、其余 INFO。
4. 响应头回写 `X-Request-ID`；请求结束复位 contextvar。

### 2.2 为什么选纯 ASGI 而非 BaseHTTPMiddleware

纯 ASGI 中间件能包裹完整响应体生命周期。SSE 流式生成（续写/重写/对话）期间，事件在响应体迭代时输出，只有纯 ASGI 能保证这些日志同样携带 `req=` 关联 ID。

### 2.3 快速异常定位流程

```
# 1) 打开异常日志，找到出错请求的关联 ID（最后一条 req=xxx 且状态码 5xx）
2026-08-16 19:19:30.936 | ERROR | app.client:67 | req=req-1530153a9a6b | ...
2026-08-16 19:19:30.937 | ERROR | app.http:208 | req=req-1530153a9a6b | << GET /api/v1/... -> 500 (812ms)

# 2) 用该 ID 在 app.log 全文检索，看这条请求从进入到抛错的完整链路
grep "req-1530153a9a6b" backend/data/logs/app.log
```

---

## 3. 全局异常兜底

`app.main` 注册 `@app.exception_handler(Exception)`：

- 任何未被路由捕获的异常，记录完整 traceback + 方法/路径 + 异常类型到 `error.log`（消息含 `未捕获异常：...`）。
- 返回统一 `{ "detail": "服务器内部错误" }` 500。
- 说明：Starlette 的 `ServerErrorMiddleware` 在发送 500 后会重新抛出异常由 ASGI 服务器消化，客户端仍正常收到 500；测试需用 `TestClient(raise_server_exceptions=False)`。

---

## 4. 前端错误上报

### 4.1 捕获来源

| 来源 | 触发位置 | 上报 source |
|------|----------|------------|
| `window 'error'` | 未捕获 JS 异常 | `window` |
| `window 'unhandledrejection'` | 未处理的 Promise 拒绝 | `unhandledrejection` |
| React ErrorBoundary | 渲染错误（`componentDidCatch`） | `react` |

- 前端入口 `main.tsx` 安装全局监听；`ErrorBoundary` 包裹应用树。
- `frontend/src/api/logs.ts` 的 `reportClientError()`：**永不抛出**、2 秒节流、消息/堆栈截断、附浏览器会话级 `client_id`（同一次前端会话的多条错误可关联）。

### 4.2 端点

`POST /api/v1/logs/client-error`

```json
{ "source": "window", "client_id": "c-ab12cd34", "message": "...", "stack": "...", "url": "...", "timestamp": 0 }
```

- 服务端按 `(source, url)` 每 2 秒最多接受 1 条（防刷）。
- 接受的记录以 ERROR 级写入 `error.log`，前缀 `[frontend]`。

---

## 5. 配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LOG_DIR` | `./data/logs` | 日志目录 |
| `LOG_LEVEL` | `INFO` | 控制台与 `app.log` 最低级别；`error.log` 恒为 ERROR+ |
| `LOG_MAX_BYTES` | `5242880`（5MB） | 单文件滚动阈值 |
| `LOG_BACKUP_COUNT` | `5` | 滚动备份份数 |

---

## 6. 已登记的日志点位

改动前仓库已有 9 个文件使用 `logging.getLogger(__name__)`（文档解析 extractor、LLM client、model_provider、conversation、embedding、hybrid 检索及各 API 模块）。由于本系统配置的是根日志器，这些 `logger.warning/exception` 调用**无需任何改动**即自动落盘。后续新增代码请复用 `logging.getLogger(__name__)` 模式，异常处用 `logger.exception(...)` 以携带 traceback。

---

## 7. 测试

`backend/tests/test_logging.py`（11 项）覆盖：

- 文件落盘与幂等（重复调用不重复添加 handler）
- 级别分离（error.log 仅 ERROR+）
- 请求关联 ID 注入与无请求时默认 `-`
- 中间件生成/透传 X-Request-ID、500 状态落 error.log
- 未捕获异常完整 traceback 记录
- 前端错误上报端点写入与防刷

运行：
```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_logging.py -v
```

---

## 8. 剩余风险与开放项

1. **日志量**：SSE 长流（续写/重写）若逐事件 INFO 记录会增长较快，滚动策略兜底；后续可对高频路径降级为 DEBUG。
2. **前端上报覆盖**：仅覆盖未捕获异常；主动的业务错误（如请求失败提示）暂不上报，避免噪音。
3. **日志查看页**：当前定位依赖命令行 `grep error.log`；如需应用内日志查看页，可后续基于 `GET /api/v1/logs` 端点扩展。