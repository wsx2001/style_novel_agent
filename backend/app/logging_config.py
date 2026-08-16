"""集中式日志基础设施：文件落盘 + 请求关联 ID + 请求/响应日志。

设计目标（docs/TECHv1.2.md §1）：
1. 全量日志落盘 data/logs/app.log，异常单独落 error.log，方便事后排查；
2. 每个 API 请求分配 X-Request-ID（关联 ID），贯穿该请求的全部日志，
   实现「按 req ID 一键 grep 完整链路」的快速异常定位；
3. 未捕获异常记录完整 traceback + 请求上下文；
4. 纯标准库 logging，不引入新依赖。

用法：
    from .logging_config import setup_logging
    setup_logging()          # 在 app.main / start.py 入口处调用一次（幂等）
"""
from __future__ import annotations

import contextvars
import logging
import logging.handlers
import sys
import time
import uuid
from pathlib import Path

from .config import settings

# 请求关联 ID：中间件在每个请求开始时写入，格式化器读取后注入日志记录
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

# 本模块负责的处理器名：reset_logging / setup_logging(reset=True) 依据它们清理
_HANDLER_NAMES = ("fictionforge_console", "fictionforge_app_file", "fictionforge_error_file")

# 默认格式：时间 | 级别 | logger:行号 | req=<关联ID> | 消息（异常 traceback 由 Formatter 自动追加）
# datefmt 不含毫秒，毫秒由 %(msecs)03d 单独追加，避免重复（asctime 默认已带毫秒）
_DEFAULT_FMT = (
    "%(asctime)s.%(msecs)03d | %(levelname)-5s | %(name)s:%(lineno)d "
    "| req=%(request_id)s | %(message)s"
)
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 噪音较高的第三方日志器：压低到 WARNING，避免刷满 app.log
_QUIET_LOGGERS = ("httpx", "httpcore", "openai", "urllib3", "asyncio", "asyncio_ssl")


def get_request_id() -> str:
    """当前请求的关联 ID（无请求时返回 "-"）。"""
    return _request_id_var.get()


def set_request_id(rid: str) -> contextvars.Token:
    """设置当前请求关联 ID，返回 token 供复位。"""
    return _request_id_var.set(rid)


def reset_request_id(token: contextvars.Token) -> None:
    """复位请求关联 ID。"""
    _request_id_var.reset(token)


class RequestIdFormatter(logging.Formatter):
    """把当前请求关联 ID 注入每条日志记录的 formatter。"""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = get_request_id()
        return super().format(record)


def _remove_owned(root: logging.Logger) -> None:
    """移除并关闭本模块此前添加的处理器（幂等重建 / 测试隔离用）。"""
    for handler in list(root.handlers):
        if getattr(handler, "name", None) in _HANDLER_NAMES:
            root.removeHandler(handler)
            handler.close()


def setup_logging(
    log_dir: str | Path | None = None,
    level: str | None = None,
    *,
    reset: bool = False,
) -> Path:
    """配置根日志器：控制台 + app.log（全量）+ error.log（仅 ERROR+）。

    - 幂等：重复调用不重复添加处理器；传 reset=True 强制重建（测试用）。
    - 返回实际日志目录。
    """
    root = logging.getLogger()
    if reset:
        _remove_owned(root)
    elif any(getattr(h, "name", None) in _HANDLER_NAMES for h in root.handlers):
        # 已配置过且未要求重建：直接返回，避免重复 handler 导致日志翻倍
        return Path(log_dir) if log_dir else settings.log_dir

    target_dir = Path(log_dir) if log_dir else settings.log_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    log_level = (level or settings.LOG_LEVEL or "INFO").upper()
    max_bytes = settings.LOG_MAX_BYTES
    backup_count = settings.LOG_BACKUP_COUNT

    console = logging.StreamHandler(sys.stdout)
    console.set_name("fictionforge_console")
    console.setLevel(log_level)
    console.setFormatter(RequestIdFormatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT))

    app_handler = logging.handlers.RotatingFileHandler(
        target_dir / "app.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    app_handler.set_name("fictionforge_app_file")
    app_handler.setLevel(log_level)
    app_handler.setFormatter(RequestIdFormatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT))

    error_handler = logging.handlers.RotatingFileHandler(
        target_dir / "error.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.set_name("fictionforge_error_file")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(RequestIdFormatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT))

    # 根级别放开到 DEBUG，由各处理器自控级别，保证任何 logger 都能输出
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(app_handler)
    root.addHandler(error_handler)

    # 压低噪音第三方日志器（httpx 的每次请求 INFO、asyncio 的 DEBUG 等）
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return target_dir


def reset_logging() -> None:
    """移除本模块添加的所有处理器（测试隔离用）。"""
    _remove_owned(logging.getLogger())


class RequestLoggingMiddleware:
    """纯 ASGI 中间件：请求关联 ID + 请求开始/结束日志。

    选择纯 ASGI（而非 BaseHTTPMiddleware）的原因：能包裹完整响应体生命周期，
    保证 SSE 流式生成期间的日志同样携带请求关联 ID（见 docs/TECHv1.2.md §3）。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 复用客户端传来的 X-Request-ID，否则生成 req-<12位hex>
        rid = ""
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                rid = value.decode("latin-1").strip()
                break
        if not rid:
            rid = f"req-{uuid.uuid4().hex[:12]}"

        token = set_request_id(rid)
        # 关联 ID 挂到 scope state：即使 contextvar 在最终 finally 复位，
        # 全局异常处理器（外层 ServerError）仍能取到同一请求的 ID
        scope.setdefault("state", {})["request_id"] = rid

        method = scope.get("method", "?")
        path = scope.get("path", "?")
        logger = logging.getLogger("app.http")
        logger.info(">> %s %s", method, path)

        start = time.perf_counter()
        status: int = 500
        try:

            async def _send(message) -> None:
                nonlocal status
                if message["type"] == "http.response.start":
                    status = int(message.get("status", 500))
                    # 回写 X-Request-ID，方便前端/调试端关联
                    headers = [
                        (k, v)
                        for k, v in message.get("headers", [])
                        if k != b"x-request-id"
                    ]
                    headers.append((b"x-request-id", rid.encode("latin-1")))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, _send)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            # 错误状态用 warning/error 记录，便于在 error.log 直接定位
            if status >= 500:
                logger.error("<< %s %s -> %s (%dms)", method, path, status, duration_ms)
            elif status >= 400:
                logger.warning(
                    "<< %s %s -> %s (%dms)", method, path, status, duration_ms
                )
            else:
                logger.info("<< %s %s -> %s (%dms)", method, path, status, duration_ms)
            reset_request_id(token)
