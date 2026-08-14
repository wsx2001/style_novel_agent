# backend/scripts/verify_depth_mapping.py
"""思维深度映射验证脚本（docs/TECHv1.md §8）。

运行方式（在 backend/ 下）：
    python scripts/verify_depth_mapping.py

覆盖：
- resolve_auto_depth 边界规则；
- apply_depth_config 在不同模型 / 深度 / 用户参数下的解析结果；
- get_depth_mapping / save_depth_mapping 的 AppConfig 读写（临时 SQLite，不影响正式库）。
所有断言通过时打印 OK 汇总并以退出码 0 结束。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# Windows 控制台可能为 GBK：强制 UTF-8 输出避免编码异常
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.depth_mapping import (  # noqa: E402
    DEFAULT_DEPTH_MAPPING,
    apply_depth_config,
    get_depth_mapping,
    resolve_auto_depth,
    save_depth_mapping,
)

_passed = 0
_failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    """断言并计数。"""
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [OK] {label}")
    else:
        _failed += 1
        print(f"  [FAIL] {label}  {detail}")


def test_resolve_auto_depth() -> None:
    print("[1] resolve_auto_depth")
    check("context 8001 -> high", resolve_auto_depth(8001, 0) == "high")
    check("cards 9 -> high", resolve_auto_depth(0, 9) == "high")
    check("context 4001 -> medium", resolve_auto_depth(4001, 0) == "medium")
    check("cards 5 -> medium", resolve_auto_depth(0, 5) == "medium")
    check("context 4000 -> low", resolve_auto_depth(4000, 0) == "low")
    check("cards 4 -> low", resolve_auto_depth(0, 4) == "low")
    check("context 0 / cards 0 -> low", resolve_auto_depth(0, 0) == "low")


def test_apply_default_mapping() -> None:
    print("[2] apply_depth_config - 默认映射（普通模型）")
    low = apply_depth_config("low", "gpt-4o", {})
    check("low -> temperature 0.9", low.get("temperature") == 0.9, str(low))
    check("low -> max_tokens 1024", low.get("max_tokens") == 1024, str(low))
    high = apply_depth_config("high", "gpt-4o", {})
    check("high -> temperature 0.5", high.get("temperature") == 0.5, str(high))
    check("high -> max_tokens 4096", high.get("max_tokens") == 4096, str(high))
    extreme = apply_depth_config("extreme", "gpt-4o", {})
    check("extreme -> max_tokens 8192", extreme.get("max_tokens") == 8192, str(extreme))
    check("普通模型不含 reasoning_effort", "reasoning_effort" not in low, str(low))
    check("普通模型不含 thinking", "thinking" not in low, str(low))


def test_apply_model_overrides() -> None:
    print("[3] apply_depth_config - model_overrides（推理模型）")
    o1_low = apply_depth_config("low", "o1-mini", {})
    check("o1-mini low -> reasoning_effort low", o1_low.get("reasoning_effort") == "low", str(o1_low))
    check("o1-mini low 无 temperature", "temperature" not in o1_low, str(o1_low))
    o1_ext = apply_depth_config("extreme", "o1-mini", {})
    check("o1-mini extreme -> reasoning_effort high", o1_ext.get("reasoning_effort") == "high", str(o1_ext))
    check("o1-mini extreme -> max_tokens 8192", o1_ext.get("max_tokens") == 8192, str(o1_ext))

    ds_high = apply_depth_config("high", "deepseek-reasoner", {})
    check("deepseek-reasoner high -> thinking enabled", ds_high.get("thinking", {}).get("type") == "enabled", str(ds_high))
    check("deepseek-reasoner high -> max_tokens 4096", ds_high.get("max_tokens") == 4096, str(ds_high))
    # deepseek-reasoner 无 extreme 等级 -> 回退 default 映射
    ds_ext = apply_depth_config("extreme", "deepseek-reasoner", {})
    check("deepseek-reasoner extreme 回退 default -> temperature 0.3", ds_ext.get("temperature") == 0.3, str(ds_ext))
    check("deepseek-reasoner extreme 回退 default -> max_tokens 8192", ds_ext.get("max_tokens") == 8192, str(ds_ext))


def test_auto_and_none() -> None:
    print("[4] apply_depth_config - auto / none")
    auto = apply_depth_config("auto", "gpt-4o", {}, context_length=9000, knowledge_card_count=0)
    check("auto(context 9000) 解析为 high -> temperature 0.5", auto.get("temperature") == 0.5, str(auto))
    auto2 = apply_depth_config("auto", "gpt-4o", {}, context_length=100, knowledge_card_count=0)
    check("auto(context 100) 解析为 low -> temperature 0.9", auto2.get("temperature") == 0.9, str(auto2))
    none = apply_depth_config("none", "gpt-4o", {"temperature": 0.6})
    check("none 仅保留用户参数", none == {"temperature": 0.6}, str(none))


def test_user_params_override() -> None:
    print("[5] apply_depth_config - 用户显式参数优先")
    merged = apply_depth_config("high", "gpt-4o", {"temperature": 0.8, "max_tokens": 3000})
    check("用户 temperature 0.8 覆盖映射", merged.get("temperature") == 0.8, str(merged))
    check("用户 max_tokens 3000 覆盖映射", merged.get("max_tokens") == 3000, str(merged))


def test_param_filtering() -> None:
    print("[6] apply_depth_config - 不支持的参数过滤")
    # 普通模型显式传 reasoning_effort / thinking 应被移除
    filtered = apply_depth_config("high", "gpt-4o", {"reasoning_effort": "high", "thinking": {"type": "enabled"}})
    check("gpt-4o 移除 reasoning_effort", "reasoning_effort" not in filtered, str(filtered))
    check("gpt-4o 移除 thinking", "thinking" not in filtered, str(filtered))
    # o1 模型保留 reasoning_effort，移除 thinking
    o1 = apply_depth_config("high", "o1-preview", {"reasoning_effort": "high", "thinking": {"type": "enabled"}})
    check("o1-preview 保留 reasoning_effort", o1.get("reasoning_effort") == "high", str(o1))
    check("o1-preview 移除 thinking", "thinking" not in o1, str(o1))
    # reasoner 模型保留 thinking，移除 reasoning_effort
    ds = apply_depth_config("medium", "deepseek-reasoner", {"reasoning_effort": "high"})
    check("deepseek-reasoner 移除 reasoning_effort", "reasoning_effort" not in ds, str(ds))
    check("deepseek-reasoner medium 保留 thinking", ds.get("thinking", {}).get("type") == "enabled", str(ds))


def test_prefix_override() -> None:
    print("[7] apply_depth_config - 自定义映射的模型前缀匹配")
    custom = {
        "default": {"medium": {"temperature": 0.7}},
        "model_overrides": {"o1": {"high": {"reasoning_effort": "high", "max_tokens": 9999}}},
    }
    res = apply_depth_config("high", "o1-preview", {}, mapping=custom)
    check("自定义 o1 前缀匹配 o1-preview -> max_tokens 9999", res.get("max_tokens") == 9999, str(res))
    check("o1-preview 保留 reasoning_effort", res.get("reasoning_effort") == "high", str(res))
    # 用户显式参数优先于自定义映射
    res2 = apply_depth_config("high", "o1-preview", {"max_tokens": 100}, mapping=custom)
    check("用户 max_tokens 覆盖自定义映射", res2.get("max_tokens") == 100, str(res2))


async def test_db_roundtrip() -> None:
    print("[8] get_depth_mapping / save_depth_mapping（临时 SQLite）")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models import Base

    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_depth_test_")
    os.close(fd)
    try:
        url = "sqlite+aiosqlite:///" + path.replace("\\", "/")
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async with maker() as s:
            m = await get_depth_mapping(s)
            check("未配置时返回默认映射", m == DEFAULT_DEPTH_MAPPING, str(m))

        custom = {"default": {"low": {"temperature": 1.0}}, "model_overrides": {}}
        async with maker() as s:
            await save_depth_mapping(s, custom)
        async with maker() as s:
            m = await get_depth_mapping(s)
            check("保存后可读回自定义映射", m == custom, str(m))

        custom2 = {"default": {"medium": {"temperature": 0.5}}, "model_overrides": {}}
        async with maker() as s:
            await save_depth_mapping(s, custom2)  # 覆盖更新
        async with maker() as s:
            m = await get_depth_mapping(s)
            check("再次保存为更新（upsert）", m == custom2, str(m))

        await engine.dispose()
    finally:
        if os.path.exists(path):
            os.remove(path)


def main() -> None:
    test_resolve_auto_depth()
    test_apply_default_mapping()
    test_apply_model_overrides()
    test_auto_and_none()
    test_user_params_override()
    test_param_filtering()
    test_prefix_override()
    asyncio.run(test_db_roundtrip())
    print(f"\n结果：{_passed} 通过，{_failed} 失败")
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
