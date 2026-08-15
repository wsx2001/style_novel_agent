# backend/scripts/verify_prompt_templates_api.py
"""提示词模板管理 API 验证脚本（docs/TECHv1.md §4.3 / §5.7）。

运行方式（在 backend/ 下）：
    python scripts/verify_prompt_templates_api.py

覆盖：
- schema 校验（PromptTemplateCreate/Update/Duplicate/Read）；
- 启动初始化 ensure_system_default_template：创建「自动模板」、幂等、全局默认自动指向；
- 模板 API 全端点（ASGI 直接驱动，走真实依赖注入）：
  GET/POST /prompt-templates、GET/PATCH/DELETE /prompt-templates/{id}、
  POST /prompt-templates/{id}/duplicate；
- 错误路径：项目不存在 404、系统模板删除 403、scope/project_id 搭配 400、scope 非法 422。
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
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models import AppConfig, Base, Project, PromptTemplate  # noqa: E402
from app.schemas.prompt_template import (  # noqa: E402
    PromptTemplateCreate,
    PromptTemplateDuplicate,
    PromptTemplateRead,
    PromptTemplateUpdate,
)
from app.services.llm.prompts import (  # noqa: E402
    DEFAULT_SYSTEM_PROMPT_CONTENT,
    GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY,
)
from app.services.prompt_template import ensure_system_default_template  # noqa: E402

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
    print("[1] schema 校验")
    create = PromptTemplateCreate.model_validate(
        {"name": "文风", "content": "正文：{{PROJECT_INFO}}", "scope": "global"}
    )
    check("create 解析", create.name == "文风" and create.scope == "global", str(create))
    try:
        PromptTemplateCreate.model_validate({"name": "x", "content": "y", "scope": "bad"})
        check("create scope 非法拒绝", False)
    except Exception:
        check("create scope 非法拒绝", True)

    upd = PromptTemplateUpdate.model_validate({"name": "新名"})
    check("update 仅显式字段", upd.model_dump(exclude_unset=True) == {"name": "新名"}, str(upd.model_dump()))
    dup = PromptTemplateDuplicate.model_validate(
        {"new_name": "副本", "scope": "project", "project_id": "p1"}
    )
    check("duplicate 解析", dup.scope == "project" and dup.project_id == "p1", str(dup))


async def test_seeding(db) -> None:
    print("[2] 启动初始化：系统默认「自动模板」")
    # 先写入全局默认 AppConfig（模拟 database.seed_default_app_configs）
    db.add(AppConfig(key=GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY, value=""))
    await db.commit()

    tpl = await ensure_system_default_template(db)
    check("创建自动模板", tpl.is_system and tpl.scope == "global", f"{tpl.is_system}/{tpl.scope}")
    check("名称=自动模板", tpl.name == "自动模板", tpl.name)
    check("内容为内置默认", tpl.content == DEFAULT_SYSTEM_PROMPT_CONTENT)
    check("内容含占位符", "{{PROJECT_INFO}}" in tpl.content and "{{USER_INPUT}}" in tpl.content)

    read = PromptTemplateRead.model_validate(tpl)
    check("PromptTemplateRead 序列化", read.id == tpl.id and read.is_system, str(read))

    # 幂等：再次调用不重复创建
    tpl2 = await ensure_system_default_template(db)
    system_global = (
        await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.is_system.is_(True),
                PromptTemplate.scope == "global",
            )
        )
    ).scalars().all()
    check("幂等不重复创建", len(system_global) == 1 and tpl2.id == tpl.id, str(len(system_global)))

    # 全局默认已自动指向该模板
    cfg = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY)
    )
    check("全局默认自动指向", cfg == tpl.id, str(cfg))


async def test_api(client: AsyncClient, maker) -> None:
    print("[3] 模板 API（ASGI 驱动）")
    # 准备两个项目（项目模板归属校验用）
    async with maker() as db:
        proj = Project(title="测试书", genre="玄幻")
        other = Project(title="其它书")
        db.add_all([proj, other])
        await db.commit()
        proj_id = proj.id
        other_id = other.id

    # ---- 列表 ----
    r = await client.get("/api/v1/prompt-templates")
    check("list 全量含自动模板", r.status_code == 200 and any(t["is_system"] for t in r.json()), str(r.status_code))

    # ---- 创建 ----
    r = await client.post(
        "/api/v1/prompt-templates",
        json={"name": "全局文风", "content": "全局：{{PROJECT_INFO}}", "scope": "global"},
    )
    check("create global 201", r.status_code == 201 and r.json()["scope"] == "global", str(r.status_code))
    gid = r.json()["id"]

    r = await client.post(
        "/api/v1/prompt-templates",
        json={"name": "项目文风", "content": "项目正文", "scope": "project", "project_id": proj_id},
    )
    check("create project 201", r.status_code == 201 and r.json()["project_id"] == proj_id, str(r.status_code))
    pid = r.json()["id"]

    r = await client.post(
        "/api/v1/prompt-templates",
        json={"name": "x", "content": "y", "scope": "project", "project_id": "no-such-project"},
    )
    check("create 项目不存在 404", r.status_code == 404, str(r.status_code))
    r = await client.post(
        "/api/v1/prompt-templates", json={"name": "x", "content": "y", "scope": "project"}
    )
    check("create project 缺 project_id 400", r.status_code == 400, str(r.status_code))
    r = await client.post(
        "/api/v1/prompt-templates",
        json={"name": "x", "content": "y", "scope": "global", "project_id": proj_id},
    )
    check("create global 带 project_id 400", r.status_code == 400, str(r.status_code))
    r = await client.post(
        "/api/v1/prompt-templates", json={"name": "x", "content": "y", "scope": "bad"}
    )
    check("create scope 非法 422", r.status_code == 422, str(r.status_code))

    # ---- 列表过滤 ----
    r = await client.get("/api/v1/prompt-templates", params={"scope": "global"})
    check("list scope=global 全部 global", r.status_code == 200 and all(t["scope"] == "global" for t in r.json()), str(r.status_code))
    r = await client.get("/api/v1/prompt-templates", params={"scope": "project"})
    check("list scope=project 含项目模板", r.status_code == 200 and any(t["id"] == pid for t in r.json()), str(r.status_code))
    r = await client.get("/api/v1/prompt-templates", params={"scope": "project", "project_id": other_id})
    check("list 其它项目过滤为空", r.status_code == 200 and all(t["project_id"] != proj_id for t in r.json()), str(r.json()))
    r = await client.get("/api/v1/prompt-templates", params={"scope": "foo"})
    check("list scope 非法 400", r.status_code == 400, str(r.status_code))

    # ---- 详情 ----
    r = await client.get(f"/api/v1/prompt-templates/{gid}")
    check("get 详情", r.status_code == 200 and r.json()["name"] == "全局文风", str(r.status_code))
    r = await client.get("/api/v1/prompt-templates/no-such-id")
    check("get 不存在 404", r.status_code == 404, str(r.status_code))

    # ---- 更新 ----
    r = await client.patch(f"/api/v1/prompt-templates/{gid}", json={"name": "全局文风v2", "content": "v2内容"})
    check("patch name/content", r.status_code == 200 and r.json()["name"] == "全局文风v2", str(r.status_code))
    r = await client.patch(f"/api/v1/prompt-templates/{gid}", json={"scope": "project"})
    check("patch global→project 未绑定 400", r.status_code == 400, str(r.status_code))
    r = await client.patch(f"/api/v1/prompt-templates/{pid}", json={"scope": "global"})
    check("patch project→global 清空项目", r.status_code == 200 and r.json()["project_id"] is None, str(r.json()))

    # ---- 删除 ----
    r = await client.get("/api/v1/prompt-templates", params={"scope": "global"})
    sys_id = next(t["id"] for t in r.json() if t["is_system"])
    r = await client.delete(f"/api/v1/prompt-templates/{sys_id}")
    check("delete 系统模板 403", r.status_code == 403, str(r.status_code))
    r = await client.delete(f"/api/v1/prompt-templates/{gid}")
    check("delete 普通模板 204", r.status_code == 204, str(r.status_code))
    r = await client.get(f"/api/v1/prompt-templates/{gid}")
    check("删除后 get 404", r.status_code == 404, str(r.status_code))
    r = await client.delete("/api/v1/prompt-templates/no-such-id")
    check("delete 不存在 404", r.status_code == 404, str(r.status_code))

    # ---- 复制 ----
    r = await client.post(
        f"/api/v1/prompt-templates/{sys_id}/duplicate",
        json={"new_name": "自动模板副本", "scope": "project", "project_id": proj_id},
    )
    check("duplicate 到项目 201", r.status_code == 201, str(r.status_code))
    dup = r.json()
    check("duplicate is_system=False 且归属项目", dup["is_system"] is False and dup["scope"] == "project" and dup["project_id"] == proj_id, str(dup))
    check("duplicate 内容一致", dup["content"] == DEFAULT_SYSTEM_PROMPT_CONTENT)
    r = await client.post(
        f"/api/v1/prompt-templates/{sys_id}/duplicate",
        json={"new_name": "副本", "scope": "project", "project_id": "no-such-project"},
    )
    check("duplicate 项目不存在 404", r.status_code == 404, str(r.status_code))
    r = await client.post(
        "/api/v1/prompt-templates/no-such-id/duplicate",
        json={"new_name": "副本", "scope": "global"},
    )
    check("duplicate 源不存在 404", r.status_code == 404, str(r.status_code))


async def main() -> None:
    test_schemas()

    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_tpl_api_test_")
    os.close(fd)
    engine = create_async_engine("sqlite+aiosqlite:///" + path.replace("\\", "/"))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_get_db():
            async with maker() as session:
                yield session

        from app.api.v1.prompt_templates import router as tpl_router

        test_app = FastAPI()
        test_app.include_router(tpl_router)
        test_app.dependency_overrides[get_db] = override_get_db

        async with maker() as db:
            await test_seeding(db)

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await test_api(client, maker)
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
