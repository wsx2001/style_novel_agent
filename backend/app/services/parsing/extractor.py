# backend/app/services/parsing/extractor.py
"""LLM 设定抽取：按章节单元并发调用 LLM，合并去重，输出候选卡片列表。

流程（docs/TECH.md §5.2 / §6.2）：
1. split_extraction_units：按 章/卷/节 标题拆分为语义完整的抽取单元
   （无结构时回退固定 4000 字符分块），超长单元二次切分；
   调用方传入 single_unit=True（文件 ≤1MB 且模型开启「1M 上下文」开关，
   或文本足够小）时整篇作为单单元一次喂入，模型可见全文上下文；
2. stream_extract_candidates：各单元并发调用 LLM 抽取
   （json_object 模式，不支持的 provider 自动回退），逐个产出进度帧；
   整篇单单元失败（如超模型上下文）时自动回退分块解析；
3. 合并所有单元结果：style 取并集，其余类别按主字段去重；
4. 候选卡达到 CONSOLIDATION_MIN_CARDS 时追加一次 LLM 合并去重调用
   （同人异名/互补内容合并、删除路人、按精简档截断），失败回退原候选；
5. 转为候选卡片列表（字典形式，对应 schemas CandidateCard）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any, Optional

from ..llm.client import LLMClient
from ..llm.prompts import (
    EXTRACTION_CONSOLIDATION_SYSTEM_PROMPT,
    EXTRACTION_CONSOLIDATION_USER_TEMPLATE,
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)

# 分块参数（docs/TECH.md §6.2）
CHUNK_SIZE = 4000
CHUNK_OVERLAP = 200

# 单分块抽取的 token 上限：推理模型（如 DeepSeek V4）会把大量预算消耗在
# reasoning_content 上，上限太小会导致 content 为空/截断（曾用 2048 触发
# "LLM 未返回有效 JSON：''"）。8192 仅为上限，不强制消耗，按实际用量计费。
EXTRACTION_MAX_TOKENS = 8192

# 分块抽取的并发上限：大文档分块多（191KB ≈ 51 块），串行依次调用远程 LLM
# 总耗时远超 HTTP 超时（bug「解析失败请求超时」）；并发受限流保护，避免打爆
# 提供商限流。
PARSE_CONCURRENCY = 5

# 单个抽取单元的最大字符数：超长章按段落二次切分，避免单次抽取上下文过大
MAX_UNIT_CHARS = 8000

# 整篇解析阈值（docs/TECH.md §5.2）：
# - SAFE_SINGLE_UNIT_CHARS：任何模型都安全的整篇字符阈值（≈30K 字符 ≈ 4-4.5 万
#   token，普通 64K/128K 上下文模型仍有余量）。低于该值的文档整篇单次喂入 LLM；
# - SINGLE_UNIT_MAX_BYTES：开启「1M 上下文」开关的模型，≤该文件字节大小的文档
#   整篇喂入（1MB 中文 ≈ 35 万字符，只有大上下文模型可承载）。整篇调用失败时
#   stream_extract_candidates 自动回退分块解析。
SAFE_SINGLE_UNIT_CHARS = 30000
SINGLE_UNIT_MAX_BYTES = 1024 * 1024

# 候选卡 LLM 合并去重：分块抽取完成后，对候选卡追加一次合并调用，解决「同一
# 人物/设定被多个分块重复抽取」导致的冗余（如「李明」与「李明（主角）」并存）。
CONSOLIDATION_MIN_CARDS = 30           # 候选卡少于该数量时跳过合并调用（省一次 LLM 调用）
CONSOLIDATION_MAX_INPUT_CHARS = 20000  # 合并调用输入 JSON 字符预算
CONSOLIDATION_CARD_CONTENT_TRUNCATE = 120  # 压缩时 content_json 字符串叶子截断长度
CONSOLIDATION_MAX_CARDS_PER_TYPE = {   # 发送前输入侧每类预上限（键为 card_type，首见顺序）
    "character": 120,
    "world": 80,
    "term": 60,
    "event": 80,
}
CONSOLIDATION_OUTPUT_CAPS = {          # 输出侧每类上限（精简档，写入合并提示词 + 兜底截断）
    "character": 25,
    "world": 15,
    "term": 10,
    "event": 15,
}
CONSOLIDATION_MAX_TOKENS = 8192        # 合并输出上限（超限 JSON 截断 → 回退原候选，安全）
CONSOLIDATION_TEMPERATURE = 0.1        # 合并是确定性任务，固定低温

# 章节级标题：行首「第X章/回/节/集/幕」+ 可选标题，或 楔子/序章/番外 等
_CHAPTER_RE = re.compile(
    r"^\s*(?:第[0-9〇零一二三四五六七八九十百千万两]+[章回节集幕]"
    r"|楔子|序章|序言|引子|引言|前言|后记|尾声|番外(?:篇|外传)?).*$"
)
# 卷级标题：行首「第X卷/部」或「X卷/部」，后跟空格 + 标题
# （无空格不视为标题，避免误伤「一卷残页」这类正文行）
_VOLUME_RE = re.compile(
    r"^\s*(?:第[0-9〇零一二三四五六七八九十百千万两]+[卷部]"
    r"|[一二三四五六七八九十百千万两]+[卷部])(?:\s+.*)?$"
)

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


def _sub_split_units(units: list[dict[str, str]]) -> list[dict[str, str]]:
    """将超过 MAX_UNIT_CHARS 的单元按字数二次切分，label 追加「（k/m）」。"""
    out: list[dict[str, str]] = []
    for unit in units:
        text = unit["text"]
        if len(text) <= MAX_UNIT_CHARS:
            out.append(unit)
            continue
        pieces = chunk_text(text, chunk_size=MAX_UNIT_CHARS, overlap=200)
        for k, piece in enumerate(pieces, 1):
            out.append({"label": f"{unit['label']}（{k}/{len(pieces)}）", "text": piece})
    return out


def split_extraction_units(
    content_text: str, *, single_unit: bool = False
) -> list[dict[str, str]]:
    """按章节/卷级标题将文档拆分为语义完整的抽取单元。

    优先级：整篇（single_unit=True，label「全文」，一次喂入全文）> 章级标记
    （章/回/节/集/幕 + 楔子/序章/番外等）> 卷级标记（卷/部）> 回退固定字数分块
    （label 为「第 N 段」）。每单元含 label（标题行）与 text（标题 + 正文）；
    存在章结构时，卷标题并入其作用域内第一章作上下文。
    超长单元按段落二次切分（label 追加「（k/m）」）。
    single_unit 由调用方根据文件大小与模型「1M 上下文」开关判定（documents.py），
    默认 False 保持原有分块行为。
    """
    text = content_text.strip()
    if not text:
        return []
    if single_unit:
        return [{"label": "全文", "text": text}]
    lines = text.split("\n")
    is_chapter = [_CHAPTER_RE.match(line.strip()) is not None for line in lines]
    is_volume = [_VOLUME_RE.match(line.strip()) is not None for line in lines]

    if not any(is_chapter) and not any(is_volume):
        return [
            {"label": f"第 {n} 段", "text": piece}
            for n, piece in enumerate(chunk_text(text), 1)
        ]

    units: list[dict[str, str]] = []
    current: list[str] = []          # 当前单元正文行
    current_label: Optional[str] = None
    context: list[str] = []          # 卷标题（章结构存在时并入所属章开头）

    def _flush() -> None:
        nonlocal current, current_label
        body = "\n".join(current).strip()
        if current_label or body:
            label = current_label or "前言"
            units.append({"label": label, "text": f"{label}\n{body}" if body else label})
        current = []
        current_label = None

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if is_chapter[idx]:
            _flush()
            current = list(context)  # 卷上下文挂到本单元开头
            context = []
            current_label = stripped
        elif is_volume[idx]:
            if any(is_chapter):
                context.append(stripped)
            else:
                _flush()
                current_label = stripped
        else:
            current.append(line)
    _flush()

    if any(len(u["text"]) > MAX_UNIT_CHARS for u in units):
        units = _sub_split_units(units)
    return units


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


def _enforce_output_caps(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按精简档每类上限截断候选卡（首见顺序保留；style 不在上限内恒保留）。"""
    counts: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        ctype = card.get("card_type")
        cap = CONSOLIDATION_OUTPUT_CAPS.get(ctype)
        if cap is not None and counts.get(ctype, 0) >= cap:
            continue
        counts[ctype] = counts.get(ctype, 0) + 1
        out.append(card)
    return out


