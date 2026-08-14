# backend/app/services/llm/client.py
"""OpenAI-compatible 聊天客户端封装。

支持通过 base_url / api_key 动态配置任意 OpenAI-compatible 提供商
（OpenAI、DeepSeek、Kimi、Moonshot 等，参考 docs/TECH.md §1.1）。
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from openai import AsyncOpenAI

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

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: Optional[dict[str, str]] = None,
    ) -> str:
        """非流式对话，返回完整文本内容。"""
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
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
    ) -> AsyncIterator[str]:
        """流式对话，逐段产出增量文本（供 SSE 转发）。"""
        stream = await self._client.chat.completions.create(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
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
