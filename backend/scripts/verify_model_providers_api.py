# backend/scripts/verify_model_providers_api.py
"""模型提供商管理 API 验证脚本（docs/TECHv1.1.md §4.2 / §5.1 / PRD v1.1 §2.1）。

运行方式（在 backend/ 下）：
    python scripts/verify_model_providers_api.py

覆盖：
- schema：ModelProviderCreate / Update / Read / ApiKeyInput / ModelItem / ProviderSummary 解析；
- 提供商 API 全端点（ASGI 直接驱动，走真实依赖注入）：
  GET/POST /model-providers、GET/PATCH/DELETE /model-providers/{id}、
  POST /model-providers/{id}/fetch-models、/detect、/keys/{key_id}/detect；
- 创建时自动获取模型列表（mock /models HTTP）：合并去重、写入 models 与 available_models、
  全部 Key 失败时仍创建成功（models 为空 + message「未获取到模型」）；
- 详情 api_keys 脱敏（不返回明文/密文）、更新 Key 增删改复用密文；
- 删除前解除项目 / 会话 / 生成记录引用；
- 全局默认提供商（PATCH /settings/app）与 ProviderSummary.is_default 同步。
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

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models import (  # noqa: E402
    AppConfig,
    Base,
    Conversation,
    GenerationRecord,
    ModelProvider,
    Project,
)
from app.schemas.model_provider import (  # noqa: E402
    ApiKeyInput,
    ModelItem,
    ModelProviderCreate,
    ModelProviderRead,
    ModelProviderUpdate,
    ProviderSummary,
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


def _models_response(*ids: str) -> dict:
    return {"object": "list", "data": [{"id": mid, "object": "model"} for mid in ids]}


def mock_models_handler(request: httpx.Request) -> httpx.Response:
    """按 Authorization 头返回不同模型列表；未知 Key → 401。"""
    auth = request.headers.get("Authorization", "")
    if auth == "Bearer sk-key-good-1111":
        return httpx.Response(200, json=_models_response("gpt-4o", "gpt-4o-mini"))
    if auth == "Bearer sk-key-good-2222":
        return httpx.Response(200, json=_models_response("gpt-4o-mini", "deepseek-chat"))
    return httpx.Response(401, text="bad key")


def test_schemas() -> None:
    print("[1] schema 解析")
    create = ModelProviderCreate.model_validate(
        {
            "name": "测试",
            "type": "opencode_go",
            "base_url": "http://127.0.0.1:9000/v1",
            "api_keys": [{"key": "sk-x", "enabled": True, "priority": 1}],
        }
    )
    check("create 解析 api_keys", create.api_keys[0].key == "sk-x" and create.api_keys[0].priority == 1, str(create))
    check("create auto_fetch 默认 True", create.auto_fetch is True)
    try:
        ModelProviderCreate.model_validate({"name": "x", "type": "not-a-type"})
        check("create 非法 type 拒绝", False)
    except Exception:
        check("create 非法 type 拒绝", True)

    upd = ModelProviderUpdate.model_validate({"name": "改名", "models": [{"model_id": "gpt-4o", "enabled": False}]})
    check("update 解析 models", upd.models[0].model_id == "gpt-4o" and upd.models[0].enabled is False, str(upd))
    check("update 未传字段不在 exclude_unset", "api_keys" not in upd.model_dump(exclude_unset=True), str(upd.model_dump()))

    summ = ProviderSummary.model_validate(
        {"id": "p1", "name": "n", "type": "openai", "key_count": 1, "model_count": 2, "is_default": False,
         "status": "ready", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}
    )
    check("summary 解析 status", summ.status == "ready", str(summ))
    assert ApiKeyInput and ModelItem and ModelProviderRead  # 引用以确保导入


async def test_provider_crud(client: AsyncClient, maker) -> None:
    print("[2] 提供商 CRUD + 自动获取模型")
    # ---- 创建（auto_fetch 默认 True，mock /models 全部成功） ----
    r = await client.post(
        "/api/v1/model-providers",
        json={
            "name": "我的Opencode",
            "type": "opencode_go",
            "base_url": "https://mock.local/v1",
            "api_keys": [
                {"key": "sk-key-good-1111", "enabled": True, "priority": 1},
                {"key": "sk-key-good-2222", "enabled": True, "priority": 2},
            ],
        },
    )
    check("create 201", r.status_code == 201, str(r.status_code))
    body = r.json()
    check("create auto_fetch success", body["auto_fetch"]["success"] is True, str(body.get("auto_fetch")))
    check("create 合并去重模型", sorted(body["auto_fetch"]["models"]) == ["deepseek-chat", "gpt-4o", "gpt-4o-mini"], str(body.get("auto_fetch")))
    check("create 无失败提示", body.get("message") is None, str(body.get("message")))
    provider = body["provider"]
    pid = provider["id"]
    check("provider 详情 models 已写入", [m["model_id"] for m in provider["models"]] == ["gpt-4o", "gpt-4o-mini", "deepseek-chat"], str(provider.get("models")))
    check("provider api_keys 脱敏", len(provider["api_keys"]) == 2 and all(k["key_masked"].startswith("sk-") and "..." in k["key_masked"] for k in provider["api_keys"]), str(provider.get("api_keys")))
    serialized = str(body)
    check("响应不含明文/密文", "sk-key-good-1111" not in serialized and "api_key_encrypted" not in serialized)

    # ---- 创建：全部 Key 失败 → 仍创建成功，models 为空 + 提示 ----
    r = await client.post(
        "/api/v1/model-providers",
        json={"name": "坏Key", "type": "openai", "base_url": "https://mock.local/v1",
              "api_keys": [{"key": "sk-bad-3333", "enabled": True, "priority": 1}]},
    )
    check("create 全失败仍 201", r.status_code == 201, str(r.status_code))
    bad = r.json()
    check("create 全失败 models 为空", bad["provider"]["models"] == [], str(bad["provider"].get("models")))
    check("create 全失败带提示", bad["message"] == "未获取到模型", str(bad.get("message")))
    check("create 全失败 auto_fetch.success=False", bad["auto_fetch"]["success"] is False, str(bad.get("auto_fetch")))

    # ---- 创建：auto_fetch=False 不触发获取 ----
    r = await client.post(
        "/api/v1/model-providers",
        json={"name": "不自动", "type": "deepseek", "auto_fetch": False,
              "api_keys": [{"key": "sk-key-good-1111", "enabled": True}]},
    )
    check("create auto_fetch=False 201", r.status_code == 201 and r.json()["auto_fetch"] is None, str(r.status_code))
    check("create auto_fetch=False models 空", r.json()["provider"]["models"] == [], str(r.json().get("provider")))

    # ---- 错误路径 ----
    r = await client.post("/api/v1/model-providers", json={"name": "", "type": "openai"})
    check("create 空名称 422", r.status_code == 422, str(r.status_code))
    r = await client.post("/api/v1/model-providers", json={"name": "x", "type": "openai", "api_keys": [{"enabled": True}]})
    check("create 新增 Key 缺明文 400", r.status_code == 400, str(r.status_code))

    # ---- 列表摘要 ----
    r = await client.get("/api/v1/model-providers")
    check("list 200", r.status_code == 200 and len(r.json()) == 3, str(r.status_code))
    summary = next(s for s in r.json() if s["id"] == pid)
    check("summary key_count/model_count", summary["key_count"] == 2 and summary["model_count"] == 3, str(summary))
    check("summary status=ready", summary["status"] == "ready", str(summary))
    check("summary 无 Key 信息", "key_masked" not in str(r.json()) and "api_key_encrypted" not in str(r.json()))

    # ---- 详情 ----
    r = await client.get(f"/api/v1/model-providers/{pid}")
    check("get 详情 200", r.status_code == 200 and r.json()["name"] == "我的Opencode", str(r.status_code))
    check("get 详情 Key 脱敏", all("..." in k["key_masked"] for k in r.json()["api_keys"]), str(r.json().get("api_keys")))
    r = await client.get("/api/v1/model-providers/no-such")
    check("get 不存在 404", r.status_code == 404, str(r.status_code))

    # ---- 更新：改名 + 改 base_url + 模型启停 + Key 增删（复用密文） ----
    detail = r = await client.get(f"/api/v1/model-providers/{pid}")
    key_id = detail.json()["api_keys"][0]["key_id"]
    key_masked = detail.json()["api_keys"][0]["key_masked"]
    r = await client.patch(
        f"/api/v1/model-providers/{pid}",
        json={
            "name": "改名Opencode",
            "base_url": " https://mock.local/v2 ",
            "api_keys": [
                {"key_id": key_id, "key": key_masked, "enabled": True, "priority": 1},
                {"key": "sk-key-good-2222", "enabled": True, "priority": 3},
            ],
            "models": [{"model_id": "gpt-4o", "enabled": False}, {"model_id": "gpt-4o-mini", "enabled": True}],
        },
    )
    check("patch 更新 200", r.status_code == 200, str(r.status_code))
    upd = r.json()
    check("patch name/base_url", upd["name"] == "改名Opencode" and upd["base_url"] == "https://mock.local/v2", str(upd))
    check("patch models 启停生效", {m["model_id"]: m["enabled"] for m in upd["models"]} == {"gpt-4o": False, "gpt-4o-mini": True}, str(upd.get("models")))
    check("patch Key 增删（2 条）", len(upd["api_keys"]) == 2, str(upd.get("api_keys")))
    check("patch Key 脱敏保留", any(k["key_id"] == key_id and k["key_masked"] == key_masked for k in upd["api_keys"]), str(upd.get("api_keys")))
    r = await client.patch(f"/api/v1/model-providers/{pid}", json={"api_keys": [{"key_id": "no-such", "key": "sk-x"}]})
    check("patch 未知 key_id 400", r.status_code == 400, str(r.status_code))


async def test_fetch_and_detect(client: AsyncClient, maker, pid: str) -> None:
    print("[3] fetch-models / detect")
    # ---- fetch-models：合并去重 ----
    r = await client.post(f"/api/v1/model-providers/{pid}/fetch-models")
    check("fetch-models 200", r.status_code == 200, str(r.status_code))
    check("fetch-models success + 合并", r.json()["success"] is True and sorted(r.json()["models"]) == ["deepseek-chat", "gpt-4o", "gpt-4o-mini"], str(r.json()))

    # ---- detect 所有 Key ----
    r = await client.post(f"/api/v1/model-providers/{pid}/detect")
    check("detect 200", r.status_code == 200 and len(r.json()) == 2, str(r.status_code))
    by_key = {item["key_id"]: item for item in r.json()}
    check("detect 好 Key 有效", all(item["valid"] is True for item in by_key.values()), str(r.json()))

    # ---- detect 单个 Key ----
    key_id = next(iter(by_key))
    r = await client.post(f"/api/v1/model-providers/{pid}/keys/{key_id}/detect")
    check("detect 单 Key 200 valid", r.status_code == 200 and r.json()["valid"] is True and r.json()["model_count"] == 2, str(r.json()))
    r = await client.post(f"/api/v1/model-providers/{pid}/keys/no-such-key/detect")
    check("detect 单 Key 不存在 404", r.status_code == 404, str(r.status_code))

    # ---- fetch/detect 不存在提供商 404 ----
    r = await client.post("/api/v1/model-providers/no-such/fetch-models")
    check("fetch 不存在 404", r.status_code == 404, str(r.status_code))
    r = await client.post("/api/v1/model-providers/no-such/detect")
    check("detect 不存在 404", r.status_code == 404, str(r.status_code))


async def test_global_default_and_delete(client: AsyncClient, maker) -> None:
    print("[4] 全局默认同步 + 删除解除引用")
    r = await client.get("/api/v1/model-providers")
    pid = r.json()[0]["id"]

    # 设置全局默认提供商 → summary.is_default=True
    r = await client.patch("/api/v1/settings/app", json={"global_default_provider_id": pid})
    check("设置全局默认提供商", r.status_code == 200 and r.json()["global_default_provider_id"] == pid, str(r.json()))
    r = await client.get("/api/v1/model-providers")
    check("summary is_default 同步", next(s for s in r.json() if s["id"] == pid)["is_default"] is True, str(r.json()))
    r = await client.patch("/api/v1/settings/app", json={"global_default_provider_id": "no-such"})
    check("全局默认提供商不存在 400", r.status_code == 400, str(r.status_code))

    # 构造引用：项目默认 / 会话当前 / 生成记录
    async with maker() as db:
        proj = Project(title="引用书", default_provider_id=pid, default_model_id="gpt-4o")
        db.add(proj)
        await db.flush()
        conv = Conversation(project_id=proj.id, current_provider_id=pid, current_model_id="gpt-4o")
        db.add(conv)
        await db.flush()
        gen = GenerationRecord(
            project_id=proj.id, generation_type="continue", status="completed",
            params_json={}, output_candidates=[], provider_id=pid, model_id="gpt-4o",
        )
        db.add(gen)
        await db.commit()
        proj_id, conv_id, gen_id = proj.id, conv.id, gen.id

    # 删除提供商 → 解除引用 + 清空全局默认
    r = await client.delete(f"/api/v1/model-providers/{pid}")
    check("delete 204", r.status_code == 204, str(r.status_code))
    r = await client.get(f"/api/v1/model-providers/{pid}")
    check("delete 后 get 404", r.status_code == 404, str(r.status_code))
    r = await client.delete("/api/v1/model-providers/no-such")
    check("delete 不存在 404", r.status_code == 404, str(r.status_code))

    async with maker() as db:
        proj = await db.get(Project, proj_id)
        conv = await db.get(Conversation, conv_id)
        gen = await db.get(GenerationRecord, gen_id)
        check("项目引用已解除", proj.default_provider_id is None and proj.default_model_id == "gpt-4o", str(proj.default_provider_id))
        check("会话引用已解除", conv.current_provider_id is None, str(conv.current_provider_id))
        check("生成记录引用已解除", gen.provider_id is None, str(gen.provider_id))
        cfg = await db.scalar(select(AppConfig.value).where(AppConfig.key == "global_default_provider_id"))
        check("全局默认已清空", not cfg, str(cfg))


async def main() -> None:
    test_schemas()

    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_mp_api_test_")
    os.close(fd)
    engine = create_async_engine("sqlite+aiosqlite:///" + path.replace("\\", "/"))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_get_db():
            async with maker() as session:
                yield session

        # 注入 mock /models（服务层 _new_http_client 返回 MockTransport 客户端）
        import app.services.model_provider as mp_service

        mp_service._new_http_client = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(mock_models_handler)
        )

        from app.api.v1.model_providers import router as mp_router
        from app.api.v1.settings import router as settings_router

        test_app = FastAPI()
        test_app.include_router(mp_router)
        test_app.include_router(settings_router)
        test_app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await test_provider_crud(client, maker)
            r = await client.get("/api/v1/model-providers")
            pid = r.json()[0]["id"]
            await test_fetch_and_detect(client, maker, pid)
            await test_global_default_and_delete(client, maker)
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
