# backend/tests/test_parsing_extractor.py
"""文档设定抽取回归测试（docs/TECH.md §5.2 / §6.2）。

针对 bug「LLM 抽取失败：LLM 未返回有效 JSON：''」：
- 根因：_chat_json 硬编码 max_tokens=2048，推理模型（如 DeepSeek V4）把预算
  全部消耗在 reasoning_content 上，content 为空/截断；
- 修复：提升到 EXTRACTION_MAX_TOKENS，且单分块返回非有效 JSON 时跳过而非
  拖垮整个文档解析。

针对 bug「解析失败请求超时」：
- 根因：extract_candidates 逐分块串行调用 LLM，大文档（191KB ≈ 51 块）总耗时
  远超前端超时；
- 修复：分块并发抽取（PARSE_CONCURRENCY 限流）；单个分块 LLM 失败仅跳过，
  全部分块失败才抛错。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.api.v1.documents import _parse_result_payload, _single_unit_decision
from app.models import Document
from app.services.parsing.extractor import (
    CONSOLIDATION_MAX_CARDS_PER_TYPE,
    CONSOLIDATION_MAX_INPUT_CHARS,
    CONSOLIDATION_MAX_TOKENS,
    EXTRACTION_MAX_TOKENS,
    SAFE_SINGLE_UNIT_CHARS,
    SINGLE_UNIT_MAX_BYTES,
    _chat_json,
    _compact_cards_for_consolidation,
    _consolidate_cards,
    extract_candidates,
    split_extraction_units,
    stream_extract_candidates,
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


class _ConcurrentStubClient:
    """模拟慢 LLM：每次调用 sleep 一下，记录最大同时进行中的调用数。

    用于验证 extract_candidates 是否真正并发（串行实现下 max_active 恒为 1）。
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.active = 0
        self.max_active = 0

    async def chat_completion(self, messages, **kwargs) -> str:  # type: ignore[no-untyped-def]
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.05)
        self.active -= 1
        return self._responses.pop(0)


class _RaisingStubClient:
    """模拟 LLM 调用失败：前 fail_first 次调用抛异常，之后正常返回。

    _chat_json 对每个分块至多发起 2 次调用（json_object 失败后重试一次），
    因此单个分块失败需 fail_first >= 2 才能把该分块彻底打失败。
    """

    def __init__(self, responses: list[str], fail_first: int) -> None:
        self._responses = list(responses)
        self._fail_first = fail_first
        self.calls: list[dict] = []

    async def chat_completion(self, messages, **kwargs) -> str:  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self._fail_first > 0:
            self._fail_first -= 1
            raise TimeoutError("LLM 调用超时")
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


# ---------------------------------------------------------------------------
# 请求超时回归：分块并发抽取，单块失败仅跳过
# ---------------------------------------------------------------------------


async def test_extract_candidates_runs_chunks_concurrently():
    """多分块并发调用 LLM：2 块应同时处于调用中，而非串行等待。"""
    stub = _ConcurrentStubClient(
        [json.dumps(VALID_RESULT, ensure_ascii=False)] * 2
    )
    cards = await extract_candidates("内容" * 3000, stub)  # 6000 字符 → 2 块
    assert len(cards) == 2
    assert stub.max_active >= 2


async def test_extract_candidates_skips_chunk_llm_error_keeps_valid():
    """单个分块 LLM 调用失败被跳过，其余分块仍产出候选卡（不拖垮整份文档）。"""
    stub = _RaisingStubClient(
        [json.dumps(VALID_RESULT, ensure_ascii=False)], fail_first=2
    )
    cards = await extract_candidates("内容" * 3000, stub)  # 2 块，第一块彻底失败
    assert len(cards) == 2
    # 第一块发起了带 json_object 的尝试（_chat_json 回退逻辑）
    assert stub.calls[0]["response_format"] == {"type": "json_object"}


async def test_extract_candidates_raises_when_all_chunks_fail():
    """全部分块 LLM 调用都失败 → 抛错（调用方映射为失败状态），而非返回空结果。"""
    stub = _RaisingStubClient([], fail_first=10)
    with pytest.raises(RuntimeError, match="LLM 调用超时"):
        await extract_candidates("内容" * 3000, stub)


# ---------------------------------------------------------------------------
# 结构化分块（章/卷/节）
# ---------------------------------------------------------------------------

CHAPTER_TEXT = (
    "第一章 初入江湖\n"
    "他踏入城门，望向远处。\n"
    "\n"
    "第二章 故人\n"
    "旧友来访，把酒言欢。\n"
    "\n"
    "第三章 抉择\n"
    "他做出了决定。\n"
)


