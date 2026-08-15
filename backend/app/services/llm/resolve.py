# backend/app/services/llm/resolve.py
"""提供商 / 模型解析服务（docs/TECHv1.1.md §7.2 / §5.2 / §5.3 / §5.4）。

在每次生成 / 对话 / 文档解析前，按 §7.2 链解析实际使用的提供商与模型：

    请求显式 provider_id/model_id
        > 会话 current_provider_id/current_model_id
        > 项目 default_provider_id/default_model_id
        > 全局默认 global_default_provider_id/global_default_model_id

解析出提供商后，用 services/model_provider.select_api_key 按
「优先级 + available_models 命中目标模型」选择启用 API Key，解密后构造
LLMClient；模型未显式指定时回退到该提供商第一个启用的模型。

- resolve_llm：生成 / 对话（需要具体模型），返回 ResolvedLLM（含客户端）；
- resolve_embedding：文档导入等仅需 Key 的场景，返回 (provider, 解密 Key)。

解析失败（无提供商 / Key / 模型）抛 NoLLMConfigError，调用方映射为 400。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppConfig, Conversation, ModelProvider, Project
from ..model_provider import (
    GLOBAL_DEFAULT_PROVIDER_KEY,
    NoAvailableApiKey,
    select_api_key,
)
from .client import LLMClient, create_client

# AppConfig 中全局默认模型的存储键（docs/TECHv1.1.md §4.6）
GLOBAL_DEFAULT_MODEL_KEY = "global_default_model_id"


class NoLLMConfigError(ValueError):
    """未配置可用的提供商 / API Key / 模型（调用方映射为 400）。"""


@dataclass
class ResolvedLLM:
    """解析结果：提供商 + 模型 + 解密 Key + 客户端。

    - provider：ORM 提供商（供生成记录 / 切换提示取 name 等）；
    - provider_id / model_id：实际使用的提供商与模型 ID；
    - api_key：解密后的明文 Key（仅进程内使用，不落库 / 不返回）；
    - client：按该 Key 构造的 LLMClient。
    """

    provider: ModelProvider
    provider_id: str
    model_id: str
    api_key: str
    client: LLMClient


async def _get_global_defaults(
    db: AsyncSession,
) -> tuple[Optional[str], Optional[str]]:
    """读取全局默认提供商与模型 ID（AppConfig；空串视为未配置）。"""
    provider_id = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_PROVIDER_KEY)
    )
    model_id = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_MODEL_KEY)
    )
    return (str(provider_id) if provider_id else None), (
        str(model_id) if model_id else None
    )


async def _resolve_provider(
    db: AsyncSession,
    *,
    project_id: Optional[str] = None,
    conversation: Optional[Conversation] = None,
    provider_id: Optional[str] = None,
) -> ModelProvider:
    """按 §7.2 链解析提供商：请求显式 > 会话当前 > 项目默认 > 全局默认。

    解析失败（未配置 / 提供商不存在）抛 NoLLMConfigError。
    """
    if not provider_id and conversation is not None:
        provider_id = conversation.current_provider_id
    if not provider_id and project_id:
        project = await db.get(Project, project_id)
        if project is not None:
            provider_id = project.default_provider_id
    if not provider_id:
        provider_id, _ = await _get_global_defaults(db)

    if not provider_id:
        raise NoLLMConfigError("请先配置模型提供商")
    provider = await db.get(ModelProvider, provider_id)
    if provider is None:
        raise NoLLMConfigError(f"模型提供商 {provider_id} 不存在")
    return provider


async def _fallback_model(provider: ModelProvider) -> Optional[str]:
    """提供商未显式指定模型时，取第一个启用的模型；无则 None。"""
    for item in provider.models_json or []:
        if item.get("enabled", True):
            return item["model_id"]
    return None


async def _resolve_model(
    db: AsyncSession,
    provider: ModelProvider,
    *,
    project_id: Optional[str] = None,
    conversation: Optional[Conversation] = None,
    model_id: Optional[str] = None,
) -> str:
    """按链解析具体模型：请求显式 > 会话当前 > 项目默认 > 全局默认 > 提供商首个启用。

    全部缺失抛 NoLLMConfigError。
    """
    if not model_id and conversation is not None:
        model_id = conversation.current_model_id
    if not model_id and project_id:
        project = await db.get(Project, project_id)
        if project is not None:
            model_id = project.default_model_id
    if not model_id:
        _, global_model_id = await _get_global_defaults(db)
        model_id = global_model_id
    if not model_id:
        model_id = await _fallback_model(provider)
    if not model_id:
        raise NoLLMConfigError("未选择模型，请先在提供商设置中添加并启用模型")
    return model_id


async def resolve_llm(
    db: AsyncSession,
    *,
    project_id: Optional[str] = None,
    conversation: Optional[Conversation] = None,
    provider_id: Optional[str] = None,
    model_id: Optional[str] = None,
) -> ResolvedLLM:
    """按 §7.2 链解析提供商与模型，选择 API Key 并构造 LLM 客户端。

    调用方应保证 project_id 与 conversation 至少提供一个；
    解析失败（无提供商 / 提供商不存在 / 无启用 Key / 无可用模型）抛 NoLLMConfigError。
    """
    provider = await _resolve_provider(
        db, project_id=project_id, conversation=conversation, provider_id=provider_id
    )
    resolved_model_id = await _resolve_model(
        db,
        provider,
        project_id=project_id,
        conversation=conversation,
        model_id=model_id,
    )

    try:
        _key_obj, decrypted = select_api_key(provider, resolved_model_id)
    except NoAvailableApiKey as exc:
        raise NoLLMConfigError(str(exc)) from exc

    client = create_client(
        api_key=decrypted,
        base_url=provider.base_url or None,
        model=resolved_model_id,
    )
    return ResolvedLLM(
        provider=provider,
        provider_id=provider.id,
        model_id=resolved_model_id,
        api_key=decrypted,
        client=client,
    )


async def resolve_embedding(
    db: AsyncSession,
    *,
    project_id: Optional[str] = None,
    conversation: Optional[Conversation] = None,
    provider_id: Optional[str] = None,
) -> tuple[ModelProvider, str]:
    """解析用于 embedding 的提供商与解密 Key（不要求目标模型，供文档导入等使用）。

    与 resolve_llm 同链解析提供商，选择优先级最高的启用 Key；
    无可用提供商 / Key 抛 NoLLMConfigError。
    """
    provider = await _resolve_provider(
        db, project_id=project_id, conversation=conversation, provider_id=provider_id
    )
    try:
        _key_obj, decrypted = select_api_key(provider, None)
    except NoAvailableApiKey as exc:
        raise NoLLMConfigError(str(exc)) from exc
    return provider, decrypted
