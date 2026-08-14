# backend/app/services/depth_mapping.py
"""思维深度映射（docs/TECHv1.md §8）。

- DEFAULT_DEPTH_MAPPING：系统内置映射（default + model_overrides）；
- get_depth_mapping / save_depth_mapping：读写全局 AppConfig（键 depth_mapping_config）；
- resolve_auto_depth：将 "auto" 按上下文长度 / 知识卡数量解析为具体等级；
- apply_depth_config：按模型与深度查找映射参数，合并用户显式参数，
  过滤模型不支持的推理参数，返回最终 LLM API 参数字典。

参数合并优先级（§8.2）：映射规则仅作为缺省值，user_params 中显式提供的
temperature / max_tokens 等参数优先于映射值。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AppConfig

# AppConfig 中思维深度映射的存储键
DEPTH_MAPPING_CONFIG_KEY = "depth_mapping_config"

# 允许透传给 LLM API 的参数白名单（depth 等非参数键不会泄漏到 API 调用）
API_PARAM_KEYS = frozenset({
    "temperature",
    "max_tokens",
    "reasoning_effort",
    "thinking",
    "top_p",
    "top_k",
    "frequency_penalty",
    "presence_penalty",
    "stop",
    "seed",
})

# 系统内置思维深度映射（docs/TECHv1.md §8.1）
DEFAULT_DEPTH_MAPPING: dict[str, Any] = {
    "default": {
        "low": {"temperature": 0.9, "max_tokens": 1024},
        "medium": {"temperature": 0.7, "max_tokens": 2048},
        "high": {"temperature": 0.5, "max_tokens": 4096},
        "extreme": {"temperature": 0.3, "max_tokens": 8192},
    },
    "model_overrides": {
        "o1-mini": {
            "low": {"reasoning_effort": "low"},
            "medium": {"reasoning_effort": "medium"},
            "high": {"reasoning_effort": "high"},
            "extreme": {"reasoning_effort": "high", "max_tokens": 8192},
        },
        "deepseek-reasoner": {
            "low": {"thinking": {"type": "disabled"}},
            "medium": {"thinking": {"type": "enabled"}},
            "high": {"thinking": {"type": "enabled"}, "max_tokens": 4096},
        },
    },
}


async def get_depth_mapping(db: AsyncSession) -> dict[str, Any]:
    """读取全局思维深度映射配置；未配置或值损坏时返回默认映射（深拷贝）。"""
    value = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == DEPTH_MAPPING_CONFIG_KEY)
    )
    if isinstance(value, dict) and value:
        return value
    return deepcopy(DEFAULT_DEPTH_MAPPING)


async def save_depth_mapping(db: AsyncSession, mapping: dict[str, Any]) -> None:
    """保存思维深度映射到全局 AppConfig（key 已存在则更新，否则插入）。"""
    if not isinstance(mapping, dict):
        raise ValueError("mapping 必须是 dict")
    config = await db.scalar(
        select(AppConfig).where(AppConfig.key == DEPTH_MAPPING_CONFIG_KEY)
    )
    if config is None:
        db.add(AppConfig(key=DEPTH_MAPPING_CONFIG_KEY, value=mapping))
    else:
        config.value = mapping
    await db.commit()


def resolve_auto_depth(context_length: int, knowledge_card_count: int) -> str:
    """按 docs/TECHv1.md §8.1 的规则将 "auto" 解析为具体等级。

    - 上下文长度 > 8000 或知识卡 > 8 → high
    - 上下文长度 > 4000 或知识卡 > 4 → medium
    - 否则 → low
    """
    if context_length > 8000 or knowledge_card_count > 8:
        return "high"
    if context_length > 4000 or knowledge_card_count > 4:
        return "medium"
    return "low"


def _lookup_level_params(
    mapping: dict[str, Any], model: str, level: str
) -> dict[str, Any]:
    """按 精确模型名 -> 模型前缀（最长优先）-> default 的顺序查找映射参数。

    若选中的 model_overrides 条目缺少该等级，则回退到 default 映射的同等级参数。
    """
    overrides = mapping.get("model_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}

    exact = overrides.get(model)
    if isinstance(exact, dict):
        params = exact.get(level)
        if isinstance(params, dict):
            return dict(params)

    best_prefix = ""
    for prefix in overrides:
        if model.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
    if best_prefix:
        params = overrides[best_prefix].get(level)
        if isinstance(params, dict):
            return dict(params)

    default_levels = mapping.get("default", {})
    if isinstance(default_levels, dict):
        params = default_levels.get(level)
        if isinstance(params, dict):
            return dict(params)
    return {}


def _filter_unsupported(model: str, params: dict[str, Any]) -> dict[str, Any]:
    """过滤模型不支持的推理参数。

    - 模型名含 "o1"：支持 reasoning_effort（保留），不支持 thinking（移除）；
    - 模型名含 "reasoner"：支持 thinking（保留），不支持 reasoning_effort（移除）；
    - 其余模型：两者均移除。
    """
    result = dict(params)
    ml = model.lower()
    if "o1" not in ml:
        result.pop("reasoning_effort", None)
    if "reasoner" not in ml:
        result.pop("thinking", None)
    return result


def apply_depth_config(
    depth: str,
    model: str,
    user_params: Optional[dict[str, Any]] = None,
    mapping: Optional[dict[str, Any]] = None,
    *,
    context_length: int = 0,
    knowledge_card_count: int = 0,
) -> dict[str, Any]:
    """根据思维深度与模型名称解析最终 LLM API 参数字典。

    处理流程（docs/TECHv1.md §8.1/8.2）：
    1. depth="none"：不使用映射参数，仅保留用户显式参数；
    2. depth="auto"（或未指定）：先按 context_length / knowledge_card_count
       解析为具体等级；
    3. 按 精确模型名 -> 模型前缀 -> default 查找该等级的映射参数；
    4. 合并 user_params（用户显式参数优先）；
    5. 仅透传白名单参数，并过滤模型不支持的 reasoning_effort / thinking。

    mapping 缺省时使用系统内置 DEFAULT_DEPTH_MAPPING。
    """
    if mapping is None:
        mapping = DEFAULT_DEPTH_MAPPING
    user_params = user_params or {}

    effective = depth or "auto"
    if effective == "auto":
        effective = resolve_auto_depth(context_length, knowledge_card_count)

    if effective == "none":
        merged = dict(user_params)
    else:
        merged = _lookup_level_params(mapping, model, effective)
        merged.update(user_params)

    final = {k: v for k, v in merged.items() if k in API_PARAM_KEYS}
    return _filter_unsupported(model, final)