async def test_split_extraction_units_by_chapter():
    """多章文本 → 按章切分，label 为章标题，text 含正文。"""
    units = split_extraction_units(CHAPTER_TEXT)
    assert [u["label"] for u in units] == [
        "第一章 初入江湖",
        "第二章 故人",
        "第三章 抉择",
    ]
    assert "他踏入城门" in units[0]["text"]
    assert "旧友来访" in units[1]["text"]
    assert "做出了决定" in units[2]["text"]


async def test_split_extraction_units_volume_only():
    """仅卷结构 → 按卷切分。"""
    text = "第一卷 风起\n正文甲。\n\n第二卷 暗涌\n正文乙。"
    units = split_extraction_units(text)
    assert [u["label"] for u in units] == ["第一卷 风起", "第二卷 暗涌"]
    assert "正文甲" in units[0]["text"]
    assert "正文乙" in units[1]["text"]


async def test_split_extraction_units_volume_prepends_to_first_chapter():
    """卷 + 章 → 卷标题并入其作用域内第一章作上下文，不产生空单元。"""
    text = "第一卷 风起\n第一章 初入江湖\n正文甲。\n第二章 故人\n正文乙。"
    units = split_extraction_units(text)
    assert [u["label"] for u in units] == ["第一章 初入江湖", "第二章 故人"]
    assert "第一卷 风起" in units[0]["text"]
    assert "第一卷 风起" not in units[1]["text"]


async def test_split_extraction_units_fallback_plain_text():
    """无章/卷标记 → 回退固定字数分块，label 为「第 N 段」。"""
    units = split_extraction_units("内容" * 3000)  # 6000 字符
    assert len(units) == 2
    assert units[0]["label"] == "第 1 段"
    assert units[1]["label"] == "第 2 段"


async def test_split_extraction_units_oversized_sub_split():
    """超长章 → 二次切分，label 追加「（k/m）」。"""
    chapter = "第五章 长章\n" + "正文。" * 4000  # 约 12000 字符
    units = split_extraction_units(chapter)
    assert len(units) >= 2
    assert units[0]["label"].startswith("第五章 长章（1/")
    # 每个单元不超过 MAX_UNIT_CHARS
    for unit in units:
        assert len(unit["text"]) <= 8000


# ---------------------------------------------------------------------------
# 流式抽取：进度帧
# ---------------------------------------------------------------------------


async def test_stream_extract_candidates_emits_progress_frames():
    """流式抽取产出 start/done（含 label 与计数）+ 终帧 done 候选。"""
    stub = _ConcurrentStubClient([json.dumps(VALID_RESULT, ensure_ascii=False)] * 3)
    events: list[dict] = []
    async for frame in stream_extract_candidates(CHAPTER_TEXT, stub):
        events.append(frame)

    progress = [f for f in events if f["event"] == "progress"]
    done_frames = [f for f in events if f["event"] == "done"]
    # 3 个章单元，每个至少一个 start + 一个 done
    assert {f["data"]["index"] for f in progress if f["data"]["status"] == "start"} == {0, 1, 2}
    done_units = [f for f in progress if f["data"]["status"] == "done"]
    assert {f["data"]["index"] for f in done_units} == {0, 1, 2}
    # 简略结果：VALID_RESULT 含 1 个人物
    assert all(f["data"]["result"]["characters"] == 1 for f in done_units)
    assert {f["data"]["label"] for f in done_units} == {
        "第一章 初入江湖",
        "第二章 故人",
        "第三章 抉择",
    }
    # 终帧 done 带合并候选
    assert len(done_frames) == 1
    candidates = done_frames[0]["data"]["candidates"]
    assert {c["card_type"] for c in candidates} == {"style", "character"}


# ---------------------------------------------------------------------------
# 整篇解析（single_unit）：单单元一次性喂入全文 + 失败自动回退分块
# ---------------------------------------------------------------------------


async def test_split_extraction_units_single_unit_flag():
    """single_unit=True → 整篇作为单单元（label「全文」，不分章）。"""
    text = "第一章 开头\n正文甲。\n\n第二章 后续\n正文乙。"
    units = split_extraction_units(text, single_unit=True)
    assert len(units) == 1
    assert units[0]["label"] == "全文"
    assert units[0]["text"] == text.strip()


