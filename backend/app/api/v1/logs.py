"""前端错误上报端点：把浏览器端未捕获异常写入后端 error.log。

前端通过 window error / unhandledrejection 监听捕获异常，POST 到
/api/v1/logs/client-error，服务端以 `[frontend]` 前缀记入 error.log，
便于后续排查前端页面问题（docs/TECHv1.2.md §4）。
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["logs"])

logger = logging.getLogger("app.client")

# 单次上报的消息/堆栈长度上限，避免恶意或循环错误刷爆日志
_MAX_MESSAGE = 500
_MAX_STACK = 2000

# 简单防刷：按 (source, url) 每 2 秒最多接受 1 条
_RATE_WINDOW = 2.0
_last_report: dict[str, float] = {}


class ClientErrorReport(BaseModel):
    """前端错误上报载荷。

    source: 错误来源（window / unhandledrejection / react / fetch）
    client_id: 浏览器会话级 ID，用于关联同一次前端会话的多条错误
    """

    source: str = "window"
    client_id: str = ""
    message: str = ""
    stack: str = ""
    url: str = ""
    timestamp: float = 0
    detail: str = ""


@router.post(
    "/logs/client-error",
    summary="前端错误上报",
    description="接收浏览器端未捕获异常并写入后端 error.log（带防刷）。",
)
async def report_client_error(report: ClientErrorReport) -> dict:
    now = time.monotonic()
    key = f"{report.source}:{report.url}"
    if now - _last_report.get(key, 0.0) < _RATE_WINDOW:
        return {"accepted": False, "reason": "rate_limited"}
    _last_report[key] = now

    parts = [
        f"[frontend] {report.source}",
        f"client={report.client_id or '-'}",
        f"url={report.url or '-'}",
    ]
    if report.message:
        parts.append(f"message={report.message[: _MAX_MESSAGE]}")
    if report.detail:
        parts.append(f"detail={report.detail[: _MAX_MESSAGE]}")
    if report.stack:
        parts.append(f"stack={report.stack[: _MAX_STACK]}")
    logger.error(" | ".join(parts))
    return {"accepted": True}
