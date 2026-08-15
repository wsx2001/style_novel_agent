# backend/app/api/v1/settings.py
"""设置 API（docs/TECH.md §5.6；V1 全局设置与深度映射，docs/TECHv1.md §5.8；
V1.1 新增全局默认提供商/模型，docs/TECHv1.1.md §5.5）。

- GET    /api/v1/settings/app          全局设置（模型配置 / 默认模板 / 默认提供商与模型）
- PATCH  /api/v1/settings/app          更新全局设置
- GET    /api/v1/settings/depth-mapping   思维深度映射配置（未配置时返回内置默认）
- PATCH  /api/v1/settings/depth-mapping   更新思维深度映射配置

V1.1 起旧 API Key 管理（/settings/keys）已迁移到 ModelProvider 提供商管理，
对应端点移除（docs/TECHv1.1.md §5.6）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import AppConfig, ModelProvider
from ...schemas.settings import (
    DepthMappingUpdate,
    GlobalAppConfigRead,
    GlobalAppConfigUpdate,
)
from ...services.depth_mapping import get_depth_mapping, save_depth_mapping
from ...services.generation import GLOBAL_DEFAULT_MODEL_CONFIG_KEY
from ...services.llm.prompts import GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY
from ...services.llm.resolve import GLOBAL_DEFAULT_MODEL_KEY
from ...services.model_provider import GLOBAL_DEFAULT_PROVIDER_KEY
from ...services.prompt_template import get_prompt_template_by_id

router = APIRouter(prefix="/api/v1", tags=["settings"])


# ===================== 全局设置与思维深度映射（docs/TECHv1.md §5.8 / §8.1） =====================


async def _get_app_config_value(
    db: AsyncSession, key: str, default: Optional[object] = None
) -> Optional[object]:
    """读取 AppConfig 键值；记录不存在时返回 default。"""
    value = await db.scalar(select(AppConfig.value).where(AppConfig.key == key))
    return value if value is not None else default


async def _read_global_settings(db: AsyncSession) -> GlobalAppConfigRead:
    """读取全局默认模型配置 / 提示词模板 / 提供商与模型。"""
    model_config = await _get_app_config_value(db, GLOBAL_DEFAULT_MODEL_CONFIG_KEY, {})
    template_id = await _get_app_config_value(db, GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY, "")
    provider_id = await _get_app_config_value(db, GLOBAL_DEFAULT_PROVIDER_KEY, "")
    model_id = await _get_app_config_value(db, GLOBAL_DEFAULT_MODEL_KEY, "")
    return GlobalAppConfigRead(
        global_default_model_config=model_config if isinstance(model_config, dict) else {},
        global_default_prompt_template_id=template_id if isinstance(template_id, str) else "",
        global_default_provider_id=provider_id if isinstance(provider_id, str) else "",
        global_default_model_id=model_id if isinstance(model_id, str) else "",
    )


async def _upsert_app_config(db: AsyncSession, key: str, value: object) -> None:
    """按 key 更新或插入 AppConfig 记录。"""
    row = await db.scalar(select(AppConfig).where(AppConfig.key == key))
    if row is None:
        db.add(AppConfig(key=key, value=value))
    else:
        row.value = value


async def _apply_global_default_provider(db: AsyncSession, provider_id: str) -> None:
    """设置/清除全局默认提供商，并同步 ModelProvider.is_default 标记（唯一全局默认）。"""
    if provider_id:
        provider = await db.get(ModelProvider, provider_id)
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"模型提供商 {provider_id} 不存在",
            )
        await db.execute(
            update(ModelProvider)
            .where(ModelProvider.is_default.is_(True))
            .values(is_default=False)
        )
        provider.is_default = True
    else:
        await db.execute(
            update(ModelProvider)
            .where(ModelProvider.is_default.is_(True))
            .values(is_default=False)
        )


@router.get(
    "/settings/app",
    response_model=GlobalAppConfigRead,
    summary="全局设置（模型配置 / 默认模板 / 默认提供商与模型）",
)
async def get_global_settings(db: AsyncSession = Depends(get_db)):
    """读取全局默认模型配置、默认提示词模板与默认提供商/模型（docs/TECHv1.md §5.8）。"""
    return await _read_global_settings(db)


@router.patch(
    "/settings/app",
    response_model=GlobalAppConfigRead,
    summary="更新全局设置",
)
async def update_global_settings(
    payload: GlobalAppConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新全局默认模型配置 / 默认提示词模板 / 默认提供商与模型（仅显式传入的字段）。

    设置全局默认提供商时校验其存在，并同步 ModelProvider.is_default 标记。
    """
    updates = payload.model_dump(exclude_unset=True)
    if "global_default_model_config" in updates:
        val = updates["global_default_model_config"]
        updates["global_default_model_config"] = val if isinstance(val, dict) else {}
    if "global_default_prompt_template_id" in updates:
        template_id = updates["global_default_prompt_template_id"] or ""
        if template_id:
            template = await get_prompt_template_by_id(db, template_id)
            if template is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"提示词模板 {template_id} 不存在",
                )
        updates["global_default_prompt_template_id"] = template_id
    if "global_default_provider_id" in updates:
        provider_id = updates["global_default_provider_id"] or ""
        await _apply_global_default_provider(db, provider_id)
        updates["global_default_provider_id"] = provider_id
    for key, value in updates.items():
        await _upsert_app_config(db, key, value)
    await db.commit()
    return await _read_global_settings(db)


@router.get(
    "/settings/depth-mapping",
    response_model=dict,
    summary="思维深度映射配置（未配置时返回内置默认）",
)
async def get_depth_mapping_config(db: AsyncSession = Depends(get_db)):
    """读取全局思维深度映射配置；未配置或值损坏时返回系统内置默认映射（docs/TECHv1.md §8.1）。"""
    return await get_depth_mapping(db)


@router.patch(
    "/settings/depth-mapping",
    response_model=dict,
    summary="更新思维深度映射配置",
)
async def update_depth_mapping_config(
    payload: DepthMappingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """partial update 合并更新思维深度映射（省略的字段保留既有值）。"""
    current = await get_depth_mapping(db)
    if not isinstance(current, dict):
        current = {}
    updates = payload.model_dump(exclude_unset=True)
    if "default" in updates:
        current["default"] = updates["default"]
    if "model_overrides" in updates:
        current["model_overrides"] = updates["model_overrides"]
    await save_depth_mapping(db, current)
    return current