async def test_stream_extract_candidates_single_unit_single_call():
    """single_unit=True：恰 1 次 LLM 调用（不分块），done 含完整候选。"""
    stub = _StubClient([json.dumps(VALID_RESULT, ensure_ascii=False)])
    events: list[dict] = []
    async for frame in stream_extract_candidates(
        "第一章 初入江湖\n正文。\n第二章 故人\n正文乙。",
        stub,
        single_unit=True,
    ):
        events.append(frame)

    assert len(stub.calls) == 1  # 单单元 → 1 次调用，无合并（<30 张）
    progress = [f for f in events if f["event"] == "progress"]
    assert {f["data"]["index"] for f in progress} == {0}
    assert progress[0]["data"]["label"] == "全文"
    done = [f for f in events if f["event"] == "done"][0]
    assert {c["card_type"] for c in done["data"]["candidates"]} == {"style", "character"}


async def test_stream_extract_candidates_single_unit_falls_back():
    """整篇单单元调用失败 → 自动回退分块解析，不把整篇失败的 error 帧暴露给调用方。"""
    stub = _RaisingStubClient(
        [json.dumps(VALID_RESULT, ensure_ascii=False)] * 3, fail_first=2
    )
    events: list[dict] = []
    async for frame in stream_extract_candidates(CHAPTER_TEXT, stub, single_unit=True):
        events.append(frame)

    # 回退到分块：3 章各产出候选
    assert len([f for f in events if f["event"] == "error"]) == 0
    progress = [f for f in events if f["event"] == "progress"]
    done_units = [f for f in progress if f["data"]["status"] == "done"]
    assert {f["data"]["label"] for f in done_units} == {
        "第一章 初入江湖",
        "第二章 故人",
        "第三章 抉择",
    }
    # 整篇尝试的帧已缓冲丢弃
    assert all("全文" not in f["data"].get("label", "") for f in progress)
    done = [f for f in events if f["event"] == "done"][0]
    assert {c["card_type"] for c in done["data"]["candidates"]} == {"style", "character"}


# ---------------------------------------------------------------------------
# 候选卡合并去重：压缩 / 合并 / 失败回退 / 端到端
# ---------------------------------------------------------------------------


async def test_compact_cards_for_consolidation_truncates_and_caps():
    """压缩：字符串叶子截断至 120、去 snippet_ids、每类输入预上限、输出可解析 JSON。"""
    # 长内容 → 串截断，且不保留 snippet_ids
    cards = [
        {
            "card_type": "character",
            "title": f"角色{i}",
            "content_json": {"name": f"角色{i}", "description": "描写" * 300},
            "snippet_ids": [f"s{i}"],
        }
        for i in range(3)
    ]
    payload = _compact_cards_for_consolidation(cards)
    assert len(payload) <= CONSOLIDATION_MAX_INPUT_CHARS
    data = json.loads(payload)
    for card in data:
        assert "snippet_ids" not in card
        assert len(card["content_json"]["description"]) == 120  # 已截断

    # 大量短卡片 → 输入侧每类预上限
    many = [
        {
            "card_type": "character",
            "title": f"角色{i}",
            "content_json": {"name": f"角色{i}"},
            "snippet_ids": [],
        }
        for i in range(130)
    ]
    data2 = json.loads(_compact_cards_for_consolidation(many))
    assert len(data2) == CONSOLIDATION_MAX_CARDS_PER_TYPE["character"]


async def test_consolidate_cards_merges_near_duplicates():
    """合并调用：合并同一人物不同写法（如「李明」与「李明（主角）」）为一条。"""
    cards = [
        {
            "card_type": "character",
            "title": f"角色{i}",
            "content_json": {"name": f"角色{i}", "description": "介绍"},
            "snippet_ids": [],
        }
        for i in range(30)
    ]
    merged_json = {
        "style": {},
        "characters": [{"name": "李明", "description": "主角，性格坚韧"}],
        "worldSettings": [],
        "terms": [],
        "keyEvents": [],
    }
    stub = _StubClient([json.dumps(merged_json, ensure_ascii=False)])
    out = await _consolidate_cards(cards, stub)
    assert len(out) == 1
    assert out[0]["card_type"] == "character"
    assert out[0]["title"] == "李明"


async def test_consolidate_cards_failure_falls_back():
    """合并调用抛异常 / 返回无效 JSON → 回退原候选列表，不抛错。"""
    cards = [
        {
            "card_type": "character",
            "title": f"角色{i}",
            "content_json": {"name": f"角色{i}"},
            "snippet_ids": [],
        }
        for i in range(3)
    ]
    # LLM 调用抛异常 → 回退
    stub = _RaisingStubClient([], fail_first=10)
    assert await _consolidate_cards(cards, stub) == cards
    # 返回无效 JSON → 回退
    stub2 = _StubClient(["not a json"])
    assert await _consolidate_cards(cards, stub2) == cards


