# backend/tests/test_model_provider.py
"""模型提供商服务层测试（docs/TECHv1.1.md §4.2 / §5.1 / §7.2）。

覆盖：
- 提供商 CRUD：加密存储、脱敏、Key 增删改（复用旧密文 / 重新加密）、删除时解除引用；
- 多 Key 选择：优先级 + available_models 命中目标模型；
- 模型列表获取：mock /models HTTP（httpx.MockTransport），合并去重、更新 available_models、
  部分/全部失败、无启用 Key；
- 连接检测：detect_key_connection / detect_provider。
"""
from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.models import Conversation, GenerationRecord, ModelProvider, Project
from app.services.crypto.api_key import decrypt_api_key, encrypt_api_key
from app.services.model_provider import (
    NoAvailableApiKey,
    _is_masked_key,
    _mask_key,
    create_provider,
    delete_provider,
    detect_key_connection,
    detect_provider,
    detect_single_key,
    fetch_model_list,
    get_provider,
    list_providers,
    select_api_key,
    update_provider,
)

pytestmark = pytest.mark.anyio

# ---------------------------------------------------------------------------
# 构造辅助
# ---------------------------------------------------------------------------


async def _create_provider(
    session_factory,
    *,
    base_url=None,
    api_keys=None,
    name="测试提供商",
    type="openai",
):
    async with session_factory() as session:
        return await create_provider(
            session, name=name, type=type, base_url=base_url, api_keys=api_keys
        )


async def _get_provider_row(session_factory, provider_id) -> ModelProvider:
    async with session_factory() as session:
        return await session.get(ModelProvider, provider_id)


# ---------------------------------------------------------------------------
# CRUD：创建与加密
# ---------------------------------------------------------------------------


async def test_create_provider_encrypts_api_keys(session_factory):
    api_keys = [
        {"key": "sk-key-one-aaaa", "enabled": True, "priority": 1},
        {"key": "sk-key-two-bbbb", "enabled": True, "priority": 2},
    ]
    provider = await _create_provider(
        session_factory, base_url="https://api.openai.com/v1", api_keys=api_keys
    )

    assert provider.id
    assert provider.name == "测试提供商"
    assert provider.type == "openai"
    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.models_json == []

    entries = provider.api_keys_json
    assert len(entries) == 2
    for entry, expected in zip(entries, api_keys):
        assert entry["key_id"].startswith("key_")
        # 密文中不应出现明文
        assert expected["key"] not in entry["api_key_encrypted"]
        assert entry["enabled"] is True
        assert entry["priority"] == expected["priority"]
        assert entry["available_models"] == []
        # 可正确解密还原
        assert decrypt_api_key(entry["api_key_encrypted"]) == expected["key"]


async def test_create_provider_validation(session_factory):
    from app.services.model_provider import ModelProviderValidationError

    async with session_factory() as session:
        with pytest.raises(ModelProviderValidationError):
            await create_provider(session, name="  ", type="openai", api_keys=[])
        with pytest.raises(ModelProviderValidationError):
            await create_provider(
                session, name="x", type="not-a-type", api_keys=[{"key": "sk-x"}]
            )
        with pytest.raises(ModelProviderValidationError):
            # 新增 Key 必须提供明文
            await create_provider(session, name="x", type="openai", api_keys=[{"enabled": True}])


# ---------------------------------------------------------------------------
# CRUD：读取脱敏 / 摘要
# ---------------------------------------------------------------------------


async def test_get_provider_masks_api_keys(session_factory):
    provider = await _create_provider(
        session_factory, api_keys=[{"key": "sk-secret-one-aaaa", "enabled": True, "priority": 1}]
    )

    async with session_factory() as session:
        detail = await get_provider(session, provider.id)

    assert detail["id"] == provider.id
    assert len(detail["api_keys"]) == 1
    masked = detail["api_keys"][0]
    assert masked["key_masked"] == "sk-s...aaaa"  # 前4位 + ... + 后4位
    assert "..." in masked["key_masked"]
    # 响应中不得出现明文或密文
    serialized = json.dumps(detail, ensure_ascii=False, default=str)
    assert "sk-secret-one-aaaa" not in serialized
    assert "api_key_encrypted" not in serialized


async def test_get_provider_not_found(session_factory):
    from app.services.model_provider import ModelProviderNotFound

    async with session_factory() as session:
        with pytest.raises(ModelProviderNotFound):
            await get_provider(session, "no-such-id")