def _compact_cards_for_consolidation(cards: list[dict[str, Any]]) -> str:
    """将候选卡压缩为合并调用输入 JSON。

    丢弃 snippet_ids；递归截断 content_json 字符串叶子至
    CONSOLIDATION_CARD_CONTENT_TRUNCATE；按类型保持先见顺序、每类不超过
    CONSOLIDATION_MAX_CARDS_PER_TYPE；若序列化后仍超字符预算，从「卡数最多
    且 > 保底 10」的类别末尾丢弃直至达标。纯函数，可单测。
    """

    def _truncate(value: Any) -> Any:
        if isinstance(value, str):
            return (
                value
                if len(value) <= CONSOLIDATION_CARD_CONTENT_TRUNCATE
                else value[:CONSOLIDATION_CARD_CONTENT_TRUNCATE]
            )
        if isinstance(value, dict):
            return {k: _truncate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_truncate(v) for v in value]
        return value

    compact: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        compact.append(
            {
                "card_type": card.get("card_type"),
                "title": _truncate(str(card.get("title", "")).strip() or "未命名"),
                "content_json": _truncate(card.get("content_json") or {}),
            }
        )

    # 输入侧每类预上限（保持先见顺序；style 无上限）
    counts: dict[str, int] = {}
    capped: list[dict[str, Any]] = []
    for card in compact:
        ctype = card["card_type"]
        limit = CONSOLIDATION_MAX_CARDS_PER_TYPE.get(ctype)
        if limit is not None and counts.get(ctype, 0) >= limit:
            continue
        counts[ctype] = counts.get(ctype, 0) + 1
        capped.append(card)

    # 字符预算：超限时从「卡数最多且 > 保底 10」的类别末尾丢弃，直至达标
    while True:
        payload = json.dumps(capped, ensure_ascii=False)
        if len(payload) <= CONSOLIDATION_MAX_INPUT_CHARS:
            return payload
        type_counts: dict[str, int] = {}
        for card in capped:
            type_counts[card["card_type"]] = type_counts.get(card["card_type"], 0) + 1
        drop_type = next(
            (
                ctype
                for ctype, n in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                if n > 10
            ),
            None,
        )
        if drop_type is None:
            return payload  # 已到每类保底，接受超限（输入极端情况，输出侧仍受 caps 约束）
        for i in range(len(capped) - 1, -1, -1):
            if capped[i]["card_type"] == drop_type:
                capped.pop(i)
                break


