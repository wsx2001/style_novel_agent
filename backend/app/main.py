"""FastAPI 入口：CORS、/api/v1 路由、前端静态托管。"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  确保所有模型注册到 Base.metadata
from .api.v1 import router as api_v1_router
from .api.v1.cards import router as cards_router
from .api.v1.chapters import router as chapters_router
from .api.v1.conversations import router as conversations_router
from .api.v1.documents import router as documents_router
from .api.v1.export import router as export_router
from .api.v1.generations import router as generations_router
from .api.v1.logs import router as logs_router
from .api.v1.model_providers import router as model_providers_router
from .api.v1.projects import router as projects_router
from .api.v1.prompt_templates import router as prompt_templates_router
from .api.v1.settings import router as settings_router
from .config import settings
from .logging_config import (
    RequestLoggingMiddleware,
    reset_request_id,
    set_request_id,
    setup_logging,
)

# 日志基础设施最先初始化：后续任何 logger 调用都会落盘（幂等）
setup_logging()

app = FastAPI(
    title="FictionForge",
    version="0.2.0",
    description="本地 AI 小说写作工具后端",
)

# 请求日志中间件先加（位于 CORS 内层）：只记录真实请求，不记录 CORS 预检
app.add_middleware(RequestLoggingMiddleware)

# CORS：允许本地开发前端（Vite dev server）与同源生产页面
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{settings.PORT}",
        f"http://127.0.0.1:{settings.PORT}",
        "http://localhost:5173",  # Vite 开发服务器
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 业务路由：/api/v1
app.include_router(api_v1_router)
app.include_router(projects_router)
app.include_router(documents_router)
app.include_router(cards_router)
app.include_router(chapters_router)
app.include_router(conversations_router)
app.include_router(prompt_templates_router)
app.include_router(export_router)
app.include_router(generations_router)
app.include_router(model_providers_router)
app.include_router(settings_router)
app.include_router(logs_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常兜底：记完整 traceback + 请求上下文，返回统一 500。"""
    # 关联 ID 由请求日志中间件挂到 scope state（contextvar 此时已被其 finally 复位）
    rid = getattr(request.state, "request_id", "") or ""
    token = set_request_id(rid) if rid else None
    try:
        logging.getLogger("app.http").error(
            "未捕获异常：%s %s（%s）",
            request.method,
            request.url.path,
            type(exc).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    finally:
        if token is not None:
            reset_request_id(token)
    # 此响应绕过请求日志中间件的 `_send` 包装（由 ServerErrorMiddleware 直发），
    # 需在此补上关联 ID，方便前端/调试端把 500 响应与日志对上
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"},
        headers={"X-Request-ID": rid},
    )

# 前端静态托管：FRONTEND_DIST 存在时挂载（放最后，避免吞掉 API 路由）
frontend_dist = settings.frontend_dist
if frontend_dist.exists() and frontend_dist.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(frontend_dist), html=True),
        name="frontend",
    )

