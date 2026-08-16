# backend/scripts/verify_project_model_settings_api.py
"""项目设置「模型设置」区域 API 验证脚本（docs/TECHv1.1.md §5.2 / PRD v1.1 §4.2）。

运行方式（在 backend/ 下）：
    python scripts/verify_project_model_settings_api.py

覆盖前端 ProjectModelSettings 依赖的完整 API 契约：
- GET  /model-providers：提供商列表摘要（供提供商下拉）；
- GET  /model-providers/{id}：提供商详情（models 含启用状态，供模型下拉）；
- GET  /settings/app：全局默认提供商/模型（供只读提示）；
- POST /projects：创建项目，未传默认提供商/模型时继承全局默认；
- PATCH /projects/{id}：保存 default_provider_id / default_model_id；
  显式传 null 清空（使用全局默认）；
- GET  /projects/{id}：反映新字段。
所有断言通过时打印 OK 汇总并以退出码 0 结束（使用临时 SQLite，不影响正式库）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# Windows 控制台可能为 GBK：强制 UTF-8 输出避免编码异常
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.model_provider import create_provider  # noqa: E402

_passed = 0
_failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [OK] {label}")
    else:
        _failed += 1
        print(f"  [FAIL] {label}  {detail}")


async def main() -> None:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_project_model_settings_")
    os.close(fd)
    engine = create_async_engine("sqlite+aiosqlite:///" + path.replace("\\", "/"))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_get_db():
            async with maker() as session:
                yield session

        from app.api.v1.model_providers import router as providers_router
        from app.api.v1.projects import router as projects_router
        from app.api.v1.settings import router as settings_router

        test_app = FastAPI()
        test_app.include_router(providers_router)
        test_app.include_router(projects_router)
        test_app.include_router(settings_router)
        test_app.dependency_overrides[get_db] = override_get_db

        # 准备数据：提供商 A（含 2 个启用模型）+ 提供商 B，设置全局默认 = A + 模型A
        async with maker() as db:
            provider_a = await create_provider(
                db,
                name="提供商A",
                type="openai",
                base_url="https://api.openai.com/v1",
                api_keys=[{"key": "sk-test-a-1111", "enabled": True, "priority": 1}],
            )
            provider_a.models_json = [
                {"model_id": "gpt-4o", "enabled": True},
                {"model_id": "gpt-4o-mini", "enabled": True},
                {"model_id": "gpt-3.5-turbo", "enabled": False},
            ]
            provider_b = await create_provider(
                db,
                name="提供商B",
                type="deepseek",
                base_url="https://api.deepseek.com/v1",
                api_keys=[{"key": "sk-test-b-2222", "enabled": True, "priority": 1}],
            )
            provider_b.models_json = [{"model_id": "deepseek-chat", "enabled": True}]
            await db.commit()
            provider_a_id, provider_b_id = provider_a.id, provider_b.id

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            print("[1] 提供商列表（下拉数据源）")
            r = await client.get("/api/v1/model-providers")
            rows = r.json()
            check("GET /model-providers 200 且含两个提供商", r.status_code == 200 and len(rows) == 2, str(rows))
            check(
                "摘要含 name/type/status/key_count/model_count",
                all(k in rows[0] for k in ("id", "name", "type", "status", "key_count", "model_count")),
                str(rows[0]),
            )

            print("[2] 提供商详情（模型下拉数据源：仅启用模型）")
            r = await client.get(f"/api/v1/model-providers/{provider_a_id}")
            detail = r.json()
            enabled = [m["model_id"] for m in detail.get("models", []) if m["enabled"]]
            check(
                "GET /model-providers/{id} 返回启用模型列表",
                r.status_code == 200 and enabled == ["gpt-4o", "gpt-4o-mini"],
                str(enabled),
            )

            print("[3] 全局默认（只读提示数据源）")
            r = await client.patch(
                "/api/v1/settings/app",
                json={
                    "global_default_provider_id": provider_a_id,
                    "global_default_model_id": "gpt-4o",
                },
            )
            check("PATCH /settings/app 设置全局默认 200", r.status_code == 200, r.text)
            r = await client.get("/api/v1/settings/app")
            s = r.json()
            check(
                "GET /settings/app 返回全局默认提供商/模型",
                r.status_code == 200
                and s["global_default_provider_id"] == provider_a_id
                and s["global_default_model_id"] == "gpt-4o",
                str(s),
            )

            print("[4] 创建项目继承全局默认")
            r = await client.post("/api/v1/projects", json={"title": "继承全局"})
            p = r.json()
            project_id = p["id"]
            check(
                "POST /projects 继承全局默认提供商/模型",
                r.status_code == 201
                and p["default_provider_id"] == provider_a_id
                and p["default_model_id"] == "gpt-4o",
                str(p),
            )

            print("[5] 保存项目模型设置（关闭使用全局默认）")
            r = await client.patch(
                f"/api/v1/projects/{project_id}",
                json={
                    "default_provider_id": provider_b_id,
                    "default_model_id": "deepseek-chat",
                },
            )
            check(
                "PATCH 保存自定义提供商/模型 200",
                r.status_code == 200
                and r.json()["default_provider_id"] == provider_b_id
                and r.json()["default_model_id"] == "deepseek-chat",
                str(r.json()),
            )
            r = await client.get(f"/api/v1/projects/{project_id}")
            check(
                "GET /projects/{id} 反映新设置",
                r.json()["default_provider_id"] == provider_b_id
                and r.json()["default_model_id"] == "deepseek-chat",
                str(r.json()),
            )

            print("[6] 切回使用全局默认（传 null 清空）")
            r = await client.patch(
                f"/api/v1/projects/{project_id}",
                json={"default_provider_id": None, "default_model_id": None},
            )
            check(
                "PATCH 传 null 清空项目默认",
                r.status_code == 200
                and r.json()["default_provider_id"] is None
                and r.json()["default_model_id"] is None,
                str(r.json()),
            )

            print("[7] 校验：提供商不存在 → 400")
            r = await client.patch(
                f"/api/v1/projects/{project_id}",
                json={"default_provider_id": "no-such-provider", "default_model_id": "x"},
            )
            check("PATCH 引用不存在提供商 400", r.status_code == 400, f"{r.status_code} {r.text}")

    finally:
        await engine.dispose()
        if os.path.exists(path):
            try:
                os.remove(path)
            except PermissionError:
                pass  # Windows 偶发连接未完全释放，忽略清理失败

    print(f"\n结果：{_passed} 通过，{_failed} 失败")
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
