# backend/app/api/v1/llm_deps.py
"""LLM 客户端解析公共依赖（generations / conversations 共享）。

- find_api_key_config：按项目查找可用的 API Key 配置
  （项目级默认 > 项目级任意 > 全局默认 > 全局任意）；
- resolve_client：解密 API Key 并构造 LLM 客户端
  （解密失败 → 500，未配置模型 → 400）。
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ApiKeyConfig
from ...services.crypto.api_key import decrypt_api_key
from ...services.llm.client import LLMClient, create_client


async def find_api_key_config(
    db: AsyncSession, project_id: str
) -> ApiKeyConfig | None:
    """查找可用的 API Key 配置：优先项目级默认，其次项目级任意，再回退全局。"""
    scoped = await db.execute(
        select(ApiKeyConfig)
        .where(ApiKeyConfig.project_id == project_id)
        .order_by(ApiKeyConfig.is_default.desc(), ApiKeyConfig.created_at)
    )
    config = scoped.scalars().first()
    if config is not None:
        return config
    global_result = await db.execute(
        select(ApiKeyConfig)
        .where(ApiKeyConfig.project_id.is_(None))
        .order_by(ApiKeyConfig.is_default.desc(), ApiKeyConfig.created_at)
    )
    return global_result.scalars().first()


def resolve_client(config: ApiKeyConfig) -> tuple[str, LLMClient]:
    """解密 API Key 并构造 LLM 客户端（解密失败 → 500，未配模型 → 400）。"""
    try:
        api_key = decrypt_api_key(config.encrypted_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"API Key 解密失败：{exc}",
        ) from exc
    if not config.model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API Key 未配置模型，请在设置中补全 model 字段",
        )
    return api_key, create_client(
        api_key=api_key, base_url=config.base_url, model=config.model
    )