def _consolidation_messages(cards_json: str) -> list[dict[str, Any]]:
    """组装候选卡合并调用的 messages（system 注入每类上限 + user 卡列表）。

    系统模板含字面 JSON 花括号，占位符用 .replace() 注入；用户模板仅一个
    {cards_json} 用 .format()。
    """
    prompt = EXTRACTION_CONSOLIDATION_SYSTEM_PROMPT
    caps = CONSOLIDATION_OUTPUT_CAPS
    prompt = prompt.replace("{{MAX_CHARACTERS}}", str(caps["character"]))
    prompt = prompt.replace("{{MAX_WORLD}}", str(caps["world"]))
    prompt = prompt.replace("{{MAX_TERMS}}", str(caps["term"]))
    prompt = prompt.replace("{{MAX_EVENTS}}", str(caps["event"]))
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": EXTRACTION_CONSOLIDATION_USER_TEMPLATE.format(cards_json=cards_json),
        },
    ]


async def _consolidate_cards(
    cards: list[dict[str, Any]], client: LLMClient
) -> list[dict[str, Any]]:
    """对候选卡做 LLM 合并去重：同人异名/互补内容合并、删除路人、按精简档截断。

    任何失败（LLM 调用异常 / 无效 JSON / 结构不符）记 warning 并回退原候选列表，
    绝不让整个解析失败。
    """
    try:
        cards_json = _compact_cards_for_consolidation(cards)
        raw = await _chat_json(
            client,
            _consolidation_messages(cards_json),
            CONSOLIDATION_TEMPERATURE,
            max_tokens=CONSOLIDATION_MAX_TOKENS,
        )
        parsed = _extract_json(raw)
        return _enforce_output_caps(_to_candidate_cards(_merge_results([parsed])))
    except Exception as exc:
        logger.warning("设定抽取：候选卡合并去重失败，回退原候选：%s", exc)
        return cards


