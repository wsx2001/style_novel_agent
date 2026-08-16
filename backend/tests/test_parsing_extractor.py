# backend/tests/test_parsing_extractor.py
"""文档设定抽取回归测试（docs/TECH.md §5.2 / §6.2）。

针对 bug「LLM 抽取失败：LLM 未返回有效 JSON：''」：
- 根因：_chat_json 硬编码 max_tokens=2048，推理模型（如 DeepSeek V4）把预算
  全部消耗在 reasoning_content 上，content 为空/截断；
- 修复：提升到 EXTRACTION_MAX_TOKENS，且单分块返回非有效 JSON 时跳过而非
  拖垮整个文档解析。
"""
from __future__ import annotations

import json

import pytest

from app.services.parsing.extractor import (
    EXTRACTION_MAX_TOKENS,
    _chat_json,
    extract_candidates,
)

pytestmark = pytest.mark.anyio

# 与 extractor.py 同构的合法抽取结果
VALID_RESULT = {
    "style": {"叙事视角": "第一人称"},
    "characters": [{"name": "主角", "description": "来自异世界"}],
    "worldSettings": [],
    "terms": [],
    "keyEvents": [],
}


class _StubClient:
    """模拟 LLMClient：按序返回预设响应，记录每次调用参数（不发起真实请求）。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat_completion(self, messages, **kwargs) -> str:  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# 根因回归：token 预算必须足够大（推理模型会把预算花在 reasoning_content）
# ---------------------------------------------------------------------------


async def test_chat_json_passes_large_max_tokens():
    """_chat_json 必须传足 EXTRACTION_MAX_TOKENS（而非旧硬编码 2048）。"""
    stub = _StubClient(["{}"])
    await _chat_json(stub, [{"role": "user", "content": "hi"}], temperature=0.2)
    assert stub.calls[0]["max_tokens"] == EXTRACTION_MAX_TOKENS
    assert stub.calls[0]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# 症状回归：空 / 无效 JSON 不再让整个文档解析失败
# ---------------------------------------------------------------------------


async def test_extract_candidates_skips_empty_response():
    """LLM 返回空串时跳过该分块并返回空结果，不再抛 ValueError。"""
    stub = _StubClient([""])
    cards = await extract_candidates("一段小说文本", stub, threshold="medium")
    assert cards == []


async def test_extract_candidates_skips_invalid_keeps_valid():
    """混合响应：坏分块被跳过，好分块仍产出候选卡。"""
    stub = _StubClient(["not a json", json.dumps(VALID_RESULT, ensure_ascii=False)])
    cards = await extract_candidates("内容" * 3000, stub)
    assert len(cards) == 2
    assert {c["card_type"] for c in cards} == {"style", "character"}


async def test_extract_candidates_parses_valid_chunk():
    """正常路径：合法 JSON 产出 style 卡与人物卡。"""
    stub = _StubClient([json.dumps(VALID_RESULT, ensure_ascii=False)])
    cards = await extract_candidates("一段小说文本", stub)
    assert len(cards) == 2
    assert cards[0]["card_type"] == "style"
    assert cards[0]["title"] == "文风设定"
    assert cards[1]["card_type"] == "character"
    assert cards[1]["title"] == "主角"