async def test_list_providers_summary_has_no_keys(session_factory):
    await _create_provider(
        session_factory, api_keys=[{"key": "sk-aaa", "enabled": True, "priority": 1}]
    )
    await _create_provider(session_factory, name="第二个", type="deepseek", api_keys=[
        {"key": "sk-bbb", "enabled": True, "priority": 1},
        {"key": "sk-ccc", "enabled": False, "priority": 2},
    ])

    async with session_factory() as session:
        summaries = await list_providers(session)

    assert len(summaries) == 2
    first, second = summaries
    assert first["key_count"] == 1 and first["enabled_key_count"] == 1
    assert second["key_count"] == 2 and second["enabled_key_count"] == 1
    assert second["type"] == "deepseek"
    serialized = json.dumps(summaries, ensure_ascii=False, default=str)
    assert "api_key_encrypted" not in serialized
    assert "key_masked" not in serialized
    assert "sk-bbb" not in serialized


# ---------------------------------------------------------------------------
# CRUD：更新（Key 增删改、密文复用 / 重加密）
# ---------------------------------------------------------------------------


async def test_update_provider_adds_and_removes_keys_preserving_ciphertext(session_factory):
    provider = await _create_provider(
        session_factory, api_keys=[{"key": "sk-orig-1111", "enabled": True, "priority": 1}]
    )
    original_ciphertext = provider.api_keys_json[0]["api_key_encrypted"]

    # 添加新 Key B；Key A 回传脱敏占位符 → 应复用旧密文
    async with session_factory() as session:
        updated = await update_provider(
            session,
            provider.id,
            api_keys=[
                {
                    "key_id": provider.api_keys_json[0]["key_id"],
                    "key": _mask_key("sk-orig-1111"),
                    "enabled": True,
                    "priority": 1,
                },
                {"key": "sk-added-2222", "enabled": True, "priority": 2},
            ],
        )

    assert len(updated.api_keys_json) == 2
    key_a, key_b = updated.api_keys_json
    assert key_a["api_key_encrypted"] == original_ciphertext  # 未改动 → 复用
    assert decrypt_api_key(key_b["api_key_encrypted"]) == "sk-added-2222"
    assert key_b["key_id"] != key_a["key_id"]

    # 删除 Key B：api_keys 只留 Key A → 全量替换为 1 条
    async with session_factory() as session:
        shrunk = await update_provider(
            session,
            provider.id,
            api_keys=[
                {
                    "key_id": key_a["key_id"],
                    "key": _mask_key("sk-orig-1111"),
                    "enabled": True,
                    "priority": 1,
                }
            ],
        )
    assert len(shrunk.api_keys_json) == 1
    assert shrunk.api_keys_json[0]["api_key_encrypted"] == original_ciphertext


async def test_update_provider_reencrypts_changed_key(session_factory):
    provider = await _create_provider(
        session_factory, api_keys=[{"key": "sk-old-key-0001", "enabled": True, "priority": 1}]
    )
    old_ciphertext = provider.api_keys_json[0]["api_key_encrypted"]

    async with session_factory() as session:
        updated = await update_provider(
            session,
            provider.id,
            api_keys=[
                {
                    "key_id": provider.api_keys_json[0]["key_id"],
                    "key": "sk-new-key-0002",  # 新明文（非脱敏）→ 重新加密
                    "enabled": True,
                    "priority": 1,
                }
            ],
        )

    entry = updated.api_keys_json[0]
    assert entry["api_key_encrypted"] != old_ciphertext
    assert decrypt_api_key(entry["api_key_encrypted"]) == "sk-new-key-0002"


async def test_update_provider_unknown_key_id_raises(session_factory):
    from app.services.model_provider import ModelProviderValidationError

    provider = await _create_provider(
        session_factory, api_keys=[{"key": "sk-orig-1111", "enabled": True, "priority": 1}]
    )
    async with session_factory() as session:
        with pytest.raises(ModelProviderValidationError):
            await update_provider(
                session,
                provider.id,
                api_keys=[{"key_id": "key_does_not_exist", "key": "sk-xxx", "enabled": True}],
            )