async def _chat_json(
    client: LLMClient,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int = EXTRACTION_MAX_TOKENS,
) -> str:
    """调用 LLM 并优先使用 json_object 模式；不支持的 provider 回退为普通调用。"""
    try:
        return await client.chat_completion(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception:
        return await client.chat_completion(
            messages, temperature=temperature, max_tokens=max_tokens
        )


def _unit_messages(unit: dict[str, str]) -> list[dict[str, Any]]:
    """组装单个抽取单元的 messages（system + user，chunk 为单元文本）。"""
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": EXTRACTION_USER_PROMPT_TEMPLATE.format(chunk=unit["text"]),
        },
    ]


def _unit_summary(result: dict[str, Any]) -> dict[str, int]:
    """单元简略结果：各类别数量（供进度面板展示）。"""
    return {
        key: len(result.get(key) or [])
        for key in ("characters", "worldSettings", "terms", "keyEvents")
    }


async def _extract_chunk(
    client: LLMClient,
    messages: list[dict[str, Any]],
    temperature: float,
) -> tuple[Optional[dict[str, Any]], Optional[Exception]]:
    """抽取单个单元：成功返回 (result, None)。

    失败返回 (None, err) 且按原因区分：
    - ValueError（空 / 无效 JSON）：跳过该单元，不计为整体失败（与旧行为一致）；
    - 其他异常（LLM 调用失败）：跳过，但上层在「全部单元都失败」时抛错。
    """
    try:
        raw = await _chat_json(client, messages, temperature)
        return _extract_json(raw), None
    except ValueError as exc:
        logger.warning("设定抽取：分块返回非有效 JSON，已跳过：%s", exc)
        return None, None
    except Exception as exc:
        logger.warning("设定抽取：分块调用 LLM 失败，已跳过：%s", exc)
        return None, exc


