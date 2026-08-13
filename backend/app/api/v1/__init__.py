"""API v1 路由占位。

后续按模块拆分到 projects.py / documents.py / cards.py / chapters.py /
generations.py / export.py / settings.py（参考 docs/TECH.md 第 2 节）。
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.get("/health", summary="健康检查")
async def health() -> dict[str, str]:
    return {"status": "ok"}