async def test_update_provider_models_and_meta_fields(session_factory):
    provider = await _create_provider(
        session_factory, api_keys=[{"key": "sk-aaa", "enabled": True}]
    )

    async with session_factory() as session:
        updated = await update_provider(
            session,
            provider.id,
            name="改名",
            base_url="  https://api.deepseek.com/v1  ",
            models=[
                {"model_id": "gpt-4o", "enabled": True},
                {"model_id": "gpt-4o-mini", "enabled": False},
            ],
        )

    assert updated.name == "改名"
    assert updated.base_url == "https://api.deepseek.com/v1"  # 已 strip
    assert updated.models_json == [
        {"model_id": "gpt-4o", "enabled": True},
        {"model_id": "gpt-4o-mini", "enabled": False},
    ]


# ---------------------------------------------------------------------------
# CRUD：删除（解除项目 / 会话 / 生成记录引用）
# ---------------------------------------------------------------------------


async def test_delete_provider_unlinks_references(session_factory):
    provider = await _create_provider(
        session_factory, api_keys=[{"key": "sk-aaa", "enabled": True, "priority": 1}]
    )

    async with session_factory() as session:
        project = Project(title="测试项目", default_provider_id=provider.id, default_model_id="gpt-4o")
        session.add(project)
        await session.flush()
        conversation = Conversation(
            project_id=project.id, current_provider_id=provider.id, current_model_id="gpt-4o"
        )
        session.add(conversation)
        generation = GenerationRecord(
            project_id=project.id,
            generation_type="continue",
            status="completed",
            params_json={},
            output_candidates=[],
            provider_id=provider.id,
            model_id="gpt-4o",
        )
        session.add(generation)
        await session.commit()
        project_id = project.id
        conversation_id = conversation.id
        generation_id = generation.id

    async with session_factory() as session:
        await delete_provider(session, provider.id)

    async with session_factory() as session:
        assert await session.get(ModelProvider, provider.id) is None
        project = await session.get(Project, project_id)
        assert project.default_provider_id is None
        assert project.default_model_id == "gpt-4o"  # 模型 ID 保留
        conversation = await session.get(Conversation, conversation_id)
        assert conversation.current_provider_id is None
        generation = await session.get(GenerationRecord, generation_id)
        assert generation.provider_id is None


# ---------------------------------------------------------------------------
# 多 Key 选择
# ---------------------------------------------------------------------------


async def _provider_with_available_models(session_factory) -> ModelProvider:
    """创建带 available_models 的提供商（经 update_provider 走真实路径）。"""
    provider = await _create_provider(
        session_factory,
        base_url="https://api.deepseek.com/v1",
        api_keys=[
            {"key": "sk-key1-1111", "enabled": True, "priority": 1},
            {"key": "sk-key2-2222", "enabled": True, "priority": 2},
        ],
    )
    key1_id = provider.api_keys_json[0]["key_id"]
    key2_id = provider.api_keys_json[1]["key_id"]
    async with session_factory() as session:
        updated = await update_provider(
            session,
            provider.id,
            api_keys=[
                {
                    "key_id": key1_id,
                    "key": _mask_key("sk-key1-1111"),
                    "enabled": True,
                    "priority": 1,
                    "available_models": ["gpt-4o", "gpt-4o-mini"],
                },
                {
                    "key_id": key2_id,
                    "key": _mask_key("sk-key2-2222"),
                    "enabled": True,
                    "priority": 2,
                    "available_models": ["gpt-4o-turbo"],
                },
            ],
        )
    return updated


async def test_select_api_key_priority_and_target_model(session_factory):
    provider = await _provider_with_available_models(session_factory)

    # 命中目标模型：key2 唯一支持 gpt-4o-turbo
    key, plain = select_api_key(provider, "gpt-4o-turbo")
    assert key["key_id"] != provider.api_keys_json[0]["key_id"]
    assert plain == "sk-key2-2222"

    # 多个支持时取优先级最高（priority 1 的 key1）
    key, plain = select_api_key(provider, "gpt-4o")
    assert key["key_id"] == provider.api_keys_json[0]["key_id"]
    assert plain == "sk-key1-1111"

    # 都不包含目标模型 → 兜底第一个启用 Key（优先级最高）
    key, plain = select_api_key(provider, "nonexistent-model")
    assert key["key_id"] == provider.api_keys_json[0]["key_id"]
    assert plain == "sk-key1-1111"


