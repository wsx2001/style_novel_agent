# backend/app/services/llm/client.py
"""OpenAI-compatible 聊天客户端封装。

支持通过 base_url / api_key 动态配置任意 OpenAI-compatible 提供商
（OpenAI、DeepSeek、Kimi、Moonshot 等，参考 docs/TECH.md §1.1 / TECHv1.1.md §2.1）。
V1：调用 LLM 前统一经 apply_depth_config 解析思维深度映射参数
（docs/TECHv1.md §8），并合并用户显式参数。
V1.1：提供商/模型动态解析与多 Key 重试（docs/TECHv1.1.md §7.2）：
    - get_llm_client：从数据库加载 ModelProvider，按 select_api_key 选择 API Key，
      解密后构造 AsyncOpenAI（base_url 为空时按 provider.type 使用默认地址）；
    - chat_completion / chat_completion_stream 新增可选 provider_id / model_id：
      传入时从 DB 动态解析并支持多 Key 失败重试（模型不存在 / 认证错误自动换 Key），
      均未传入时保持向后兼容（使用 create_client 预构造的客户端；无预构造客户端则
      回退全局默认 AppConfig，未配置时抛 LLMConfigError）；
    - 每次调用记录实际使用的 provider_id / model_id / key_id 到 client.last_usage。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx
from openai import (
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session_maker
from ...models import AppConfig, ModelProvider
from ..depth_mapping import apply_depth_config
from ..model_provider import (
    GLOBAL_DEFAULT_PROVIDER_KEY,
    NoAvailableApiKey,
    select_api_key,
)

logger = logging.getLogger(__name__)

# 本地生成类请求耗时较长，设置较长的默认超时
DEFAULT_TIMEOUT = 120.0

# AppConfig 中全局默认模型的存储键（与 services/llm/resolve.py 保持一致）
GLOBAL_DEFAULT_MODEL_KEY = "global_default_model_id"

# 提供商类型 -> 默认 base_url（provider.base_url 为空时使用；docs/TECHv1.1.md §2.1）
# custom / other 无内置默认：base_url 为空时回退 openai 默认地址。
DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "opencode_go": "http://127.0.0.1:9000/v1",
}


class LLMConfigError(ValueError):
    """未配置可用的提供商 / API Key / 模型（调用方映射为 400）。"""


@dataclass
class LLMCallUsage:
    """一次 LLM 调用实际使用的提供商 / 模型 / Key（供调用方追溯）。

    provider_id / model_id 是本次调用真正生效的值（含全局默认回退后的结果）；
    key_id 是最终选中的 API Key。
    """

    provider_id: str
    model_id: str
    key_id: str


def _new_http_client() -> httpx.AsyncClient:
    """构造默认异步 HTTP 客户端（trust_env=False）。

    避免 Windows 系统代理把 127.0.0.1 / 本地自定义端点的请求转发到代理导致 502
    （见项目记忆 windows-system-proxy-breaks-localhost）；远程提供商仍可直连。
    与 services/model_provider._new_http_client 同理。
    """
    return httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, trust_env=False)


def _default_base_url(provider_type: str) -> Optional[str]:
    """按提供商类型取默认 base_url；无内置默认（custom/other）返回 None。"""
    return DEFAULT_BASE_URLS.get(provider_type)


@asynccontextmanager
async def _maybe_session(
    db: Optional[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """db 已传入则复用调用方的会话，否则新建独立会话（用后自动关闭）。"""
    if db is not None:
        yield db
    else:
        async with async_session_maker() as session:
            yield session


async def _get_global_default_model_id(db: AsyncSession) -> Optional[str]:
    """读取全局默认模型 ID（AppConfig；空串视为未配置）。"""
    value = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_MODEL_KEY)
    )
    return str(value) if value else None


async def _first_enabled_model(provider: ModelProvider) -> Optional[str]:
    """提供商未显式指定模型时，取第一个启用的模型；无则 None。"""
    for item in provider.models_json or []:
        if item.get("enabled", True):
            return item["model_id"]
    return None


def _is_retryable_llm_error(exc: Exception) -> bool:
    """判断错误是否可换 Key 重试（docs/TECHv1.1.md §7.2：模型不存在 / 认证错误）。

    - openai SDK 的 401（认证）/ 403（权限）/ 404（模型不存在）异常直接判定；
    - 部分提供商以 400 + 文本「model not found」返回：按消息关键词兜底。
    """
    if isinstance(exc, (AuthenticationError, PermissionDeniedError, NotFoundError)):
        return True
    text = str(exc).lower()
    return "model" in text and (
        "not found" in text or "does not exist" in text
    )


async def _load_provider(
    db: AsyncSession,
    provider_id: Optional[str],
) -> ModelProvider:
    """加载提供商：显式 provider_id > 全局默认提供商；未配置则抛 LLMConfigError。"""
    effective_id = provider_id
    if not effective_id:
        value = await db.scalar(
            select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_PROVIDER_KEY)
        )
        effective_id = str(value) if value else None
    if not effective_id:
        raise LLMConfigError("请先配置模型提供商")
    provider = await db.get(ModelProvider, effective_id)
    if provider is None:
        raise LLMConfigError(f"模型提供商 {effective_id} 不存在")
    return provider


async def _resolve_llm_context(
    db: AsyncSession,
    provider_id: Optional[str],
    model_id: Optional[str],
    *,
    fallback_model: Optional[str] = None,
    exclude_key_ids: Optional[set[str]] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> tuple[ModelProvider, str, str, str, AsyncOpenAI]:
    """解析提供商 + 模型，选择 API Key 并构造 AsyncOpenAI 客户端。

    模型解析顺序（docs/TECHv1.1.md §7.2）：显式 model_id > fallback_model
    （调用方默认模型）> 全局默认模型 > 提供商第一个启用的模型；全部缺失抛 LLMConfigError。

    exclude_key_ids：重试时排除已失败的 Key（调用方维护集合）；
    http_client：可选，供测试注入 MockTransport（默认 trust_env=False 的客户端）。

    返回 (provider, provider_id, model_id, key_id, client)。
    """
    provider = await _load_provider(db, provider_id)

    effective_model_id = model_id or fallback_model
    if not effective_model_id:
        effective_model_id = await _get_global_default_model_id(db)
    if not effective_model_id:
        effective_model_id = await _first_enabled_model(provider)
    if not effective_model_id:
        raise LLMConfigError("未选择模型，请先在提供商设置中添加并启用模型")

    try:
        key_obj, decrypted = select_api_key(
            provider, effective_model_id, exclude_key_ids=exclude_key_ids
        )
    except NoAvailableApiKey as exc:
        raise LLMConfigError(str(exc)) from exc

    base_url = provider.base_url or _default_base_url(provider.type) or None
    client = AsyncOpenAI(
        api_key=decrypted,
        base_url=base_url,
        timeout=DEFAULT_TIMEOUT,
        max_retries=1,
        http_client=http_client or _new_http_client(),
    )
    return provider, provider.id, effective_model_id, str(key_obj["key_id"]), client


class LLMClient:
    """异步聊天客户端：封装 chat.completions 的同步与流式调用。

    V1.1：可仅传 api_key/base_url 预构造（resolve.py 流程，向后兼容），
    也可在调用时传 provider_id/model_id 从 DB 动态解析并多 Key 重试。
    每次调用后可从 ``client.last_usage`` 读取实际使用的提供商/模型/Key。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.model = model
        self.last_usage: Optional[LLMCallUsage] = None
        self._client: Optional[AsyncOpenAI] = None
        if api_key:
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=DEFAULT_TIMEOUT,
                max_retries=1,
                http_client=http_client or _new_http_client(),
            )

    def _build_params(
        self,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        depth: Optional[str] = None,
        user_params: Optional[dict[str, Any]] = None,
        mapping: Optional[dict[str, Any]] = None,
        context_length: int = 0,
        knowledge_card_count: int = 0,
    ) -> dict[str, Any]:
        """构造最终 LLM API 参数字典。

        未指定 depth 时保持旧行为（直接使用 temperature / max_tokens）；
        指定 depth 时经 apply_depth_config 解析映射参数并与 user_params 合并。
        """
        base: dict[str, Any] = {"model": model}
        if depth is None:
            base["temperature"] = temperature
            base["max_tokens"] = max_tokens
        else:
            base.update(
                apply_depth_config(
                    depth=depth,
                    model=model,
                    user_params=user_params,
                    mapping=mapping,
                    context_length=context_length,
                    knowledge_card_count=knowledge_card_count,
                )
            )
        # max_tokens == 0 / None → 无上限：不传该参数，交由提供商默认输出上限
        # （避免 max_tokens=0 被部分 API 拒绝；映射/user_params 中的 0 同样生效）
        if base.get("max_tokens") in (0, None):
            base.pop("max_tokens", None)
        return base

    def _record_usage(self, provider_id: str, model_id: str, key_id: str) -> None:
        """记录本次调用实际使用的提供商 / 模型 / Key。"""
        self.last_usage = LLMCallUsage(
            provider_id=provider_id, model_id=model_id, key_id=key_id
        )

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 0,
        response_format: Optional[dict[str, str]] = None,
        depth: Optional[str] = None,
        user_params: Optional[dict[str, Any]] = None,
        mapping: Optional[dict[str, Any]] = None,
        context_length: int = 0,
        knowledge_card_count: int = 0,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> str:
        """非流式对话，返回完整文本内容。

        provider_id / model_id（V1.1）：传入时从数据库动态解析提供商与模型，
        并按 §7.2 多 Key 失败重试；均未传入时使用构造时预解析的客户端（resolve.py
        流程，向后兼容）；无预构造客户端则回退全局默认 AppConfig，未配置抛
        LLMConfigError。实际使用的提供商/模型/Key 记录在 self.last_usage。
        """
        if provider_id is None and model_id is None:
            if self._client is not None:
                # 兼容路径：使用预解析客户端（resolve.py 流程）
                kwargs = self._build_params(
                    model=model or self.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    depth=depth,
                    user_params=user_params,
                    mapping=mapping,
                    context_length=context_length,
                    knowledge_card_count=knowledge_card_count,
                )
                kwargs["messages"] = messages
                if response_format is not None:
                    kwargs["response_format"] = response_format
                response = await self._client.chat.completions.create(**kwargs)
                return response.choices[0].message.content or ""
            # 无预构造客户端 → 回退全局默认（AppConfig）
            async with _maybe_session(db) as session:
                return await self._chat_completion_resolved(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    depth=depth,
                    user_params=user_params,
                    mapping=mapping,
                    context_length=context_length,
                    knowledge_card_count=knowledge_card_count,
                    provider_id=None,
                    model_id=None,
                    db=session,
                    http_client=http_client,
                )
        async with _maybe_session(db) as session:
            return await self._chat_completion_resolved(
                messages,
                model=model or self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                depth=depth,
                user_params=user_params,
                mapping=mapping,
                context_length=context_length,
                knowledge_card_count=knowledge_card_count,
                provider_id=provider_id,
                model_id=model_id,
                db=session,
                http_client=http_client,
            )

    async def _chat_completion_resolved(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict[str, str]],
        depth: Optional[str],
        user_params: Optional[dict[str, Any]],
        mapping: Optional[dict[str, Any]],
        context_length: int,
        knowledge_card_count: int,
        provider_id: Optional[str],
        model_id: Optional[str],
        db: AsyncSession,
        http_client: Optional[httpx.AsyncClient],
    ) -> str:
        """动态路径：逐 Key 尝试调用，失败（模型不存在 / 认证错误）换下一个 Key。"""
        failed_key_ids: set[str] = set()
        while True:
            _provider, eff_pid, eff_mid, key_id, client = await _resolve_llm_context(
                db,
                provider_id,
                model_id,
                fallback_model=model,
                exclude_key_ids=failed_key_ids,
                http_client=http_client,
            )
            kwargs = self._build_params(
                model=eff_mid,
                temperature=temperature,
                max_tokens=max_tokens,
                depth=depth,
                user_params=user_params,
                mapping=mapping,
                context_length=context_length,
                knowledge_card_count=knowledge_card_count,
            )
            kwargs["messages"] = messages
            if response_format is not None:
                kwargs["response_format"] = response_format
            try:
                response = await client.chat.completions.create(**kwargs)
            except Exception as exc:
                if _is_retryable_llm_error(exc):
                    failed_key_ids.add(key_id)
                    logger.warning(
                        "LLM 调用失败（provider=%s model=%s key=%s），尝试下一个 Key：%s",
                        eff_pid,
                        eff_mid,
                        key_id,
                        exc,
                    )
                    continue
                raise
            self._record_usage(eff_pid, eff_mid, key_id)
            return response.choices[0].message.content or ""

    async def chat_completion_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 0,
        depth: Optional[str] = None,
        user_params: Optional[dict[str, Any]] = None,
        mapping: Optional[dict[str, Any]] = None,
        context_length: int = 0,
        knowledge_card_count: int = 0,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> AsyncIterator[str]:
        """流式对话，逐段产出增量文本（供 SSE 转发）。

        provider_id / model_id（V1.1）：与 chat_completion 相同，支持动态客户端
        与多 Key 失败重试；已产出部分内容后的中途失败无法安全换 Key，会原样抛出
        （SSE 已下发增量，无法撤回）。
        """
        if provider_id is None and model_id is None:
            if self._client is not None:
                # 兼容路径：使用预解析客户端（resolve.py 流程）
                kwargs = self._build_params(
                    model=model or self.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    depth=depth,
                    user_params=user_params,
                    mapping=mapping,
                    context_length=context_length,
                    knowledge_card_count=knowledge_card_count,
                )
                kwargs["messages"] = messages
                kwargs["stream"] = True
                stream = await self._client.chat.completions.create(**kwargs)
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
                return
            async with _maybe_session(db) as session:
                async for delta in self._chat_completion_stream_resolved(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    depth=depth,
                    user_params=user_params,
                    mapping=mapping,
                    context_length=context_length,
                    knowledge_card_count=knowledge_card_count,
                    provider_id=None,
                    model_id=None,
                    db=session,
                    http_client=http_client,
                ):
                    yield delta
                return
        async with _maybe_session(db) as session:
            async for delta in self._chat_completion_stream_resolved(
                messages,
                model=model or self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                depth=depth,
                user_params=user_params,
                mapping=mapping,
                context_length=context_length,
                knowledge_card_count=knowledge_card_count,
                provider_id=provider_id,
                model_id=model_id,
                db=session,
                http_client=http_client,
            ):
                yield delta

    async def _chat_completion_stream_resolved(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        depth: Optional[str],
        user_params: Optional[dict[str, Any]],
        mapping: Optional[dict[str, Any]],
        context_length: int,
        knowledge_card_count: int,
        provider_id: Optional[str],
        model_id: Optional[str],
        db: AsyncSession,
        http_client: Optional[httpx.AsyncClient],
    ) -> AsyncIterator[str]:
        """动态流式路径：逐 Key 尝试；未产出任何内容前的失败才换 Key 重试。"""
        failed_key_ids: set[str] = set()
        emitted = False
        while True:
            _provider, eff_pid, eff_mid, key_id, client = await _resolve_llm_context(
                db,
                provider_id,
                model_id,
                fallback_model=model,
                exclude_key_ids=failed_key_ids,
                http_client=http_client,
            )
            kwargs = self._build_params(
                model=eff_mid,
                temperature=temperature,
                max_tokens=max_tokens,
                depth=depth,
                user_params=user_params,
                mapping=mapping,
                context_length=context_length,
                knowledge_card_count=knowledge_card_count,
            )
            kwargs["messages"] = messages
            kwargs["stream"] = True
            try:
                stream = await client.chat.completions.create(**kwargs)
            except Exception as exc:
                if _is_retryable_llm_error(exc):
                    failed_key_ids.add(key_id)
                    logger.warning(
                        "流式创建失败（provider=%s model=%s key=%s），尝试下一个 Key：%s",
                        eff_pid,
                        eff_mid,
                        key_id,
                        exc,
                    )
                    continue
                raise
            self._record_usage(eff_pid, eff_mid, key_id)
            try:
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        emitted = True
                        yield delta.content
                return
            except Exception as exc:
                if emitted or not _is_retryable_llm_error(exc):
                    raise
                failed_key_ids.add(key_id)
                logger.warning(
                    "流式中断（provider=%s model=%s key=%s），尝试下一个 Key：%s",
                    eff_pid,
                    eff_mid,
                    key_id,
                    exc,
                )
                continue


def create_client(
    api_key: str, base_url: str, model: Optional[str] = None
) -> LLMClient:
    """AsyncOpenAI 客户端工厂：按解析出的提供商 Key / base_url / 模型动态构造。

    （resolve.py 流程使用；V1.1 多 Key 重试由调用时传 provider_id/model_id 触发。）
    """
    return LLMClient(api_key=api_key, base_url=base_url, model=model)


async def get_llm_client(
    provider_id: Optional[str] = None,
    model_id: Optional[str] = None,
    *,
    db: Optional[AsyncSession] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> AsyncOpenAI:
    """从数据库加载 ModelProvider，选择 API Key 并构造 AsyncOpenAI 客户端。

    - base_url 使用 provider.base_url；为空时按 provider.type 使用默认地址
      （如 openai → https://api.openai.com/v1）；
    - provider_id / model_id 未提供时回退全局默认（AppConfig，需调用方先配置）；
    - 返回原始 AsyncOpenAI（单 Key，不含重试；多 Key 重试封装在
      LLMClient.chat_completion / chat_completion_stream 中）。
    """
    async with _maybe_session(db) as session:
        _provider, _pid, _mid, _key_id, client = await _resolve_llm_context(
            session, provider_id, model_id, http_client=http_client
        )
        return client
