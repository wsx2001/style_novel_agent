# backend/tests/test_llm_client.py
"""LLM 客户端动态解析与多 Key 重试测试（docs/TECHv1.1.md §7.2）。

覆盖：
- get_llm_client：从 DB 加载提供商、select_api_key 选择 Key、base_url 按类型回退；
- chat_completion 动态解析：显式 provider_id/model_id 选择 Key 并调用、记录 last_usage；
- 多 Key 重试：认证错误 / 模型不存在自动换下一个 Key；全部失败抛 LLMConfigError；
- 流式：动态客户端 + 未产出内容前的换 Key 重试；
- 兼容性：预构造客户端（create_client）不传 provider_id/model_id 保持旧行为；
- 全局默认回退：无预构造客户端时从 AppConfig 读取全局默认；未配置抛 LLMConfigError。

网络全部走 httpx.MockTransport，不发起真实请求。
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.models import AppConfig
from app.services.llm.client import LLMClient, LLMConfigError, create_client, get_llm_client
from app.services.model_provider import create_provider, update_provider

pytestmark = pytest.mark.anyio

MESSAGES = [{"role": "user", "content": "你好"}]


# ---------------------------------------------------------------------------
# 构造辅助
# ---------------------------------------------------------------------------


def _completion_json(text: str = "hello") -> dict:
    """OpenAI 兼容的非流式补全响应体。"""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }


def _stream_content(*chunks: str) -> bytes:
    """构造 SSE 流式响应体（data: {chunk} / data: [DONE]）。"""
    lines = []
    for chunk in chunks:
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-4o",
            "choices": [
                {"index": 0, "delta": {"content": chunk}, "finish_reason": None}
            ],
        }
        lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def _auth_handler(auth_map: dict[str, httpx.Response]):
    """按 Authorization 头分发响应的 handler；未知 Key → 401。"""

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        resp = auth_map.get(auth)
        if resp is not None:
            return resp
        return httpx.Response(
            401, json={"error": {"message": "invalid api key", "type": "auth"}}
        )

    return handler


def _transport(auth_map: dict[str, httpx.Response]) -> httpx.AsyncClient:
    """构造带 MockTransport 的 httpx 客户端（模拟远端 /chat/completions）。"""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(_auth_handler(auth_map)), trust_env=False
    )


async def _provider_two_keys(
    session_factory,
    *,
    base_url: str | None = "http://127.0.0.1:9000/v1",
    type: str = "openai",
    key1_models: list[str] | None = None,
    key2_models: list[str] | None = None,
):
    """创建带两个启用 Key 的提供商；默认 key1 支持 gpt-4o、key2 支持 gpt-4o-mini。

    同时写入 provider.models_json（与 Key 模型一致，供「取第一个启用模型」回退）。
    """
    key1_models = key1_models if key1_models is not None else ["gpt-4o"]
    key2_models = key2_models if key2_models is not None else ["gpt-4o-mini"]
    merged_models = list(dict.fromkeys([*key1_models, *key2_models]))
    async with session_factory() as session:
        provider = await create_provider(
            session,
            name="测试提供商",
            type=type,
            base_url=base_url,
            api_keys=[
                {"key": "sk-key1-1111", "enabled": True, "priority": 1},
                {"key": "sk-key2-2222", "enabled": True, "priority": 2},
            ],
        )
        key1_id = provider.api_keys_json[0]["key_id"]
        key2_id = provider.api_keys_json[1]["key_id"]
        return await update_provider(
            session,
            provider.id,
            api_keys=[
                {
                    "key_id": key1_id,
                    "key": "sk-key1-1111",
                    "enabled": True,
                    "priority": 1,
                    "available_models": key1_models,
                },
                {
                    "key_id": key2_id,
                    "key": "sk-key2-2222",
                    "enabled": True,
                    "priority": 2,
                    "available_models": key2_models,
                },
            ],
            models=[
                {"model_id": mid, "enabled": True} for mid in merged_models
            ],
        )


# ---------------------------------------------------------------------------
# get_llm_client：Key 选择与 base_url 回退
# ---------------------------------------------------------------------------


async def test_get_llm_client_base_url_fallback_and_key_selection(session_factory):
    # type=openai 且不配 base_url → 回退 https://api.openai.com/v1
    provider = await _provider_two_keys(session_factory, base_url=None, type="openai")
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("Authorization", "")))
        return httpx.Response(200, json=_completion_json("ok"))

    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    async with session_factory() as session:
        client = await get_llm_client(provider.id, "gpt-4o", db=session, http_client=transport)
        response = await client.chat.completions.create(model="gpt-4o", messages=MESSAGES)

    assert response.choices[0].message.content == "ok"
    url, auth = seen[0]
    assert url == "https://api.openai.com/v1/chat/completions"
    # gpt-4o 仅 key1 支持 → 选中 key1
    assert auth == "Bearer sk-key1-1111"


async def test_get_llm_client_selects_key_matching_model(session_factory):
    provider = await _provider_two_keys(
        session_factory, base_url="http://127.0.0.1:9000/v1"
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json=_completion_json("ok"))

    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    async with session_factory() as session:
        # gpt-4o-mini 仅 key2 支持 → 选中 key2
        client = await get_llm_client(provider.id, "gpt-4o-mini", db=session, http_client=transport)
        await client.chat.completions.create(model="gpt-4o-mini", messages=MESSAGES)

    assert seen == ["Bearer sk-key2-2222"]


# ---------------------------------------------------------------------------
# chat_completion：动态解析、用量记录、多 Key 重试
# ---------------------------------------------------------------------------


async def test_chat_completion_dynamic_selects_key_and_records_usage(session_factory):
    provider = await _provider_two_keys(
        session_factory, base_url="http://127.0.0.1:9000/v1"
    )
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("Authorization", "")))
        return httpx.Response(200, json=_completion_json("from-key1"))

    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    client = LLMClient()
    async with session_factory() as session:
        content = await client.chat_completion(
            MESSAGES,
            provider_id=provider.id,
            model_id="gpt-4o",
            db=session,
            http_client=transport,
        )

    assert content == "from-key1"
    url, auth = seen[0]
    assert url == "http://127.0.0.1:9000/v1/chat/completions"  # 显式 base_url 优先
    assert auth == "Bearer sk-key1-1111"
    # 实际使用的提供商/模型/Key 已记录
    assert client.last_usage is not None
    assert client.last_usage.provider_id == provider.id
    assert client.last_usage.model_id == "gpt-4o"
    assert client.last_usage.key_id == provider.api_keys_json[0]["key_id"]


async def test_chat_completion_retries_next_key_on_auth_error(session_factory):
    # 两个 Key 都声明支持 gpt-4o：key1 认证失败 → 自动换 key2
    provider = await _provider_two_keys(
        session_factory,
        key1_models=["gpt-4o"],
        key2_models=["gpt-4o"],
    )
    transport = _transport(
        {
            "Bearer sk-key1-1111": httpx.Response(
                401, json={"error": {"message": "Invalid API key"}}
            ),
            "Bearer sk-key2-2222": httpx.Response(200, json=_completion_json("from-key2")),
        }
    )
    client = LLMClient()
    async with session_factory() as session:
        content = await client.chat_completion(
            MESSAGES,
            provider_id=provider.id,
            model_id="gpt-4o",
            db=session,
            http_client=transport,
        )

    assert content == "from-key2"
    assert client.last_usage is not None
    assert client.last_usage.key_id == provider.api_keys_json[1]["key_id"]


async def test_chat_completion_retries_next_key_on_model_not_found(session_factory):
    # available_models 过时：key1 声明支持但实际 404 → 换 key2（docs/TECHv1.1.md §7.2）
    provider = await _provider_two_keys(
        session_factory,
        key1_models=["gpt-4o"],
        key2_models=["gpt-4o"],
    )
    transport = _transport(
        {
            "Bearer sk-key1-1111": httpx.Response(
                404,
                json={
                    "error": {
                        "message": "The model `gpt-4o` does not exist",
                        "type": "invalid_request_error",
                    }
                },
            ),
            "Bearer sk-key2-2222": httpx.Response(200, json=_completion_json("ok")),
        }
    )
    client = LLMClient()
    async with session_factory() as session:
        content = await client.chat_completion(
            MESSAGES,
            provider_id=provider.id,
            model_id="gpt-4o",
            db=session,
            http_client=transport,
        )

    assert content == "ok"
    assert client.last_usage is not None
    assert client.last_usage.key_id == provider.api_keys_json[1]["key_id"]


async def test_chat_completion_all_keys_fail_raises(session_factory):
    provider = await _provider_two_keys(session_factory)
    transport = _transport(
        {
            "Bearer sk-key1-1111": httpx.Response(401, json={"error": {"message": "bad"}}),
            "Bearer sk-key2-2222": httpx.Response(401, json={"error": {"message": "bad"}}),
        }
    )
    client = LLMClient()
    async with session_factory() as session:
        with pytest.raises(LLMConfigError):
            await client.chat_completion(
                MESSAGES,
                provider_id=provider.id,
                model_id="gpt-4o",
                db=session,
                http_client=transport,
            )


async def test_chat_completion_model_from_provider_first_enabled(session_factory):
    # 不传 model_id → 用提供商第一个启用的模型（gpt-4o）
    provider = await _provider_two_keys(session_factory)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json=_completion_json("ok"))

    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    client = LLMClient()
    async with session_factory() as session:
        content = await client.chat_completion(
            MESSAGES, provider_id=provider.id, db=session, http_client=transport
        )

    assert content == "ok"
    assert seen == ["Bearer sk-key1-1111"]  # gpt-4o → key1
    assert client.last_usage is not None
    assert client.last_usage.model_id == "gpt-4o"


# ---------------------------------------------------------------------------
# 流式：动态客户端 + 换 Key 重试
# ---------------------------------------------------------------------------


async def test_chat_completion_stream_dynamic_and_retry(session_factory):
    provider = await _provider_two_keys(
        session_factory,
        key1_models=["gpt-4o"],
        key2_models=["gpt-4o"],
    )
    transport = _transport(
        {
            "Bearer sk-key1-1111": httpx.Response(
                401, json={"error": {"message": "bad"}}
            ),
            "Bearer sk-key2-2222": httpx.Response(
                200,
                content=_stream_content("hi", " there"),
                headers={"content-type": "text/event-stream"},
            ),
        }
    )
    client = LLMClient()
    parts: list[str] = []
    async with session_factory() as session:
        async for delta in client.chat_completion_stream(
            MESSAGES,
            provider_id=provider.id,
            model_id="gpt-4o",
            db=session,
            http_client=transport,
        ):
            parts.append(delta)

    assert "".join(parts) == "hi there"
    assert client.last_usage is not None
    assert client.last_usage.key_id == provider.api_keys_json[1]["key_id"]


async def test_chat_completion_stream_dynamic_first_key_ok(session_factory):
    provider = await _provider_two_keys(session_factory)
    transport = _transport(
        {
            "Bearer sk-key1-1111": httpx.Response(
                200,
                content=_stream_content("hello", " world"),
                headers={"content-type": "text/event-stream"},
            )
        }
    )
    client = LLMClient()
    parts: list[str] = []
    async with session_factory() as session:
        async for delta in client.chat_completion_stream(
            MESSAGES,
            provider_id=provider.id,
            model_id="gpt-4o",
            db=session,
            http_client=transport,
        ):
            parts.append(delta)

    assert "".join(parts) == "hello world"
    assert client.last_usage is not None
    assert client.last_usage.key_id == provider.api_keys_json[0]["key_id"]


# ---------------------------------------------------------------------------
# 兼容性：预构造客户端（resolve.py 流程）
# ---------------------------------------------------------------------------


async def test_create_client_builds_prebuilt_client():
    client = create_client("sk-legacy-0000", "http://127.0.0.1:9000/v1", model="gpt-4o")
    assert isinstance(client, LLMClient)
    assert client.model == "gpt-4o"
    assert client._client is not None  # 预构造的 AsyncOpenAI
    assert client.last_usage is None


async def test_chat_completion_legacy_uses_prebuilt_client():
    """不传 provider_id/model_id → 直接使用构造时预解析的客户端（向后兼容）。"""
    transport = _transport(
        {
            "Bearer sk-legacy-0000": httpx.Response(200, json=_completion_json("legacy"))
        }
    )
    client = LLMClient(
        api_key="sk-legacy-0000",
        base_url="http://127.0.0.1:9000/v1",
        model="gpt-4o",
        http_client=transport,
    )
    content = await client.chat_completion(MESSAGES, model="gpt-4o")
    assert content == "legacy"


async def test_chat_completion_stream_legacy_uses_prebuilt_client(session_factory):
    transport = _transport(
        {
            "Bearer sk-legacy-0000": httpx.Response(
                200,
                content=_stream_content("stream"),
                headers={"content-type": "text/event-stream"},
            )
        }
    )
    client = LLMClient(
        api_key="sk-legacy-0000",
        base_url="http://127.0.0.1:9000/v1",
        model="gpt-4o",
        http_client=transport,
    )
    parts: list[str] = []
    async for delta in client.chat_completion_stream(MESSAGES, model="gpt-4o"):
        parts.append(delta)
    assert "".join(parts) == "stream"


# ---------------------------------------------------------------------------
# 全局默认回退与未配置报错
# ---------------------------------------------------------------------------


async def test_chat_completion_fallback_to_global_default(session_factory):
    provider = await _provider_two_keys(session_factory)
    async with session_factory() as session:
        session.add(AppConfig(key="global_default_provider_id", value=provider.id))
        session.add(AppConfig(key="global_default_model_id", value="gpt-4o"))
        await session.commit()

    transport = _transport(
        {
            "Bearer sk-key1-1111": httpx.Response(200, json=_completion_json("default-ok")),
            "Bearer sk-key2-2222": httpx.Response(200, json=_completion_json("x")),
        }
    )
    client = LLMClient()  # 无预构造客户端
    async with session_factory() as session:
        content = await client.chat_completion(MESSAGES, db=session, http_client=transport)

    assert content == "default-ok"
    assert client.last_usage is not None
    assert client.last_usage.provider_id == provider.id
    assert client.last_usage.model_id == "gpt-4o"


async def test_chat_completion_no_config_raises(session_factory):
    client = LLMClient()
    async with session_factory() as session:
        with pytest.raises(LLMConfigError) as excinfo:
            await client.chat_completion(MESSAGES, db=session)
    assert "请先配置模型提供商" in str(excinfo.value)


async def test_get_llm_client_no_provider_raises(session_factory):
    async with session_factory() as session:
        with pytest.raises(LLMConfigError):
            await get_llm_client("no-such-provider", "gpt-4o", db=session)