async def stream_extract_candidates(
    content_text: str,
    client: LLMClient,
    threshold: str = "medium",
    *,
    single_unit: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """按章节单元并发抽取设定，逐个产出进度帧（供 SSE 转发 / 测试）。

    single_unit=True 时整篇作为单单元一次喂入 LLM（模型可见全文上下文）；
    若整篇调用失败（如超模型上下文）或未产出候选，自动回退分块解析。
    分块/整篇结果合并后，候选达到 CONSOLIDATION_MIN_CARDS 时追加一次
    LLM 合并去重调用（失败回退原候选）。

    帧格式（{"event", "data"}，event 供 sse_event 编码）：
        progress / {"index", "total", "label", "status": "start"}
        progress / {"index", "total", "label", "status": "done", "result": {...计数}}
        progress / {"index", "total", "label", "status": "error"}      # 单块失败
        progress / {"index", "total", "label", "status": "skipped"}    # 空/无效 JSON
        error     / {"message"}                                        # 空文档 / 全部失败
        done      / {"candidates": [...], "consolidated_from"?: int}   # 合并候选
    """

    async def _run(single_unit_flag: bool) -> AsyncIterator[dict[str, Any]]:
        units = split_extraction_units(content_text, single_unit=single_unit_flag)
        total = len(units)
        if total == 0:
            yield {"event": "error", "data": {"message": "文档为空，无法解析"}}
            return
        temperature = THRESHOLD_TEMPERATURE.get(threshold, 0.2)

        semaphore = asyncio.Semaphore(PARSE_CONCURRENCY)
        start_queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()

        async def _call(
            index: int, unit: dict[str, str]
        ) -> tuple[Optional[dict[str, Any]], Optional[Exception]]:
            async with semaphore:
                start_queue.put_nowait((index, unit["label"]))
                return await _extract_chunk(client, _unit_messages(unit), temperature)

        meta: dict[asyncio.Task, tuple[int, str]] = {}
        tasks: set[asyncio.Task] = set()
        for index, unit in enumerate(units):
            task = asyncio.create_task(_call(index, unit))
            tasks.add(task)
            meta[task] = (index, unit["label"])

        results: dict[int, dict[str, Any]] = {}
        errors: list[Exception] = []
        while tasks:
            done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            while not start_queue.empty():
                index, label = start_queue.get_nowait()
                yield {
                    "event": "progress",
                    "data": {"index": index, "total": total, "label": label, "status": "start"},
                }
            for task in done:
                index, label = meta[task]
                result, err = task.result()
                if err is not None:
                    errors.append(err)
                    yield {
                        "event": "progress",
                        "data": {"index": index, "total": total, "label": label, "status": "error"},
                    }
                elif result is None:
                    yield {
                        "event": "progress",
                        "data": {"index": index, "total": total, "label": label, "status": "skipped"},
                    }
                else:
                    results[index] = result
                    yield {
                        "event": "progress",
                        "data": {
                            "index": index,
                            "total": total,
                            "label": label,
                            "status": "done",
                            "result": _unit_summary(result),
                        },
                    }

        if not results and errors:
            yield {"event": "error", "data": {"message": str(errors[0])}}
            return
        merged = _merge_results([results[index] for index in sorted(results)])
        raw_cards = _to_candidate_cards(merged)
        if len(raw_cards) >= CONSOLIDATION_MIN_CARDS:
            final_cards = await _consolidate_cards(raw_cards, client)
        else:
            final_cards = raw_cards
        data: dict[str, Any] = {"candidates": final_cards}
        if len(final_cards) != len(raw_cards):
            data["consolidated_from"] = len(raw_cards)
        yield {"event": "done", "data": data}

    if not single_unit:
        async for frame in _run(False):
            yield frame
        return

    # 整篇解析：缓冲单单元帧（量很小）；失败/空候选时回退分块解析
    buffered: list[dict[str, Any]] = []
    fallback = False
    async for frame in _run(True):
        buffered.append(frame)
        if frame["event"] == "error":
            logger.warning("设定抽取：整篇解析失败，回退分块解析：%s", frame["data"]["message"])
            fallback = True
            break
        if frame["event"] == "done" and not frame["data"].get("candidates"):
            logger.warning("设定抽取：整篇解析未产出候选，回退分块解析")
            fallback = True
            break
    if fallback:
        async for frame in _run(False):
            yield frame
        return
    for buffered_frame in buffered:
        yield buffered_frame


async def extract_candidates(
    content_text: str,
    client: LLMClient,
    threshold: str = "medium",
    *,
    single_unit: bool = False,
) -> list[dict[str, Any]]:
    """对文档全文抽取设定，返回候选卡片列表（不写入数据库）。

    兼容入口：内部走 stream_extract_candidates（结构化分块 + 并发 + 合并去重），
    正常返回合并候选；全部分块失败抛 RuntimeError。
    """
    async for frame in stream_extract_candidates(
        content_text, client, threshold, single_unit=single_unit
    ):
        if frame["event"] == "error":
            raise RuntimeError(frame["data"]["message"])
        if frame["event"] == "done":
            return frame["data"]["candidates"]
    return []
