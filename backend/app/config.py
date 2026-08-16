"""全局配置：从环境变量或 .env 文件读取（pydantic-settings）。

环境变量清单参考 docs/TECH.md 第 3 节：
    HOST / PORT / DATA_DIR / DATABASE_URL / CHROMA_PERSIST_DIR / FRONTEND_DIST
所有字段均提供默认值，本地运行可不配置任何环境变量。
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """FictionForge 本地后端配置（环境变量大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 服务监听
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # 数据目录与存储位置
    DATA_DIR: str = "./data"
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/fictionforge.db"
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    FRONTEND_DIST: str = "../frontend/dist"  # 前端构建产物（不存在则不挂载）

    # 日志
    LOG_DIR: str = "./data/logs"
    LOG_LEVEL: str = "INFO"  # 控制台与 app.log 的最低级别；error.log 恒为 ERROR+
    LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 单日志文件超过 5MB 滚动
    LOG_BACKUP_COUNT: int = 5  # 保留 5 份滚动备份

    # ---- 便捷属性（Path 形式，供业务代码使用）----
    @property
    def data_dir(self) -> Path:
        return Path(self.DATA_DIR)

    @property
    def log_dir(self) -> Path:
        return Path(self.LOG_DIR)

    @property
    def chroma_persist_dir(self) -> Path:
        return Path(self.CHROMA_PERSIST_DIR)

    @property
    def frontend_dist(self) -> Path:
        return Path(self.FRONTEND_DIST)


settings = Settings()