async def test_stream_extract_candidates_consolidates_large_results():
    """候选 ≥30 张 → 追加合并调用：done 候选减少且带 consolidated_from。"""
    def _block(names: list[str]) -> str:
        return json.dumps(
            {
                "style": {"叙事视角": "第三人称"},
                "characters": [{"name": n, "description": "角色"} for n in names],
                "worldSettings": [],
                "terms": [],
                "keyEvents": [],
            },
            ensure_ascii=False,
        )

    consolidation = json.dumps(
        {
            "style": {"叙事视角": "第三人称"},
            "characters": [{"name": "主角", "description": "合并后的主角"}],
            "worldSettings": [],
            "terms": [],
            "keyEvents": [],
        },
        ensure_ascii=False,
    )
    block_names = [
        [f"角色A{i}" for i in range(10)],
        [f"角色B{i}" for i in range(10)],
        [f"角色C{i}" for i in range(10)],
    ]
    stub = _StubClient([*map(_block, block_names), consolidation])

    events: list[dict] = []
    async for frame in stream_extract_candidates(
        "第一章 甲\n正文。\n\n第二章 乙\n正文。\n\n第三章 丙\n正文。", stub
    ):
        events.append(frame)

    done_frames = [f for f in events if f["event"] == "done"]
    assert len(done_frames) == 1
    payload = done_frames[0]["data"]
    assert payload["consolidated_from"] == 31  # 30 人物 + 1 style
    assert len(payload["candidates"]) == 2  # style + 合并后的主角
    assert len(stub.calls) == 3 + 1  # 3 分块 + 1 合并


async def test_stream_extract_candidates_skips_consolidation_small():
    """小结果（<30 张）→ 无额外合并调用。"""
    stub = _StubClient([json.dumps(VALID_RESULT, ensure_ascii=False)])
    cards = await extract_candidates("一段小文本", stub)
    assert len(cards) == 2
    assert len(stub.calls) == 1  # 仅 1 次抽取调用


async def test_chat_json_passes_custom_max_tokens():
    """_chat_json 透传自定义 max_tokens（合并调用使用 CONSOLIDATION_MAX_TOKENS）。"""
    stub = _StubClient(["{}"])
    await _chat_json(
        stub,
        [{"role": "user", "content": "hi"}],
        temperature=0.1,
        max_tokens=CONSOLIDATION_MAX_TOKENS,
    )
    assert stub.calls[0]["max_tokens"] == CONSOLIDATION_MAX_TOKENS


# ---------------------------------------------------------------------------
# 文档解析端点纯函数
# ---------------------------------------------------------------------------


def test_single_unit_decision():
    """_single_unit_decision：小文本整篇；大文本需 1M 且 ≤1MB 才整篇。"""
    tiny_text = "你好，短文本"
    assert _single_unit_decision(500, tiny_text, False) is True

    big_text = "x" * (SAFE_SINGLE_UNIT_CHARS + 1)
    assert _single_unit_decision(SINGLE_UNIT_MAX_BYTES, big_text, False) is False
    assert _single_unit_decision(SINGLE_UNIT_MAX_BYTES, big_text, True) is True
    # 超过 1MB 即使开 1M 也不整篇（回退分块）
    assert _single_unit_decision(SINGLE_UNIT_MAX_BYTES + 1, big_text, True) is False


def test_parse_result_payload():
    """_parse_result_payload：parsed + 有候选 → 返回响应体；否则 None。"""
    doc = Document(
        id="doc-1",
        project_id="proj-1",
        filename="a.txt",
        file_type="txt",
        file_size=1024,
        content_text="正文",
        status="parsed",
        parse_threshold="medium",
        require_manual_confirm=True,
        parse_result_json={
            "candidates": [{"card_type": "style", "title": "文风", "content_json": {"a": "b"}}],
            "threshold": "low",
            "manual_confirm": True,
            "extracted_at": "2026-01-01T00:00:00",
        },
    )
    payload = _parse_result_payload(doc)
    assert payload is not None
    assert payload["candidates"][0]["title"] == "文风"
    assert payload["threshold"] == "low"

    # 状态不是 parsed → None（尚未解析 / 解析失败）
    doc.status = "pending"
    assert _parse_result_payload(doc) is None

    # 已导入 → 结果不再提供（已转为知识卡）
    doc.status = "imported"
    assert _parse_result_payload(doc) is None

    # parsed 但无候选 → None
    doc.status = "parsed"
    doc.parse_result_json = {"threshold": "medium"}
    assert _parse_result_payload(doc) is None
