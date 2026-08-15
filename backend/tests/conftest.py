# backend/tests/conftest.py
"""共享测试夹具（backend/tests/）。

- 隔离 crypto 主密钥目录：settings.DATA_DIR 指向临时目录，避免污染真实
  DATA_DIR/secret.key，并保证每次测试使用独立密钥；
- 内存 SQLite + StaticPool：提供独立 AsyncSession（与真实数据库隔离）；
- httpx.MockTransport 工厂：mock /models 请求，不发起真实 HTTP。
"""
from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings


@pytest.fixture
def anyio_backend() -> str:
    """async 测试统一使用 asyncio 事件循环（anyio 插件）。"""
    return "asyncio"


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """将 crypto 主密钥目录指向临时目录（每次测试独立 secret.key）。"""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
async def session_factory(tmp_data_dir):
    """内存 SQLite 会话工厂：建好所有表后返回 async_sessionmaker。"""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    from app.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    yield factory
    await engine.dispose()


@pytest.fixture
def http_client_factory() -> Callable[[Callable], httpx.AsyncClient]:
    """按 handler 构造 httpx.AsyncClient(MockTransport)，用于 mock /models。"""

    def make(handler: Callable) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return make
