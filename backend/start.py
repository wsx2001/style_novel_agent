"""FictionForge 启动脚本。

职责：
1. 切换到 backend 目录（保证 ./data、sqlite:///./data/... 等相对路径稳定）；
2. 检查并创建数据目录；
3. 初始化日志（落盘 data/logs/）；
4. 初始化数据库表（幂等）；
5. 启动 Uvicorn 监听 HOST:PORT；
6. 自动打开默认浏览器。

用法（在 backend/ 下）：
    python start.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

# 切换 stdout/stderr 为 UTF-8：避免 Windows 控制台中文日志乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 切换到 backend 目录：所有相对路径（DATA_DIR、DATABASE_URL 等）以此为准
BACKEND_DIR = Path(__file__).resolve().parent
os.chdir(BACKEND_DIR)

# 保证 `import app` 可用（即使从其他目录调用 start.py）
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.database import engine, init_db  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("app.main")


def prepare_data_dirs() -> Path:
    """检查并创建数据目录：DATA_DIR 下含 chroma / documents / exports / logs。"""
    data_dir = Path(settings.DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("chroma", "documents", "exports", "logs"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)
    return data_dir


async def _init_database() -> None:
    """初始化数据库表，并释放初始化期间（旧事件循环上）的连接。"""
    await init_db()
    await engine.dispose()


def main() -> None:
    data_dir = prepare_data_dirs()

    # 日志配置在打印前完成：后续 print/日志全部落盘
    log_dir = setup_logging()
    logger.info("FictionForge 启动：数据目录=%s，日志目录=%s", data_dir, log_dir)

    asyncio.run(_init_database())
    logger.info("数据库初始化完成")

    host, port = settings.HOST, settings.PORT
    if host in ("0.0.0.0", "::"):
        url = f"http://127.0.0.1:{port}"
    else:
        url = f"http://{host}:{port}"

    # 等服务真正监听后再打开浏览器
    threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    logger.info("服务启动中：%s（按 Ctrl+C 停止）", url)

    import uvicorn

    # log_config=None：让 uvicorn 复用上方日志配置，访问日志一并落盘 app.log
    uvicorn.run("app.main:app", host=host, port=port, reload=False, log_config=None)


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()