async def test_select_api_key_skips_disabled(session_factory):
    provider = await _provider_with_available_models(session_factory)
    key1_id = provider.api_keys_json[0]["key_id"]

    # 禁用 key1 → 只剩 key2
    async with session_factory() as session:
        updated = await update_provider(
            session,
            provider.id,
            api_keys=[
                {
                    "key_id": key1_id,
                    "key": _mask_key("sk-key1-1111"),
                    "enabled": False,
                    "priority": 1,
                },
                {"key_id": provider.api_keys_json[1]["key_id"], "key": _mask_key("sk-key2-2222"),
                 "enabled": True, "priority": 2},
            ],
        )
    key, plain = select_api_key(updated, "gpt-4o")  # key1 禁用且唯一支持 gpt-4o
    assert plain == "sk-key2-2222"  # 兜底到 key2
    assert key["enabled"] is True


async def test_select_api_key_no_enabled_raises(session_factory):
    provider = await _provider_with_available_models(session_factory)
    k1, k2 = provider.api_keys_json[0]["key_id"], provider.api_keys_json[1]["key_id"]

    async with session_factory() as session:
        updated = await update_provider(
            session,
            provider.id,
            api_keys=[
                {"key_id": k1, "key": _mask_key("sk-key1-1111"), "enabled": False, "priority": 1},
                {"key_id": k2, "key": _mask_key("sk-key2-2222"), "enabled": False, "priority": 2},
            ],
        )
    with pytest.raises(NoAvailableApiKey):
        select_api_key(updated, "gpt-4o")


# ---------------------------------------------------------------------------
# 模型列表获取（mock /models HTTP）
# ---------------------------------------------------------------------------


def _models_response(*ids: str) -> dict:
    return {"object": "list", "data": [{"id": mid, "object": "model"} for mid in ids]}


