"""SQLAlchemy 异步引擎 / 会话工厂。

- SQLite + aiosqlite（异步驱动）
- 连接级 PRAGMA：WAL 模式 + 外键约束
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# V1 全局默认配置（AppConfig 种子记录，幂等写入）
DEFAULT_APP_CONFIGS: dict[str, dict] = {
    "global_default_model_config": {"depth": "auto"},
    "global_default_prompt_template_id": "",
}


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """SQLite 连接级配置：WAL 模式、外键约束、同步级别。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _ensure_db_parent() -> None:
    """确保 SQLite 数据库文件的父目录存在（默认落在 DATA_DIR 下）。"""
    url = make_url(settings.DATABASE_URL)
    if url.drivername.startswith("sqlite") and url.database not in (None, "", ":memory:"):
        Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)


async def init_db() -> None:
    """创建所有表（幂等）并写入全局默认配置。导入 models 使所有模型注册到 Base.metadata。"""
    from .models import Base  # noqa: F401

    _ensure_db_parent()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_default_app_configs()


async def seed_default_app_configs() -> None:
    """幂等写入 AppConfig 全局默认记录（key 已存在则跳过）。

    目前两条 V1 默认记录：
    - global_default_model_config     全局默认模型配置（思维深度等）
    - global_default_prompt_template_id 全局默认提示词模板 ID（空串表示未设置）
    """
    from sqlalchemy import select

    from .models import AppConfig

    async with async_session_maker() as session:
        for key, value in DEFAULT_APP_CONFIGS.items():
            exists = await session.scalar(select(AppConfig.id).where(AppConfig.key == key))
            if exists is None:
                session.add(AppConfig(key=key, value=value))
        await session.commit()


async def get_db():
    """FastAPI 依赖：提供异步会话。"""
    async with async_session_maker() as session:
        yield session
