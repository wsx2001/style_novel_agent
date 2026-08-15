"""FastAPI 入口：CORS、/api/v1 路由、前端静态托管。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  确保所有模型注册到 Base.metadata
from .api.v1 import router as api_v1_router
from .api.v1.cards import router as cards_router
from .api.v1.chapters import router as chapters_router
from .api.v1.conversations import router as conversations_router
from .api.v1.documents import router as documents_router
from .api.v1.export import router as export_router
from .api.v1.generations import router as generations_router
from .api.v1.model_providers import router as model_providers_router
from .api.v1.projects import router as projects_router
from .api.v1.prompt_templates import router as prompt_templates_router
from .api.v1.settings import router as settings_router
from .config import settings

app = FastAPI(
    title="FictionForge",
    version="0.2.0",
    description="本地 AI 小说写作工具后端",
)

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

# 前端静态托管：FRONTEND_DIST 存在时挂载（放最后，避免吞掉 API 路由）
frontend_dist = settings.frontend_dist
if frontend_dist.exists() and frontend_dist.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(frontend_dist), html=True),
        name="frontend",
    )