async def test_fetch_model_list_merges_and_updates_available_models(
    session_factory, http_client_factory
):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.deepseek.com/v1",
        api_keys=[
            {"key": "sk-key1-1111", "enabled": True, "priority": 1},
            {"key": "sk-key2-2222", "enabled": True, "priority": 2},
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.deepseek.com/v1/models"
        auth = request.headers["Authorization"]
        if auth == "Bearer sk-key1-1111":
            return httpx.Response(200, json=_models_response("gpt-4o", "gpt-4o-mini"))
        if auth == "Bearer sk-key2-2222":
            return httpx.Response(200, json=_models_response("gpt-4o-mini", "gpt-4o-turbo"))
        return httpx.Response(401, text="unauthorized")

    client = http_client_factory(handler)
    async with session_factory() as session:
        result = await fetch_model_list(session, provider.id, http_client=client)

    assert result["success"] is True
    assert result["models"] == ["gpt-4o", "gpt-4o-mini", "gpt-4o-turbo"]  # 合并去重，保持顺序
    assert result["errors"] == []

    async with session_factory() as session:
        row = await session.get(ModelProvider, provider.id)
        assert row.models_json == [
            {"model_id": "gpt-4o", "enabled": True},
            {"model_id": "gpt-4o-mini", "enabled": True},
            {"model_id": "gpt-4o-turbo", "enabled": True},
        ]
        by_key = {k["key_id"]: k["available_models"] for k in row.api_keys_json}
        assert by_key[provider.api_keys_json[0]["key_id"]] == ["gpt-4o", "gpt-4o-mini"]
        assert by_key[provider.api_keys_json[1]["key_id"]] == ["gpt-4o-mini", "gpt-4o-turbo"]


async def test_fetch_model_list_preserves_manual_models(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[{"key": "sk-key1-1111", "enabled": True, "priority": 1}],
    )
    async with session_factory() as session:
        await update_provider(
            session, provider.id, models=[{"model_id": "manual-model", "enabled": False}]
        )

    client = http_client_factory(lambda req: httpx.Response(200, json=_models_response("gpt-4o")))
    async with session_factory() as session:
        result = await fetch_model_list(session, provider.id, http_client=client)

    assert result["success"] is True
    async with session_factory() as session:
        row = await session.get(ModelProvider, provider.id)
        assert row.models_json == [
            {"model_id": "manual-model", "enabled": False},  # 手动模型保留
            {"model_id": "gpt-4o", "enabled": True},
        ]


async def test_fetch_model_list_partial_failure(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[
            {"key": "sk-good-1111", "enabled": True, "priority": 1},
            {"key": "sk-bad-2222", "enabled": True, "priority": 2},
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == "Bearer sk-good-1111":
            return httpx.Response(200, json=_models_response("gpt-4o"))
        return httpx.Response(401, text="Invalid API key")

    client = http_client_factory(handler)
    async with session_factory() as session:
        result = await fetch_model_list(session, provider.id, http_client=client)

    assert result["success"] is True  # 至少一个 Key 成功
    assert result["models"] == ["gpt-4o"]
    assert len(result["errors"]) == 1
    assert result["errors"][0]["key_id"] == provider.api_keys_json[1]["key_id"]
    assert "401" in result["errors"][0]["error"]

    # 失败 Key 的 available_models 保留原值（空）
    async with session_factory() as session:
        row = await session.get(ModelProvider, provider.id)
        by_key = {k["key_id"]: k["available_models"] for k in row.api_keys_json}
        assert by_key[provider.api_keys_json[1]["key_id"]] == []


async def test_fetch_model_list_all_fail(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[
            {"key": "sk-bad-1111", "enabled": True, "priority": 1},
            {"key": "sk-bad-2222", "enabled": True, "priority": 2},
        ],
    )
    client = http_client_factory(lambda req: httpx.Response(401, text="bad key"))
    async with session_factory() as session:
        result = await fetch_model_list(session, provider.id, http_client=client)

    assert result["success"] is False
    assert result["models"] == []
    assert len(result["errors"]) == 2


async def test_fetch_model_list_no_enabled_keys(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[{"key": "sk-off-1111", "enabled": True, "priority": 1}],
    )
    async with session_factory() as session:
        await update_provider(
            session,
            provider.id,
            api_keys=[
                {"key_id": provider.api_keys_json[0]["key_id"], "key": _mask_key("sk-off-1111"),
                 "enabled": False, "priority": 1}
            ],
        )
    client = http_client_factory(lambda req: httpx.Response(200, json=_models_response("gpt-4o")))
    async with session_factory() as session:
        result = await fetch_model_list(session, provider.id, http_client=client)

    assert result["success"] is False
    assert result["errors"] == [{"key_id": None, "error": "提供商没有启用的 API Key"}]


async def test_fetch_model_list_bad_json_and_empty_list(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[{"key": "sk-key-1111", "enabled": True, "priority": 1}],
    )

    async with session_factory() as session:
        result = await fetch_model_list(
            session,
            provider.id,
            http_client=http_client_factory(
                lambda req: httpx.Response(200, text="<html>not json</html>")
            ),
        )
        assert result["success"] is False
        assert "JSON" in result["errors"][0]["error"]

        result = await fetch_model_list(
            session, provider.id,
            http_client=http_client_factory(lambda req: httpx.Response(200, json={"data": []})),
        )
        assert result["success"] is False
        assert "未找到模型列表" in result["errors"][0]["error"]


async def test_fetch_model_list_connection_error(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[{"key": "sk-key-1111", "enabled": True, "priority": 1}],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with session_factory() as session:
        result = await fetch_model_list(
            session, provider.id, http_client=http_client_factory(handler)
        )

    assert result["success"] is False
    assert "请求失败" in result["errors"][0]["error"]


async def test_fetch_model_list_no_base_url(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory, api_keys=[{"key": "sk-key-1111", "enabled": True, "priority": 1}]
    )
    client = http_client_factory(lambda req: httpx.Response(200, json=_models_response("gpt-4o")))
    async with session_factory() as session:
        result = await fetch_model_list(session, provider.id, http_client=client)
    assert result["success"] is False
    assert "未配置 base_url" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# 连接检测
# ---------------------------------------------------------------------------


async def test_detect_key_connection(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[{"key": "sk-good-1111", "enabled": True, "priority": 1}],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == "Bearer sk-good-1111":
            return httpx.Response(200, json=_models_response("gpt-4o"))
        return httpx.Response(401, text="bad")

    client = http_client_factory(handler)
    valid = await detect_key_connection(
        provider, provider.api_keys_json[0], "sk-good-1111", http_client=client
    )
    assert valid == {"valid": True, "models": ["gpt-4o"]}

    client = http_client_factory(lambda req: httpx.Response(401, text="bad"))
    invalid = await detect_key_connection(
        provider, provider.api_keys_json[0], "sk-wrong-2222", http_client=client
    )
    assert invalid["valid"] is False
    assert "401" in invalid["error"]


async def test_detect_provider_updates_available_models(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[
            {"key": "sk-good-1111", "enabled": True, "priority": 1},
            {"key": "sk-bad-2222", "enabled": True, "priority": 2},
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == "Bearer sk-good-1111":
            return httpx.Response(200, json=_models_response("gpt-4o", "gpt-4o-mini"))
        return httpx.Response(401, text="bad")

    client = http_client_factory(handler)
    async with session_factory() as session:
        results = await detect_provider(session, provider.id, http_client=client)

    assert len(results) == 2
    good, bad = results
    assert good["valid"] is True and good["model_count"] == 2
    assert bad["valid"] is False and bad["error"]

    async with session_factory() as session:
        row = await session.get(ModelProvider, provider.id)
        by_key = {k["key_id"]: k["available_models"] for k in row.api_keys_json}
        assert by_key[provider.api_keys_json[0]["key_id"]] == ["gpt-4o", "gpt-4o-mini"]
        assert by_key[provider.api_keys_json[1]["key_id"]] == []  # 失败保留原值


async def test_detect_single_key_persists(session_factory, http_client_factory):
    provider = await _create_provider(
        session_factory,
        base_url="https://api.openai.com/v1",
        api_keys=[
            {"key": "sk-good-1111", "enabled": True, "priority": 1},
            {"key": "sk-bad-2222", "enabled": True, "priority": 2},
        ],
    )
    good_id = provider.api_keys_json[0]["key_id"]
    bad_id = provider.api_keys_json[1]["key_id"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == "Bearer sk-good-1111":
            return httpx.Response(200, json=_models_response("gpt-4o", "gpt-4o-mini"))
        return httpx.Response(401, text="bad")

    client = http_client_factory(handler)
    async with session_factory() as session:
        result = await detect_single_key(session, provider.id, good_id, http_client=client)
        assert result["valid"] is True and result["model_count"] == 2 and result["error"] is None

    # 有效 Key 的 available_models 已持久化
    async with session_factory() as session:
        row = await session.get(ModelProvider, provider.id)
        by_key = {k["key_id"]: k["available_models"] for k in row.api_keys_json}
        assert by_key[good_id] == ["gpt-4o", "gpt-4o-mini"]
        assert by_key[bad_id] == []  # 未检测 → 保留原值

    # 无效 Key：valid=False，available_models 保留原值
    async with session_factory() as session:
        result = await detect_single_key(session, provider.id, bad_id, http_client=client)
        assert result["valid"] is False and result["error"] and result["model_count"] == 0
    async with session_factory() as session:
        row = await session.get(ModelProvider, provider.id)
        by_key = {k["key_id"]: k["available_models"] for k in row.api_keys_json}
        assert by_key[bad_id] == []


async def test_detect_single_key_not_found(session_factory):
    from app.services.model_provider import ModelProviderValidationError

    provider = await _create_provider(
        session_factory, api_keys=[{"key": "sk-good-1111", "enabled": True}]
    )
    async with session_factory() as session:
        with pytest.raises(ModelProviderValidationError):
            await detect_single_key(session, provider.id, "no-such-key")


async def test_list_providers_summary_status(session_factory):
    await _create_provider(
        session_factory, api_keys=[{"key": "sk-on-1111", "enabled": True}]
    )
    off_provider = await _create_provider(
        session_factory, name="全禁用", api_keys=[{"key": "sk-off-2222", "enabled": True}]
    )
    async with session_factory() as session:
        await update_provider(
            session,
            off_provider.id,
            api_keys=[
                {"key_id": off_provider.api_keys_json[0]["key_id"],
                 "key": _mask_key("sk-off-2222"), "enabled": False}
            ],
        )
    async with session_factory() as session:
        summaries = await list_providers(session)
    by_id = {s["id"]: s for s in summaries}
    assert by_id[off_provider.id]["status"] == "no_keys"
    other = next(s for s in summaries if s["id"] != off_provider.id)
    assert other["status"] == "ready"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def test_mask_and_is_masked():
    assert _mask_key("sk-abcdefghij123456") == "sk-a...3456"
    assert _mask_key("short") == "s****"
    assert _mask_key("") == ""
    assert _is_masked_key("sk-a...3456") is True
    assert _is_masked_key("sk-real-key-0001") is False


def test_encrypt_roundtrip(tmp_data_dir):
    encrypted = encrypt_api_key("sk-secret-key")
    assert encrypted != "sk-secret-key"
    assert decrypt_api_key(encrypted) == "sk-secret-key"
