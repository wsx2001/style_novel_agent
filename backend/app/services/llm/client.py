# backend/app/services/llm/client.py
"""OpenAI-compatible 聊天客户端封装。

支持通过 base_url / api_key 动态配置任意 OpenAI-compatible 提供商
（OpenAI、DeepSeek、Kimi、Moonshot 等，参考 docs/TECH.md §1.1）。
V1：调用 LLM 前统一经 apply_depth_config 解析思维深度映射参数
（docs/TECHv1.md §8），并合并用户显式参数。
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from openai import AsyncOpenAI

from ..depth_mapping import apply_depth_config

# 本地生成类请求耗时较长，设置较长的默认超时
DEFAULT_TIMEOUT = 120.0


class LLMClient:
    """异步聊天客户端：封装 chat.completions 的同步与流式调用。"""

    def __init__(self, api_key: str, base_url: str, model: Optional[str] = None) -> None:
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=DEFAULT_TIMEOUT,
            max_retries=1,
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
        return base

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: Optional[dict[str, str]] = None,
        depth: Optional[str] = None,
        user_params: Optional[dict[str, Any]] = None,
        mapping: Optional[dict[str, Any]] = None,
        context_length: int = 0,
        knowledge_card_count: int = 0,
    ) -> str:
        """非流式对话，返回完整文本内容。"""
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

    async def chat_completion_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        depth: Optional[str] = None,
        user_params: Optional[dict[str, Any]] = None,
        mapping: Optional[dict[str, Any]] = None,
        context_length: int = 0,
        knowledge_card_count: int = 0,
    ) -> AsyncIterator[str]:
        """流式对话，逐段产出增量文本（供 SSE 转发）。"""
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


def create_client(
    api_key: str, base_url: str, model: Optional[str] = None
) -> LLMClient:
    """AsyncOpenAI 客户端工厂：按 ApiKeyConfig 动态构造。"""
    return LLMClient(api_key=api_key, base_url=base_url, model=model)
