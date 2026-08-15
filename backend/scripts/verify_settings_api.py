# backend/scripts/verify_settings_api.py
"""设置 API 验证脚本（docs/TECHv1.md §5.8 / §8.1）。

运行方式（在 backend/ 下）：
    python scripts/verify_settings_api.py

覆盖：
- schema：GlobalAppConfigRead/Update、DepthMappingUpdate 解析；
- GET/PATCH /settings/app：种子值读取、更新、部分更新、模板校验 400；
- GET/PATCH /settings/depth-mapping：未配置返回内置默认、partial update 不抹除 default；
- 项目创建继承全局默认：新建项目复制 global_default_model_config 与
  global_default_prompt_template_id；全局清空时回退标准默认与 None。
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
from app.models import AppConfig, Base, Project, PromptTemplate  # noqa: E402
from app.schemas.settings import (  # noqa: E402
    DepthMappingUpdate,
    GlobalAppConfigRead,
    GlobalAppConfigUpdate,
)

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


def test_schemas() -> None:
    print("[1] schema 解析")
    g = GlobalAppConfigRead.model_validate(
        {"global_default_model_config": {"depth": "auto"}, "global_default_prompt_template_id": ""}
    )
    check("GlobalAppConfigRead 解析", g.global_default_model_config == {"depth": "auto"} and g.global_default_prompt_template_id == "", str(g))
    u = GlobalAppConfigUpdate.model_validate({"global_default_model_config": {"depth": "high"}})
    check("GlobalAppConfigUpdate 部分字段", u.model_dump(exclude_unset=True) == {"global_default_model_config": {"depth": "high"}}, str(u.model_dump()))
    d = DepthMappingUpdate.model_validate({"model_overrides": {"o1-mini": {}}})
    check("DepthMappingUpdate 部分字段", d.model_dump(exclude_unset=True) == {"model_overrides": {"o1-mini": {}}}, str(d.model_dump()))


async def test_global_settings(client: AsyncClient, maker) -> None:
    print("[2] GET/PATCH /settings/app")
    # 无记录时返回友好默认
    r = await client.get("/api/v1/settings/app")
    check("无记录返回默认", r.status_code == 200 and r.json()["global_default_model_config"] == {} and r.json()["global_default_prompt_template_id"] == "", str(r.json()))

    # 模拟 init_db 种子记录
    async with maker() as db:
        db.add(AppConfig(key="global_default_model_config", value={"depth": "auto"}))
        db.add(AppConfig(key="global_default_prompt_template_id", value=""))
        await db.commit()
    r = await client.get("/api/v1/settings/app")
    check("种子记录返回", r.status_code == 200 and r.json()["global_default_model_config"] == {"depth": "auto"}, str(r.json()))

    # 创建全局模板（供全局默认引用）
    async with maker() as db:
        tpl = PromptTemplate(name="全局默认", content="全局提示词", scope="global", is_system=True)
        db.add(tpl)
        await db.commit()
        tpl_id = tpl.id

    # 更新 model config + 模板
    r = await client.patch(
        "/api/v1/settings/app",
        json={
            "global_default_model_config": {"depth": "high", "temperature": 0.5, "max_tokens": 4096},
            "global_default_prompt_template_id": tpl_id,
        },
    )
    check("PATCH 更新成功", r.status_code == 200 and r.json()["global_default_model_config"] == {"depth": "high", "temperature": 0.5, "max_tokens": 4096} and r.json()["global_default_prompt_template_id"] == tpl_id, str(r.json()))
    r = await client.get("/api/v1/settings/app")
    check("GET 反映更新", r.json()["global_default_model_config"]["depth"] == "high", str(r.json()))

    # 部分更新：仅清除模板，model config 保留
    r = await client.patch("/api/v1/settings/app", json={"global_default_prompt_template_id": ""})
    check("PATCH 清除模板", r.status_code == 200 and r.json()["global_default_prompt_template_id"] == "", str(r.json()))
    r = await client.get("/api/v1/settings/app")
    check("清除模板后 model config 保留", r.json()["global_default_model_config"]["depth"] == "high", str(r.json()))

    # 模板不存在 → 400
    r = await client.patch("/api/v1/settings/app", json={"global_default_prompt_template_id": "no-such"})
    check("PATCH 模板不存在 400", r.status_code == 400, str(r.status_code))


async def test_depth_mapping(client: AsyncClient) -> None:
    print("[3] GET/PATCH /settings/depth-mapping")
    r = await client.get("/api/v1/settings/depth-mapping")
    check("未配置返回内置默认", r.status_code == 200 and "default" in r.json() and "model_overrides" in r.json(), str(r.json()))

    # partial update：仅 model_overrides，default 保留
    r = await client.patch(
        "/api/v1/settings/depth-mapping",
        json={"model_overrides": {"o1-mini": {"high": {"reasoning_effort": "high"}}}},
    )
    check("PATCH 部分更新", r.status_code == 200 and r.json()["model_overrides"]["o1-mini"]["high"]["reasoning_effort"] == "high", str(r.json()))
    r = await client.get("/api/v1/settings/depth-mapping")
    check("GET 反映覆盖配置", r.json()["model_overrides"]["o1-mini"]["high"]["reasoning_effort"] == "high")
    check("default 未被抹除", "low" in r.json()["default"], str(r.json().get("default", {})))

    # 全量替换 default + 清空 overrides
    r = await client.patch(
        "/api/v1/settings/depth-mapping",
        json={"default": {"high": {"temperature": 0.2, "max_tokens": 1024}}, "model_overrides": {}},
    )
    check("PATCH 全量替换", r.status_code == 200 and r.json()["default"]["high"]["max_tokens"] == 1024 and r.json()["model_overrides"] == {}, str(r.json()))


async def test_project_inherit(client: AsyncClient, maker) -> None:
    print("[4] 项目创建继承全局默认")
    # 设置全局：模型配置 + 模板
    async with maker() as db:
        tpl = PromptTemplate(name="全局模板", content="全局提示词", scope="global", is_system=True)
        db.add(tpl)
        await db.commit()
        tpl_id = tpl.id
    r = await client.patch(
        "/api/v1/settings/app",
        json={"global_default_model_config": {"depth": "medium", "temperature": 0.6}, "global_default_prompt_template_id": tpl_id},
    )
    check("预置全局设置", r.status_code == 200, str(r.status_code))

    r = await client.post("/api/v1/projects", json={"title": "新书", "genre": "玄幻"})
    check("创建项目 201", r.status_code == 201, str(r.status_code))
    proj_id = r.json()["id"]
    async with maker() as db:
        proj = await db.get(Project, proj_id)
        check("项目默认模型配置继承全局", proj.default_model_config == {"depth": "medium", "temperature": 0.6}, str(proj.default_model_config))
        check("项目默认模板继承全局", proj.default_prompt_template_id == tpl_id, str(proj.default_prompt_template_id))

    # 清除全局后新建项目 → 标准默认模型配置 + 无默认模板
    r = await client.patch(
        "/api/v1/settings/app",
        json={"global_default_model_config": {}, "global_default_prompt_template_id": ""},
    )
    check("清除全局设置", r.status_code == 200, str(r.status_code))
    r = await client.post("/api/v1/projects", json={"title": "另一本"})
    check("创建项目 201（清除后）", r.status_code == 201, str(r.status_code))
    proj2_id = r.json()["id"]
    async with maker() as db:
        proj2 = await db.get(Project, proj2_id)
        check("无全局时项目用标准默认", proj2.default_model_config == {"depth": "auto", "temperature": 0.7, "max_tokens": 2048}, str(proj2.default_model_config))
        check("无全局时项目无默认模板", proj2.default_prompt_template_id is None, str(proj2.default_prompt_template_id))


async def main() -> None:
    test_schemas()

    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_settings_api_test_")
    os.close(fd)
    engine = create_async_engine("sqlite+aiosqlite:///" + path.replace("\\", "/"))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_get_db():
            async with maker() as session:
                yield session

        from app.api.v1.projects import router as projects_router
        from app.api.v1.settings import router as settings_router

        test_app = FastAPI()
        test_app.include_router(settings_router)
        test_app.include_router(projects_router)
        test_app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await test_global_settings(client, maker)
            await test_depth_mapping(client)
            await test_project_inherit(client, maker)
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
