# backend/app/api/v1/settings.py
"""设置 API（docs/TECH.md §5.6；V1 全局设置与深度映射，docs/TECHv1.md §5.8）。

- GET    /api/v1/settings/keys         API Key 列表（脱敏，不暴露明文）
- POST   /api/v1/settings/keys         保存 API Key（AES-GCM 加密后存入 SQLite）
- DELETE /api/v1/settings/keys/{id}    删除 API Key
- GET    /api/v1/settings/app          全局设置（global_default_model_config / global_default_prompt_template_id）
- PATCH  /api/v1/settings/app          更新全局设置
- GET    /api/v1/settings/depth-mapping   思维深度映射配置（未配置时返回内置默认）
- PATCH  /api/v1/settings/depth-mapping   更新思维深度映射配置
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import ApiKeyConfig, AppConfig
from ...schemas.settings import (
    ApiKeyConfigCreate,
    ApiKeyConfigRead,
    DepthMappingUpdate,
    GlobalAppConfigRead,
    GlobalAppConfigUpdate,
)
from ...services.crypto.api_key import decrypt_api_key, encrypt_api_key
from ...services.depth_mapping import get_depth_mapping, save_depth_mapping
from ...services.generation import GLOBAL_DEFAULT_MODEL_CONFIG_KEY
from ...services.llm.prompts import GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY
from ...services.prompt_template import get_prompt_template_by_id

router = APIRouter(prefix="/api/v1", tags=["settings"])


def _mask_api_key(encrypted: str) -> str:
    """解密后脱敏：保留前 3 位与后 4 位（解密失败时退化为 ***）。"""
    try:
        key = decrypt_api_key(encrypted)
    except Exception:
        return "***"
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}***{key[-4:]}"


async def _get_key_or_404(key_id: str, db: AsyncSession) -> ApiKeyConfig:
    """按 id 查询 API Key 配置，不存在则抛 404。"""
    config = await db.get(ApiKeyConfig, key_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API Key 配置 {key_id} 不存在",
        )
    return config


def _to_read(config: ApiKeyConfig) -> ApiKeyConfigRead:
    """将 ORM 模型转为脱敏响应体。"""
    return ApiKeyConfigRead(
        id=config.id,
        provider=config.provider,
        name=config.name,
        key_masked=_mask_api_key(config.encrypted_key),
        base_url=config.base_url,
        model=config.model,
        is_default=config.is_default,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get(
    "/settings/keys",
    response_model=list[ApiKeyConfigRead],
    summary="API Key 列表（脱敏）",
)
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyConfigRead]:
    result = await db.execute(
        select(ApiKeyConfig).order_by(
            ApiKeyConfig.is_default.desc(), ApiKeyConfig.created_at
        )
    )
    return [_to_read(config) for config in result.scalars().all()]


@router.post(
    "/settings/keys",
    response_model=ApiKeyConfigRead,
    status_code=status.HTTP_201_CREATED,
    summary="保存 API Key（加密存储）",
)
async def save_api_key(
    payload: ApiKeyConfigCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyConfigRead:
    # 设为默认时，清除其它默认标记
    if payload.is_default:
        await db.execute(
            ApiKeyConfig.__table__.update().where(
                ApiKeyConfig.is_default.is_(True)
            ).values(is_default=False)
        )
    config = ApiKeyConfig(
        provider=payload.provider,
        name=payload.name,
        encrypted_key=encrypt_api_key(payload.api_key),
        base_url=payload.base_url,
        model=payload.model,
        is_default=payload.is_default,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return _to_read(config)


@router.delete(
    "/settings/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 API Key",
)
async def delete_api_key(key_id: str, db: AsyncSession = Depends(get_db)) -> None:
    config = await _get_key_or_404(key_id, db)
    await db.delete(config)
    await db.commit()


# ===================== 全局设置与思维深度映射（docs/TECHv1.md §5.8 / §8.1） =====================


async def _get_app_config_value(
    db: AsyncSession, key: str, default: Optional[object] = None
) -> Optional[object]:
    """读取 AppConfig 键值；记录不存在时返回 default。"""
    value = await db.scalar(select(AppConfig.value).where(AppConfig.key == key))
    return value if value is not None else default


async def _read_global_settings(db: AsyncSession) -> GlobalAppConfigRead:
    """读取全局默认模型配置与全局默认提示词模板。"""
    model_config = await _get_app_config_value(db, GLOBAL_DEFAULT_MODEL_CONFIG_KEY, {})
    template_id = await _get_app_config_value(db, GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY, "")
    return GlobalAppConfigRead(
        global_default_model_config=model_config if isinstance(model_config, dict) else {},
        global_default_prompt_template_id=template_id if isinstance(template_id, str) else "",
    )


async def _upsert_app_config(db: AsyncSession, key: str, value: object) -> None:
    """按 key 更新或插入 AppConfig 记录。"""
    row = await db.scalar(select(AppConfig).where(AppConfig.key == key))
    if row is None:
        db.add(AppConfig(key=key, value=value))
    else:
        row.value = value


@router.get(
    "/settings/app",
    response_model=GlobalAppConfigRead,
    summary="全局设置（global_default_model_config / global_default_prompt_template_id）",
)
async def get_global_settings(db: AsyncSession = Depends(get_db)):
    """读取全局默认模型配置与全局默认提示词模板（docs/TECHv1.md §5.8）。"""
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
    """更新全局默认模型配置与全局默认提示词模板（仅显式传入的字段）。"""
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
