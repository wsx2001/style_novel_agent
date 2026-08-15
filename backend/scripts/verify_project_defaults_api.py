# backend/scripts/verify_project_defaults_api.py
"""项目默认模型配置 / 默认提示词模板更新 API 验证脚本（docs/TECHv1.md §4.2 / §5.1）。

运行方式（在 backend/ 下）：
    python scripts/verify_project_defaults_api.py

覆盖：
- schema：ProjectUpdate / ProjectRead 解析 default_model_config / default_prompt_template_id；
- PATCH /projects/{id}：更新默认模型配置、设置/清除默认模板；
- 校验：模板不存在 → 400；引用其他项目的项目模板 → 400；
  同项目项目模板 / 全局模板 → 200；
- GET /projects/{id} 反映新字段。
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
from app.models import Base, Project, PromptTemplate  # noqa: E402
from app.schemas.project import ProjectRead, ProjectUpdate  # noqa: E402

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
    u = ProjectUpdate.model_validate(
        {"title": "改名", "default_model_config": {"depth": "high"}, "default_prompt_template_id": None}
    )
    dumped = u.model_dump(exclude_unset=True)
    check(
        "ProjectUpdate 含默认配置字段",
        dumped.get("default_model_config") == {"depth": "high"} and "default_prompt_template_id" in dumped,
        str(dumped),
    )
    u2 = ProjectUpdate.model_validate({"title": "仅改名"})
    check(
        "ProjectUpdate 未传字段不出现在 exclude_unset",
        "default_model_config" not in u2.model_dump(exclude_unset=True),
        str(u2.model_dump(exclude_unset=True)),
    )
    r = ProjectRead.model_validate(
        {
            "id": "p1",
            "title": "书",
            "default_model_config": {"depth": "auto", "max_tokens": 2048},
            "default_prompt_template_id": "tpl1",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
    )
    check(
        "ProjectRead 含默认配置字段",
        r.default_model_config == {"depth": "auto", "max_tokens": 2048} and r.default_prompt_template_id == "tpl1",
        str(r),
    )


async def main() -> None:
    test_schemas()

    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_project_defaults_test_")
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

        test_app = FastAPI()
        test_app.include_router(projects_router)
        test_app.dependency_overrides[get_db] = override_get_db

        # 准备数据：两个项目 + 全局模板 + 项目A模板
        async with maker() as db:
            proj_a = Project(title="项目A")
            proj_b = Project(title="项目B")
            db.add_all([proj_a, proj_b])
            await db.flush()
            tpl_global = PromptTemplate(name="全局模板", content="全局", scope="global")
            tpl_proj_a = PromptTemplate(name="A模板", content="A", scope="project", project_id=proj_a.id)
            db.add_all([tpl_global, tpl_proj_a])
            await db.commit()
            proj_a_id, proj_b_id = proj_a.id, proj_b.id
            tpl_global_id, tpl_proj_a_id = tpl_global.id, tpl_proj_a.id

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            print("[2] PATCH 更新项目默认配置")
            # 更新模型配置
            r = await client.patch(
                f"/api/v1/projects/{proj_a_id}",
                json={"default_model_config": {"depth": "extreme", "temperature": 0.3, "max_tokens": 8192}},
            )
            check("PATCH 更新默认模型配置 200", r.status_code == 200 and r.json()["default_model_config"]["depth"] == "extreme", str(r.json()))
            # GET 反映
            r = await client.get(f"/api/v1/projects/{proj_a_id}")
            check("GET 反映默认模型配置", r.json()["default_model_config"].get("max_tokens") == 8192, str(r.json()))
            # 仅改标题，默认配置保留
            r = await client.patch(f"/api/v1/projects/{proj_a_id}", json={"title": "项目A改名"})
            check("PATCH 仅改标题保留默认配置", r.status_code == 200 and r.json()["default_model_config"]["depth"] == "extreme", str(r.json()))

            print("[3] PATCH 设置 / 校验默认模板")
            # 全局模板 → OK
            r = await client.patch(f"/api/v1/projects/{proj_a_id}", json={"default_prompt_template_id": tpl_global_id})
            check("设置全局模板为默认", r.status_code == 200 and r.json()["default_prompt_template_id"] == tpl_global_id, str(r.json()))
            # 同项目项目模板 → OK
            r = await client.patch(f"/api/v1/projects/{proj_a_id}", json={"default_prompt_template_id": tpl_proj_a_id})
            check("设置同项目模板为默认", r.status_code == 200 and r.json()["default_prompt_template_id"] == tpl_proj_a_id, str(r.json()))
            # 其他项目的项目模板 → 400
            r = await client.patch(f"/api/v1/projects/{proj_b_id}", json={"default_prompt_template_id": tpl_proj_a_id})
            check("引用其他项目模板 400", r.status_code == 400, f"{r.status_code} {r.text}")
            # 不存在的模板 → 400
            r = await client.patch(f"/api/v1/projects/{proj_a_id}", json={"default_prompt_template_id": "no-such"})
            check("引用不存在模板 400", r.status_code == 400, f"{r.status_code} {r.text}")
            # 显式 null → 清空
            r = await client.patch(f"/api/v1/projects/{proj_a_id}", json={"default_prompt_template_id": None})
            check("显式 null 清空默认模板", r.status_code == 200 and r.json()["default_prompt_template_id"] is None, str(r.json()))

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
