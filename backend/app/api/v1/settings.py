# backend/app/api/v1/settings.py
"""设置 API（docs/TECH.md §5.6）。

- GET    /api/v1/settings/keys         API Key 列表（脱敏，不暴露明文）
- POST   /api/v1/settings/keys         保存 API Key（AES-GCM 加密后存入 SQLite）
- DELETE /api/v1/settings/keys/{id}    删除 API Key
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import ApiKeyConfig
from ...schemas.settings import ApiKeyConfigCreate, ApiKeyConfigRead
from ...services.crypto.api_key import decrypt_api_key, encrypt_api_key

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
