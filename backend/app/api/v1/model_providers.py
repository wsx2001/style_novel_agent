# backend/app/api/v1/model_providers.py
"""模型提供商管理 API（docs/TECHv1.1.md §5.1 / PRD v1.1 §2.1）。

端点：
- GET    /api/v1/model-providers                          提供商列表摘要
- POST   /api/v1/model-providers                          创建提供商（默认自动获取模型列表）
- GET    /api/v1/model-providers/{provider_id}            提供商详情（api_keys 脱敏）
- PATCH  /api/v1/model-providers/{provider_id}            更新提供商（名称/base_url/api_keys/models）
- DELETE /api/v1/model-providers/{provider_id}            删除提供商（解除项目/会话引用）
- POST   /api/v1/model-providers/{provider_id}/fetch-models  触发获取模型列表
- POST   /api/v1/model-providers/{provider_id}/detect     检测所有 Key 连接状态
- POST   /api/v1/model-providers/{provider_id}/keys/{key_id}/detect  检测单个 Key

错误处理：提供商 / Key 不存在 → 404；参数不合法（空名称 / 非法 type / 新增 Key 缺明文）→ 400。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import ModelProvider
from ...schemas.model_provider import (
    KeyDetectResult,
    ModelFetchResult,
    ModelProviderCreate,
    ModelProviderCreateResponse,
    ModelProviderRead,
    ModelProviderUpdate,
    ProviderSummary,
)
from ...services import model_provider as model_provider_service
from ...services.model_provider import (
    ModelProviderNotFound,
    ModelProviderValidationError,
)

router = APIRouter(prefix="/api/v1", tags=["model_providers"])

# 创建成功后自动获取模型列表失败时的提示文案（PRD v1.1 §2.1）
AUTO_FETCH_FAIL_MESSAGE = "未获取到模型"


async def _get_provider_or_404(db: AsyncSession, provider_id: str) -> ModelProvider:
    """按 id 查询提供商，不存在则抛 404。"""
    provider = await db.get(ModelProvider, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"模型提供商 {provider_id} 不存在",
        )
    return provider


@router.get(
    "/model-providers",
    response_model=list[ProviderSummary],
    summary="提供商列表摘要（id/name/type/key_count/model_count/is_default/status）",
)
async def list_model_providers(db: AsyncSession = Depends(get_db)) -> list:
    """列出所有提供商摘要，不含任何 Key 信息（明文或密文）。"""
    return await model_provider_service.list_providers(db)


@router.post(
    "/model-providers",
    response_model=ModelProviderCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建提供商（默认自动获取模型列表）",
)
async def create_model_provider(
    payload: ModelProviderCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建提供商并加密各 API Key；成功后自动获取模型列表。

    获取失败不阻断创建：provider 返回成功但 models 为空，并附带 message「未获取到模型」。
    """
    try:
        provider = await model_provider_service.create_provider(
            db,
            name=payload.name,
            type=payload.type,
            base_url=payload.base_url,
            api_keys=[key.model_dump() for key in payload.api_keys],
        )
    except ModelProviderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    response: dict = {}
    if payload.auto_fetch:
        result = await model_provider_service.fetch_model_list(db, provider.id)
        response["auto_fetch"] = result
        if not result["success"]:
            response["message"] = AUTO_FETCH_FAIL_MESSAGE
    # 详情必须在 fetch 之后取，保证 models / available_models 反映最新结果
    response["provider"] = await model_provider_service.get_provider(db, provider.id)
    return response


@router.get(
    "/model-providers/{provider_id}",
    response_model=ModelProviderRead,
    summary="提供商详情（api_keys 脱敏）",
)
async def get_model_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await model_provider_service.get_provider(db, provider_id)
    except ModelProviderNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch(
    "/model-providers/{provider_id}",
    response_model=ModelProviderRead,
    summary="更新提供商（名称/base_url/api_keys/models）",
)
async def update_model_provider(
    provider_id: str,
    payload: ModelProviderUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """仅更新显式传入的字段；api_keys / models 为一次全量替换。"""
    await _get_provider_or_404(db, provider_id)
    # model_dump 已把嵌套的 ApiKeyInput / ModelItem 转为 dict，直接透传给服务层
    updates = payload.model_dump(exclude_unset=True)
    try:
        await model_provider_service.update_provider(db, provider_id, **updates)
    except ModelProviderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return await model_provider_service.get_provider(db, provider_id)


@router.delete(
    "/model-providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除提供商（解除项目/会话引用）",
)
async def delete_model_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除提供商：服务层先解除项目 / 会话 / 生成记录引用并清空全局默认，再删除本身。"""
    try:
        await model_provider_service.delete_provider(db, provider_id)
    except ModelProviderNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/model-providers/{provider_id}/fetch-models",
    response_model=ModelFetchResult,
    summary="获取模型列表（合并去重所有启用 Key）",
)
async def fetch_models(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """使用所有启用 Key 请求 /models，合并去重并持久化到提供商与各 Key。"""
    try:
        return await model_provider_service.fetch_model_list(db, provider_id)
    except ModelProviderNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/model-providers/{provider_id}/detect",
    response_model=list[KeyDetectResult],
    summary="检测所有 Key 连接状态",
)
async def detect_provider_keys(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
) -> list:
    """逐个检测所有 Key 的连接状态，并刷新成功 Key 的模型列表。"""
    try:
        return await model_provider_service.detect_provider(db, provider_id)
    except ModelProviderNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/model-providers/{provider_id}/keys/{key_id}/detect",
    response_model=KeyDetectResult,
    summary="检测单个 Key 连接状态",
)
async def detect_single_key(
    provider_id: str,
    key_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """检测单个 Key 的有效性并刷新其模型列表；Key 不存在 → 404。"""
    provider = await _get_provider_or_404(db, provider_id)
    if not any(k.get("key_id") == key_id for k in provider.api_keys_json or []):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API Key {key_id} 不存在",
        )
    return await model_provider_service.detect_single_key(db, provider_id, key_id)
