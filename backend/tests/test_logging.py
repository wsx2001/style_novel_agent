# backend/tests/test_logging.py
"""集中式日志系统测试。

覆盖：文件落盘、级别分离、请求关联 ID、请求日志中间件、
前端错误上报端点、未捕获异常 traceback 记录。
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.v1.logs import router as logs_router
from app.logging_config import (
    RequestLoggingMiddleware,
    reset_logging,
    reset_request_id,
    set_request_id,
    setup_logging,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def log_dir(tmp_path) -> Path:
    """配置日志落到临时目录，测试结束后复位处理器，避免污染其他测试。"""
    d = tmp_path / "logs"
    setup_logging(log_dir=d, reset=True)
    yield d
    reset_logging()


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _make_app() -> FastAPI:
    """最小化应用：请求日志中间件 + 全局异常处理器 + 前端错误上报端点。"""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 与 app.main 保持一致：从 scope state 取关联 ID（此时 contextvar 已复位）
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
        return JSONResponse(
            status_code=500, content={"detail": "boom"}, headers={"X-Request-ID": rid}
        )

    @app.get("/ok")
    async def ok() -> dict:
        logging.getLogger("app.unit").info("inside ok handler")
        return {"ok": True}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    app.include_router(logs_router)
    return app


# ---- setup_logging 行为 ----

def test_setup_logging_creates_files(log_dir: Path) -> None:
    """setup_logging 应在目标目录生成 app.log 与 error.log。"""
    assert (log_dir / "app.log").exists()
    assert (log_dir / "error.log").exists()


def test_setup_logging_idempotent(log_dir: Path) -> None:
    """重复调用不重复添加处理器（避免日志翻倍）。"""
    root = logging.getLogger()
    before = sum(
        1
        for h in root.handlers
        if (getattr(h, "name", None) or "").startswith("fictionforge_")
    )
    setup_logging(log_dir=log_dir)
    after = sum(
        1
        for h in root.handlers
        if (getattr(h, "name", None) or "").startswith("fictionforge_")
    )
    assert after == before


def test_error_log_only_holds_error(log_dir: Path) -> None:
    """error.log 仅含 ERROR+；warning 只出现在 app.log。"""
    logger = logging.getLogger("app.unit")
    logger.warning("普通告警")
    logger.error("严重错误")

    app_log = _read(log_dir / "app.log")
    error_log = _read(log_dir / "error.log")

    assert "普通告警" in app_log
    assert "严重错误" in app_log
    assert "严重错误" in error_log
    assert "普通告警" not in error_log


def test_request_id_embedded_in_record(log_dir: Path) -> None:
    """日志记录应携带当前请求关联 ID。"""
    token = set_request_id("req-unittest-abc")
    try:
        logging.getLogger("app.unit").warning("带关联 ID 的消息")
    finally:
        reset_request_id(token)

    line = _read(log_dir / "app.log")
    assert "req=req-unittest-abc" in line
    assert "带关联 ID 的消息" in line


def test_no_request_id_defaults_to_dash(log_dir: Path) -> None:
    """无请求上下文时关联 ID 显示为 '-'，且不抛错。"""
    logging.getLogger("app.unit").info("无请求上下文的消息")
    assert "req=-" in _read(log_dir / "app.log")


# ---- 请求日志中间件 ----

async def test_middleware_assigns_and_logs_request_id(log_dir: Path) -> None:
    """中间件生成 X-Request-ID 并贯穿 >>/<< 日志。"""
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ok")

    assert resp.status_code == 200
    rid = resp.headers.get("x-request-id")
    assert rid and rid.startswith("req-")

    app_log = _read(log_dir / "app.log")
    assert ">> GET /ok" in app_log
    assert "<< GET /ok -> 200" in app_log
    # 请求 ID 同时出现在请求开始与结束日志行
    assert f"req={rid}" in app_log


async def test_middleware_honors_incoming_request_id(log_dir: Path) -> None:
    """客户端传入 X-Request-ID 时被复用。"""
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ok", headers={"X-Request-ID": "req-from-client"})

    assert resp.headers.get("x-request-id") == "req-from-client"
    assert "req=req-from-client" in _read(log_dir / "app.log")


def test_middleware_logs_error_status(log_dir: Path) -> None:
    """500 响应以 error 级别记录，落盘 error.log。

    注：Starlette 的 ServerErrorMiddleware 在发送 500 后会重新抛出异常，
    故用 TestClient(raise_server_exceptions=False) 获取响应。
    """
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")

    assert resp.status_code == 500
    error_log = _read(log_dir / "error.log")
    app_log = _read(log_dir / "app.log")
    # 请求开始是 INFO 级（app.log）；500 结束与异常是 ERROR 级（error.log）
    assert ">> GET /boom" in app_log
    assert "<< GET /boom -> 500" in error_log


def test_unhandled_exception_records_traceback(log_dir: Path) -> None:
    """未捕获异常应记录完整 traceback（且携带关联 ID）到 error.log，500 响应回写头。"""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")

    assert resp.status_code == 500
    rid = resp.headers.get("x-request-id")
    assert rid and rid.startswith("req-")

    error_log = _read(log_dir / "error.log")
    assert "未捕获异常：GET /boom（RuntimeError）" in error_log
    assert "kaboom" in error_log
    assert "Traceback (most recent call last)" in error_log
    # traceback 日志行应携带本次请求的关联 ID（req=<rid>）
    assert f"req={rid}" in error_log
    assert "req=-" not in error_log


# ---- 前端错误上报端点 ----

async def test_client_error_endpoint_writes_error_log(log_dir: Path) -> None:
    """POST client-error 应把前端错误写入 error.log。"""
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/logs/client-error",
            json={
                "source": "window",
                "client_id": "c-abcdef",
                "message": "TypeError: x is undefined",
                "stack": "at Foo (Foo.tsx:42)",
                "url": "http://test/workspace",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"accepted": True}

    error_log = _read(log_dir / "error.log")
    assert "[frontend] window" in error_log
    assert "client=c-abcdef" in error_log
    assert "TypeError: x is undefined" in error_log
    assert "Foo.tsx:42" in error_log


async def test_client_error_rate_limited(log_dir: Path) -> None:
    """同来源 2 秒内重复上报应被拒绝。"""
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    payload = {"source": "unhandledrejection", "message": "reject boom"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        first = await ac.post("/api/v1/logs/client-error", json=payload)
        second = await ac.post("/api/v1/logs/client-error", json=payload)

    assert first.json() == {"accepted": True}
    assert second.json()["accepted"] is False
    # 只有一条写入了 error.log
    assert _read(log_dir / "error.log").count("reject boom") == 1
