# backend/app/services/model_provider.py
"""模型提供商服务层（docs/TECHv1.1.md §4.2 / §5.1 / §7.2）。

职责：
- 提供商 CRUD：API Key 使用 services/crypto/api_key.py 加密存储（AES-256-GCM），
  响应层一律脱敏，不返回密文或明文。
- 模型列表获取：使用所有启用的 Key 请求 OpenAI 兼容的 ``/models`` 端点（或自定义
  base_url 下的同构端点），合并去重后写入 provider.models_json 与各 Key 的
  available_models。
- 多 Key 选择：``select_api_key`` 按「优先级 + available_models 命中目标模型」选取，
  供 LLM 客户端在生成/对话前调用。

数据格式（与模型 docstring 一致）：
    api_keys_json: [{key_id, api_key_encrypted, enabled, priority, available_models}, ...]
    models_json:   [{model_id, enabled}, ...]
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AppConfig, Conversation, GenerationRecord, ModelProvider, Project
from .crypto.api_key import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

# 提供商类型枚举（docs/TECHv1.1.md §4.2）
MODEL_PROVIDER_TYPES = (
    "openai",
    "anthropic",
    "deepseek",
    "kimi",
    "opencode_go",
    "custom",
    "other",
)

# AppConfig 中全局默认提供商 ID 的键
GLOBAL_DEFAULT_PROVIDER_KEY = "global_default_provider_id"

# /models 请求超时（秒）；本机自定义端点与远程提供商均适用
DEFAULT_TIMEOUT = 20.0

# 未提供优先级时的默认值（数值越小优先级越高）
DEFAULT_PRIORITY = 1


class ModelProviderNotFound(Exception):
    """提供商不存在。"""


class ModelProviderValidationError(ValueError):
    """提供商参数不合法（名称 / type / api_keys 等）。"""


class NoAvailableApiKey(Exception):
    """提供商没有可用的（启用的）API Key。"""


def _new_key_id() -> str:
    """生成 API Key 记录的唯一 key_id（形如 key_xxxxxxxx）。"""
    return f"key_{uuid4().hex[:8]}"


def _mask_key(plaintext: str) -> str:
    """脱敏：只显示首尾几位（前端回传时据此识别未改动的 Key）。"""
    if not plaintext:
        return ""
    if len(plaintext) <= 8:
        return f"{plaintext[0]}****"
    return f"{plaintext[:4]}...{plaintext[-4:]}"


def _is_masked_key(value: str) -> bool:
    """判断前端提交的 key 是否为脱敏占位符（未改动 → 应复用旧密文）。

    真实 API Key 由字母数字构成，不含 ``*`` 或 ``...``，因此可安全识别。
    """
    return "*" in value or "..." in value


def _build_models_url(base_url: str) -> str:
    """拼接 OpenAI 兼容的 /models 端点地址。

    base_url 以 /v1 结尾时按 ``{base_url}/models``（如 api.openai.com/v1/models），
    否则同样按 ``{base_url}/models``（DeepSeek 等直接支持）。
    """
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/models"


def _parse_models_response(data: dict) -> list[str]:
    """从 /models 响应中提取模型 ID 列表。

    兼容 OpenAI 格式（``{"data": [{"id": ...}]}``）与部分自定义接口
    （``{"models": [...]}`` 或元素直接为字符串）。
    """
    items = data.get("data") or data.get("models") or []
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
        elif isinstance(item, str):
            ids.append(item)
    return ids


def _new_http_client() -> httpx.AsyncClient:
    """构造默认异步 HTTP 客户端。

    trust_env=False：避免 Windows 系统代理把 127.0.0.1 / 本地自定义端点的
    请求转发到代理导致 502（见项目记忆 windows-system-proxy-breaks-localhost）。
    远程提供商仍可直连（DeepSeek / Kimi / 智谱等国内服务无需代理）。
    """
    return httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT, follow_redirects=True, trust_env=False
    )


async def _request_models(
    base_url: str,
    api_key: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> tuple[Optional[list[str]], Optional[str]]:
    """请求 /models 端点，返回 (模型ID列表, 错误信息)，二者恰有一个非空。

    - 成功：返回 (model_ids, None)；
    - 失败：返回 (None, 错误信息)，错误信息面向用户展示，不抛异常。
    """
    url = _build_models_url(base_url)
    if not url:
        return None, "未配置 base_url"
    headers = {"Authorization": f"Bearer {api_key}"}
    if http_client is None:
        http_client = _new_http_client()
    try:
        response = await http_client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("GET %s 请求失败：%s", url, exc)
        return None, f"请求失败：{exc}"
    if response.status_code in (401, 403):
        return None, f"API Key 无效或无权限（HTTP {response.status_code}）"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}：{response.text[:200]}"
    try:
        payload = response.json()
    except ValueError:
        return None, "响应不是有效的 JSON"
    if not isinstance(payload, dict):
        return None, "响应格式异常（应为 JSON 对象）"
    model_ids = _parse_models_response(payload)
    if not model_ids:
        return None, "响应中未找到模型列表"
    return model_ids, None


def _build_api_key_entry(
    raw: dict, existing: Optional[dict]
) -> dict:
    """构造一条 api_keys_json 记录（新增或更新）。

    - raw 为前端提交的 Key 信息，可能含明文 ``key`` / ``key_id`` / enabled / priority；
    - existing 为数据库中同 key_id 的旧记录（None 表示新增）；
    - 提供了新明文（非脱敏占位符）→ 重新加密；否则复用旧密文；
    - 新增 Key 必须提供明文 key，否则抛 ModelProviderValidationError。
    """
    key_id = raw.get("key_id") or (existing.get("key_id") if existing else None) or _new_key_id()
    plaintext = (raw.get("key") or "").strip()
    existing_encrypted = existing.get("api_key_encrypted") if existing else None

    if plaintext and not _is_masked_key(plaintext):
        encrypted = encrypt_api_key(plaintext)
    elif existing_encrypted:
        encrypted = existing_encrypted
    else:
        raise ModelProviderValidationError("新增 API Key 必须提供明文 key")

    default_enabled = existing.get("enabled", True) if existing else True
    default_priority = existing.get("priority", DEFAULT_PRIORITY) if existing else DEFAULT_PRIORITY
    default_models = existing.get("available_models", []) if existing else []
    return {
        "key_id": key_id,
        "api_key_encrypted": encrypted,
        "enabled": bool(raw.get("enabled", default_enabled)),
        "priority": int(raw.get("priority", default_priority)),
        "available_models": list(raw.get("available_models", default_models)),
    }


def _merge_api_keys(existing_keys: list[dict], new_keys: list[dict]) -> list[dict]:
    """按 key_id 合并 API Key 列表（新增 / 修改 / 删除，一次全量替换）。

    - new_keys 中带 key_id 且存在于 existing → 更新该条（复用旧密文，除非提供新明文）；
    - new_keys 中不带 key_id → 视为新增；
    - existing 中未被 new_keys 覆盖的 → 删除。
    """
    existing_by_id = {k["key_id"]: k for k in existing_keys if k.get("key_id")}
    result: list[dict] = []
    for raw in new_keys:
        key_id = raw.get("key_id")
        existing = existing_by_id.get(key_id)
        if key_id and existing is None:
            raise ModelProviderValidationError(
                f"key_id {key_id} 不存在，无法更新（需先新增该 Key）"
            )
        result.append(_build_api_key_entry(raw, existing))
    return result


def _merge_models(existing_models: list[dict], new_models: list[dict]) -> list[dict]:
    """按 model_id 合并 models_json（一次全量替换，保留既有启用状态）。"""
    existing_enabled = {
        m["model_id"]: bool(m.get("enabled", True)) for m in existing_models
    }
    merged: dict[str, bool] = {}
    for item in new_models:
        model_id = item.get("model_id")
        if not model_id:
            continue
        merged[model_id] = bool(
            item.get("enabled", existing_enabled.get(model_id, True))
        )
    return [{"model_id": mid, "enabled": enabled} for mid, enabled in merged.items()]


async def _get_or_raise(db: AsyncSession, provider_id: str) -> ModelProvider:
    """按 id 查询提供商，不存在则抛 ModelProviderNotFound。"""
    provider = await db.get(ModelProvider, provider_id)
    if provider is None:
        raise ModelProviderNotFound(f"提供商 {provider_id} 不存在")
    return provider


# ---------------------------------------------------------------------------
# 提供商 CRUD
# ---------------------------------------------------------------------------


async def create_provider(
    db: AsyncSession,
    name: str,
    type: str,
    base_url: Optional[str] = None,
    api_keys: Optional[list[dict]] = None,
) -> ModelProvider:
    """创建提供商，加密各 API Key（docs/TECHv1.1.md §5.1）。

    api_keys 每项为 ``{"key": 明文, "enabled": bool, "priority": int}``；
    api_keys_json 与 models_json 初始为加密 Key 列表与空模型列表。
    模型列表需随后调用 fetch_model_list 获取（或手动添加）。
    """
    name = (name or "").strip()
    if not name:
        raise ModelProviderValidationError("提供商名称不能为空")
    if type not in MODEL_PROVIDER_TYPES:
        raise ModelProviderValidationError(
            f"type 必须是 {'/'.join(MODEL_PROVIDER_TYPES)}，当前：{type}"
        )
    keys = [_build_api_key_entry(raw, None) for raw in api_keys or []]
    provider = ModelProvider(
        name=name,
        type=type,
        base_url=(base_url or "").strip() or None,
        api_keys_json=keys,
        models_json=[],
        is_default=False,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


async def update_provider(
    db: AsyncSession,
    provider_id: str,
    name: Optional[str] = None,
    type: Optional[str] = None,
    base_url: Optional[str] = None,
    api_keys: Optional[list[dict]] = None,
    models: Optional[list[dict]] = None,
) -> ModelProvider:
    """更新提供商信息（仅更新显式传入的字段）。

    - api_keys：一次全量替换（新增 / 删除 / 改优先级 / 改明文均在此处理，
      未改动的 Key 由前端回传脱敏占位符，服务端复用旧密文）；
    - models：一次全量替换（支持启停模型）。
    """
    provider = await _get_or_raise(db, provider_id)
    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise ModelProviderValidationError("提供商名称不能为空")
        provider.name = stripped
    if type is not None:
        if type not in MODEL_PROVIDER_TYPES:
            raise ModelProviderValidationError(
                f"type 必须是 {'/'.join(MODEL_PROVIDER_TYPES)}，当前：{type}"
            )
        provider.type = type
    if base_url is not None:
        provider.base_url = base_url.strip() or None
    if api_keys is not None:
        provider.api_keys_json = _merge_api_keys(provider.api_keys_json or [], api_keys)
    if models is not None:
        provider.models_json = _merge_models(provider.models_json or [], models)
    await db.commit()
    await db.refresh(provider)
    return provider


async def delete_provider(db: AsyncSession, provider_id: str) -> None:
    """删除提供商。

    先解除项目（default_provider_id）、会话（current_provider_id）与生成记录
    （provider_id）对它的引用（设为 NULL），再删除本身；若它是全局默认提供商，
    同时清空 app_configs.global_default_provider_id。
    """
    provider = await _get_or_raise(db, provider_id)
    await db.execute(
        update(Project)
        .where(Project.default_provider_id == provider_id)
        .values(default_provider_id=None)
    )
    await db.execute(
        update(Conversation)
        .where(Conversation.current_provider_id == provider_id)
        .values(current_provider_id=None)
    )
    await db.execute(
        update(GenerationRecord)
        .where(GenerationRecord.provider_id == provider_id)
        .values(provider_id=None)
    )
    if provider.is_default:
        cfg = await db.scalar(
            select(AppConfig).where(AppConfig.key == GLOBAL_DEFAULT_PROVIDER_KEY)
        )
        if cfg is not None and cfg.value == provider_id:
            cfg.value = ""
    await db.delete(provider)
    await db.commit()


def _provider_detail_dict(provider: ModelProvider) -> dict:
    """提供商详情（api_keys 脱敏，仅返回脱敏后的 key，绝不含明文或密文）。"""
    masked_keys: list[dict] = []
    for key in provider.api_keys_json or []:
        item = dict(key)
        encrypted = item.pop("api_key_encrypted", "")
        try:
            masked_keys.append({**item, "key_masked": _mask_key(decrypt_api_key(encrypted))})
        except Exception:
            masked_keys.append({**item, "key_masked": "****"})
    return {
        "id": provider.id,
        "name": provider.name,
        "type": provider.type,
        "base_url": provider.base_url,
        "scope": provider.scope,
        "is_default": provider.is_default,
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
        "api_keys": masked_keys,
        "models": provider.models_json or [],
    }


def _provider_summary_dict(provider: ModelProvider) -> dict:
    """提供商摘要（不含任何 Key 信息）。

    status 为派生状态：``ready``（有启用 Key，可用于生成）/ ``no_keys``（无启用 Key）。
    """
    api_keys = provider.api_keys_json or []
    models = provider.models_json or []
    enabled_key_count = sum(1 for k in api_keys if k.get("enabled", True))
    return {
        "id": provider.id,
        "name": provider.name,
        "type": provider.type,
        "base_url": provider.base_url,
        "scope": provider.scope,
        "is_default": provider.is_default,
        "key_count": len(api_keys),
        "enabled_key_count": enabled_key_count,
        "model_count": len(models),
        "enabled_model_count": sum(1 for m in models if m.get("enabled", True)),
        "status": "ready" if enabled_key_count > 0 else "no_keys",
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


async def get_provider(db: AsyncSession, provider_id: str) -> dict:
    """获取提供商详情；api_keys 中的 key 脱敏（只显示前后几位）。"""
    provider = await _get_or_raise(db, provider_id)
    return _provider_detail_dict(provider)


async def list_providers(db: AsyncSession) -> list[dict]:
    """列出所有提供商摘要（不返回解密后的 Key，也不返回密文）。"""
    result = await db.execute(
        select(ModelProvider).order_by(ModelProvider.created_at)
    )
    return [_provider_summary_dict(p) for p in result.scalars().all()]


# ---------------------------------------------------------------------------
# API Key 选择与模型列表获取
# ---------------------------------------------------------------------------


def select_api_key(
    provider: ModelProvider,
    target_model_id: Optional[str],
    exclude_key_ids: Optional[set[str]] = None,
) -> tuple[dict, str]:
    """在生成 / 对话前选择可用的 API Key（docs/TECHv1.1.md §7.2）。

    优先级语义：priority 数值越小优先级越高（默认 1 为最高，与迁移中
    is_default 的 Key 排第 1 一致）。

    选择顺序：
    1. 所有启用的 Key 中，优先取 priority 最小、且 available_models 包含
       target_model_id 的 Key；
    2. 若均不包含目标模型，则取优先级最高的第一个启用 Key（available_models
       可能过时，调用失败由调用方标记并尝试下一个 Key）；
    3. 无启用 Key 时抛 NoAvailableApiKey。

    exclude_key_ids（V1.1，可选）：调用失败重试时排除已失败的 Key
    （docs/TECHv1.1.md §7.2「尝试下一个 Key」），默认 None。

    返回 (key_obj, decrypted_key)：key_obj 为 api_keys_json 中的记录 dict。
    """
    api_keys = provider.api_keys_json or []
    enabled = [k for k in api_keys if k.get("enabled", True)]
    if exclude_key_ids:
        enabled = [k for k in enabled if k.get("key_id") not in exclude_key_ids]
    if not enabled:
        raise NoAvailableApiKey(
            f"提供商「{provider.name}」没有可用的 API Key"
        )
    enabled.sort(key=lambda k: k.get("priority", DEFAULT_PRIORITY))

    # 1) 优先：命中目标模型且优先级最高
    if target_model_id:
        for key in enabled:
            if target_model_id in (key.get("available_models") or []):
                return key, decrypt_api_key(key["api_key_encrypted"])

    # 2) 兜底：第一个启用 Key（可能不含目标模型，调用方负责失败重试）
    fallback = enabled[0]
    return fallback, decrypt_api_key(fallback["api_key_encrypted"])


async def detect_key_connection(
    provider: ModelProvider,
    key_obj: dict,
    decrypted_key: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """发起轻量请求验证单个 Key 的有效性，并顺带获取其模型列表。

    返回 ``{"valid": bool, "error"?: str, "models"?: list[str]}``。
    本函数不做任何持久化（api_keys_json 的更新由 detect_provider 统一完成）。
    """
    model_ids, error = await _request_models(
        provider.base_url or "", decrypted_key, http_client
    )
    if error is not None:
        return {"valid": False, "error": error}
    return {"valid": True, "models": model_ids}


async def fetch_model_list(
    db: AsyncSession,
    provider_id: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """使用所有启用的 Key 请求 /models，合并去重并持久化。

    更新内容：
    - provider.models_json：与既有模型合并（保留手动添加的模型与启用状态），
      新模型默认启用；
    - 每个成功请求的 Key 的 available_models。

    返回 ``{"success": bool, "models": list[str], "errors": [{key_id, error}]}``，
    其中 success 为至少一个 Key 获取成功，models 为合并去重后的模型 ID 列表。
    """
    provider = await _get_or_raise(db, provider_id)
    enabled_keys = [
        k for k in provider.api_keys_json or [] if k.get("enabled", True)
    ]
    errors: list[dict] = []
    per_key_models: dict[str, list[str]] = {}
    all_models: list[str] = []

    if not enabled_keys:
        errors.append({"key_id": None, "error": "提供商没有启用的 API Key"})

    for index, key in enumerate(enabled_keys):
        key_id = key.get("key_id") or f"key_{index}"
        try:
            decrypted = decrypt_api_key(key.get("api_key_encrypted", ""))
        except Exception as exc:
            logger.warning("API Key 解密失败（provider=%s key=%s）：%s", provider_id, key_id, exc)
            errors.append({"key_id": key_id, "error": f"解密失败：{exc}"})
            continue
        model_ids, error = await _request_models(
            provider.base_url or "", decrypted, http_client
        )
        if error is not None:
            errors.append({"key_id": key_id, "error": error})
            continue
        per_key_models[key_id] = model_ids
        all_models.extend(model_ids)

    # 与既有模型合并（保留手动添加与启用状态），按首次出现顺序去重
    existing_enabled = {
        m["model_id"]: bool(m.get("enabled", True)) for m in provider.models_json or []
    }
    merged_ids = list(dict.fromkeys([*existing_enabled.keys(), *all_models]))
    provider.models_json = [
        {"model_id": mid, "enabled": existing_enabled.get(mid, True)}
        for mid in merged_ids
    ]

    # 更新成功 Key 的 available_models（失败 Key 保留原值）。
    # JSON 列不追踪原地修改，需整体重建列表后再赋值才能触发持久化。
    updated_keys: list[dict] = []
    for key in provider.api_keys_json or []:
        key_id = key.get("key_id")
        if key_id in per_key_models:
            key = {**key, "available_models": per_key_models[key_id]}
        updated_keys.append(key)
    provider.api_keys_json = updated_keys

    await db.commit()

    success = bool(per_key_models)
    return {"success": success, "models": merged_ids, "errors": errors}


async def detect_provider(
    db: AsyncSession,
    provider_id: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> list[dict]:
    """检测提供商下所有 Key 的连接状态，并更新可用模型列表。

    每个 Key（含禁用状态）都会发起一次 /models 请求；成功者将其
    available_models 更新为获取到的模型列表并持久化。

    返回每个 Key 的状态：
        [{"key_id", "valid": bool, "error": Optional[str], "model_count": int}, ...]
    """
    provider = await _get_or_raise(db, provider_id)
    results: list[dict] = []
    # JSON 列不追踪原地修改，需整体重建列表后再赋值触发持久化
    updated_keys: list[dict] = []
    for index, key in enumerate(provider.api_keys_json or []):
        key_id = key.get("key_id") or f"key_{index}"
        try:
            decrypted = decrypt_api_key(key.get("api_key_encrypted", ""))
        except Exception as exc:
            logger.warning("API Key 解密失败（provider=%s key=%s）：%s", provider_id, key_id, exc)
            updated_keys.append(key)
            results.append(
                {"key_id": key_id, "valid": False, "error": f"解密失败：{exc}", "model_count": 0}
            )
            continue
        model_ids, error = await _request_models(
            provider.base_url or "", decrypted, http_client
        )
        if error is not None:
            updated_keys.append(key)
            results.append(
                {"key_id": key_id, "valid": False, "error": error, "model_count": 0}
            )
            continue
        updated_keys.append({**key, "available_models": model_ids})
        results.append(
            {"key_id": key_id, "valid": True, "error": None, "model_count": len(model_ids)}
        )
    provider.api_keys_json = updated_keys
    await db.commit()
    return results


async def detect_single_key(
    db: AsyncSession,
    provider_id: str,
    key_id: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """检测单个 Key 的连接状态并持久化其 available_models（docs/TECHv1.1.md §5.1）。

    - Key 有效：将该 Key 的 available_models 更新为获取到的模型列表；
    - Key 无效 / 解密失败：保留原值；
    - Key 不存在：抛 ModelProviderValidationError。

    返回 ``{"key_id", "valid": bool, "error": Optional[str], "model_count": int}``。
    """
    provider = await _get_or_raise(db, provider_id)
    result: dict = {}
    updated_keys: list[dict] = []
    found = False
    for index, key in enumerate(provider.api_keys_json or []):
        current_key_id = key.get("key_id") or f"key_{index}"
        if current_key_id != key_id:
            # 非目标 Key 原样保留
            updated_keys.append(key)
            continue
        found = True
        try:
            decrypted = decrypt_api_key(key.get("api_key_encrypted", ""))
        except Exception as exc:
            logger.warning(
                "API Key 解密失败（provider=%s key=%s）：%s", provider_id, key_id, exc
            )
            updated_keys.append(key)
            result = {
                "key_id": key_id,
                "valid": False,
                "error": f"解密失败：{exc}",
                "model_count": 0,
            }
            continue
        status_obj = await detect_key_connection(provider, key, decrypted, http_client)
        if status_obj["valid"]:
            updated_keys.append({**key, "available_models": status_obj["models"]})
            result = {
                "key_id": key_id,
                "valid": True,
                "error": None,
                "model_count": len(status_obj["models"]),
            }
        else:
            updated_keys.append(key)
            result = {
                "key_id": key_id,
                "valid": False,
                "error": status_obj["error"],
                "model_count": 0,
            }
    if not found:
        raise ModelProviderValidationError(f"API Key {key_id} 不存在")
    provider.api_keys_json = updated_keys
    await db.commit()
    return result
