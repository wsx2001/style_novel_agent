"""Alembic 迁移环境：对接 FictionForge 异步 SQLite 数据库。

- 目标元数据：app.models 的 Base.metadata（导入 models 即注册所有表）
- 数据库 URL：优先读取环境变量 ALEMBIC_DATABASE_URL（用于生成 baseline 等临时场景），
  否则使用应用配置 app.config.settings.DATABASE_URL
- 异步引擎（aiosqlite）；SQLite 使用 batch 模式（render_as_batch）以便后续 ALTER
- 迁移连接：开启 WAL；迁移期间关闭外键约束（batch 重建表时避免级联删除数据）
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import event, pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据：
# 1) ALEMBIC_REFLECT_SRC 被设置时，反射该 SQLite 库作为目标（用于从既有库生成 baseline 迁移）；
# 2) 默认使用 app.models 的 Base.metadata（所有模型已注册）。
_reflect_src = os.environ.get("ALEMBIC_REFLECT_SRC")
if _reflect_src:
    from sqlalchemy import MetaData, create_engine

    _src_engine = create_engine(_reflect_src)
    target_metadata = MetaData()
    target_metadata.reflect(bind=_src_engine)
    _src_engine.dispose()
else:
    from app.models import Base  # noqa: F401  确保所有模型注册到 Base.metadata

    target_metadata = Base.metadata


def _resolve_database_url(url: str) -> str:
    """将相对 SQLite 路径解析为相对 backend 目录（与 start.py 的 chdir 约定一致），
    使 alembic 可从任意 cwd 运行。"""
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite") and parsed.database and not Path(parsed.database).is_absolute():
        backend_dir = Path(__file__).resolve().parent.parent
        resolved = str((backend_dir / parsed.database).resolve()).replace("\\", "/")
        return url.replace(parsed.database, resolved, 1)
    return url


# 覆盖 ini 中的 URL：优先环境变量，其次应用配置（相对路径解析到 backend 目录）
config.set_main_option(
    "sqlalchemy.url",
    _resolve_database_url(os.environ.get("ALEMBIC_DATABASE_URL", settings.DATABASE_URL)),
)


def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """迁移连接级 PRAGMA：WAL 模式 + 关闭外键约束。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=OFF")
    finally:
        cursor.close()


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：异步引擎 + 逐连接 PRAGMA。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    event.listen(connectable.sync_engine, "connect", _set_sqlite_pragma)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
