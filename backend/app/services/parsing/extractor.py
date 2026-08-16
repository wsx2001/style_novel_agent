# backend/app/services/parsing/extractor.py
"""LLM 设定抽取：分块调用 LLM，合并去重，输出候选卡片列表。

流程（docs/TECH.md §5.2 / §6.2）：
1. 将 document.content_text 按 4000 字符分块（重叠 200）；
2. 每个块调用 LLM 抽取（json_object 模式，不支持的 provider 自动回退）；
3. 合并所有块结果：style 取并集，其余类别按主字段去重；
4. 转为候选卡片列表（字典形式，对应 schemas CandidateCard）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..llm.client import LLMClient
from ..llm.prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# 分块参数（docs/TECH.md §6.2）
CHUNK_SIZE = 4000
CHUNK_OVERLAP = 200

# 单分块抽取的 token 上限：推理模型（如 DeepSeek V4）会把大量预算消耗在
# reasoning_content 上，上限太小会导致 content 为空/截断（曾用 2048 触发
# "LLM 未返回有效 JSON：''"）。8192 仅为上限，不强制消耗，按实际用量计费。
EXTRACTION_MAX_TOKENS = 8192

# parse_threshold -> temperature（阈值越高，抽取越保守稳定）
THRESHOLD_TEMPERATURE: dict[str, float] = {"low": 0.4, "medium": 0.2, "high": 0.1}

# 类别 -> 去重/命名主字段；以及 类别 -> 卡片类型
_DEDUPE_FIELDS: dict[str, str] = {
    "characters": "name",
    "worldSettings": "title",
    "terms": "term",
    "keyEvents": "title",
}
_CARD_TYPES: dict[str, str] = {
    "characters": "character",
    "worldSettings": "world",
    "terms": "term",
    "keyEvents": "event",
}


def chunk_text(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """将文本按 chunk_size 分块，相邻块重叠 overlap 字符。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(end - overlap, start + 1)  # +1 保证推进，避免死循环
    return chunks


def _extract_json(raw: str) -> dict[str, Any]:
    """从 LLM 响应中稳健解析 JSON（容忍 markdown 代码围栏与前后多余文本）。"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"LLM 未返回有效 JSON：{raw[:200]!r}")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 返回的 JSON 无法解析：{exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM 返回的 JSON 不是对象")
    return parsed


def _merge_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """合并各块结果：style 键值取并集；其余类别按主字段去重（首见保留）。"""
    merged: dict[str, Any] = {
        "style": {},
        "characters": [],
        "worldSettings": [],
        "terms": [],
        "keyEvents": [],
    }
    seen: dict[str, set[str]] = {key: set() for key in _DEDUPE_FIELDS}
    for result in results:
        if not isinstance(result, dict):
            continue
        style = result.get("style")
        if isinstance(style, dict):
            merged["style"].update(style)
        for key, primary in _DEDUPE_FIELDS.items():
            for item in result.get(key) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get(primary, "")).strip()
                if not name or name in seen[key]:
                    continue
                seen[key].add(name)
                merged[key].append(item)
    return merged


def _to_candidate_cards(merged: dict[str, Any]) -> list[dict[str, Any]]:
    """将合并结果转为候选卡片列表（字典形式，对应 CandidateCard schema）。"""
    cards: list[dict[str, Any]] = []
    if merged.get("style"):
        cards.append(
            {
                "card_type": "style",
                "title": "文风设定",
                "content_json": merged["style"],
                "snippet_ids": [],
            }
        )
    for key, card_type in _CARD_TYPES.items():
        for entry in merged.get(key) or []:
            primary = str(entry.get(_DEDUPE_FIELDS[key], "")).strip() or "未命名"
            cards.append(
                {
                    "card_type": card_type,
                    "title": primary,
                    "content_json": entry,
                    "snippet_ids": [],
                }
            )
    return cards


async def _chat_json(
    client: LLMClient, messages: list[dict[str, Any]], temperature: float
) -> str:
    """调用 LLM 并优先使用 json_object 模式；不支持的 provider 回退为普通调用。"""
    try:
        return await client.chat_completion(
            messages,
            temperature=temperature,
            max_tokens=EXTRACTION_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
    except Exception:
        return await client.chat_completion(
            messages, temperature=temperature, max_tokens=EXTRACTION_MAX_TOKENS
        )


async def extract_candidates(
    content_text: str, client: LLMClient, threshold: str = "medium"
) -> list[dict[str, Any]]:
    """对文档全文抽取设定，返回候选卡片列表（不写入数据库）。"""
    chunks = chunk_text(content_text)
    if not chunks:
        return []
    temperature = THRESHOLD_TEMPERATURE.get(threshold, 0.2)

    results: list[dict[str, Any]] = []
    for chunk in chunks:
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": EXTRACTION_USER_PROMPT_TEMPLATE.format(chunk=chunk),
            },
        ]
        raw = await _chat_json(client, messages, temperature)
        try:
            results.append(_extract_json(raw))
        except ValueError as exc:
            # 单分块返回空/无效 JSON 不拖垮整个文档：记日志并跳过该分块
            logger.warning("设定抽取：分块返回非有效 JSON，已跳过：%s", exc)

    return _to_candidate_cards(_merge_results(results))
