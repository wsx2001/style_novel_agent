# backend/app/services/llm/stream.py
"""LLM 流式生成：多候选解析 + SSE 编码（docs/TECH.md §7.3）。

候选分隔符为 `<<<CANDIDATE_n>>>`。模型输出的候选文本按该分隔符切分：
- CandidateSplitter：缓冲增量文本解析多候选，兼容分隔符被 LLM 增量输出切跨 chunk；
- sse_event：将事件编码为 SSE 帧（event + data）；
- stream_candidates：流式调用 LLM 并逐段产出 SSE 帧的 async generator。
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any, Optional

from .client import LLMClient

# 候选分隔符：<<<CANDIDATE_1>>> / <<<CANDIDATE_2>>> / ...
CANDIDATE_RE = re.compile(r"<<<CANDIDATE_(\d+)>>>")
_DELIM_HEAD = "<<<CANDIDATE_"


def _is_delim_prefix(s: str) -> bool:
    """判断 s 是否为候选分隔符的前缀。

    两类都视为“可能是分隔符的开头”：
    1. 分隔符头部 `<<<CANDIDATE_` 自身的前缀（如 `<<`、`<<<C`，分隔符尚未输完）；
    2. 头部已完整且后跟数字 + `>`（如 `<<<CANDIDATE_1`、`<<<CANDIDATE_12>>`）。
    """
    if _DELIM_HEAD.startswith(s):
        return True
    if not s.startswith(_DELIM_HEAD):
        return False
    rest = s[len(_DELIM_HEAD):]
    if not rest:
        return True
    j = 0
    while j < len(rest) and rest[j].isdigit():
        j += 1
    return set(rest[j:]) <= {">"}


class CandidateSplitter:
    """多候选流解析器：累积各候选文本，兼容分隔符跨 chunk。

    用法：
        splitter = CandidateSplitter()
        for index, text in splitter.feed(delta): ...   # 逐段喂入 LLM 增量
        candidates = splitter.finish()                 # 收尾，返回非空候选列表

    feed 返回 (index, text)：index 为候选序号（1 基）；首个分隔符前的序言为 None，
    不会被计入任何候选。
    """

    def __init__(self) -> None:
        self.candidates: list[str] = []
        self._current: Optional[int] = None
        self._buffer = ""
        self._preamble = ""  # 首个分隔符之前的文本（候选外）；无分隔符时兜底为单候选

    def feed(self, delta: str) -> list[tuple[Optional[int], str]]:
        """喂入一段增量文本，返回应下发的 (候选序号, 正文增量) 列表。"""
        self._buffer += delta
        out: list[tuple[Optional[int], str]] = []

        # 反复切分已完整出现的分隔符（分隔符可能一次出现多个）
        while True:
            match = CANDIDATE_RE.search(self._buffer)
            if match is None:
                break
            head = self._buffer[: match.start()]
            tail = self._buffer[match.end():]
            if head:
                out.append((self._current, head))
                self._append(self._current, head)
            self._current = int(match.group(1))
            self._buffer = tail

        # 缓冲尾部可能是半截分隔符（分隔符跨 chunk），暂留到下一次 feed 再判断
        hold = self._hold_len(self._buffer)
        if hold:
            flush_text, self._buffer = self._buffer[:-hold], self._buffer[-hold:]
        else:
            flush_text, self._buffer = self._buffer, ""
        if flush_text:
            out.append((self._current, flush_text))
            self._append(self._current, flush_text)
        return out

    def finish(self) -> list[str]:
        """收尾：返回按分隔符切分的非空候选列表。

        若模型未输出任何分隔符（单候选），整个正文作为一条候选兜底返回。
        """
        if self._buffer:
            self._append(self._current, self._buffer)
            self._buffer = ""
        candidates = [c for c in self.candidates if c and c.strip()]
        if not candidates and self._preamble.strip():
            return [self._preamble.strip()]
        return candidates

    def _append(self, index: Optional[int], text: str) -> None:
        if not text:
            return
        if index is None:
            self._preamble += text
            return
        while len(self.candidates) < index:
            self.candidates.append("")
        self.candidates[index - 1] += text

    @staticmethod
    def _hold_len(text: str) -> int:
        """返回需暂留的尾部长度：若文本尾部是半截分隔符前缀则暂留，否则 0。"""
        for i in range(len(text), 0, -1):
            if _is_delim_prefix(text[-i:]):
                return i
        return 0


def sse_event(event: str, data: dict[str, Any]) -> str:
    """编码一条 SSE 帧：`event: <event>\ndata: <json>\n\n`。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_candidates(
    client: LLMClient,
    messages: list[dict[str, Any]],
    *,
    temperature: float,
    max_tokens: int,
    model: Optional[str] = None,
    depth: Optional[str] = None,
    user_params: Optional[dict[str, Any]] = None,
    mapping: Optional[dict[str, Any]] = None,
    context_length: int = 0,
    knowledge_card_count: int = 0,
) -> AsyncIterator[str]:
    """流式调用 LLM 并解析多候选，产出 SSE 帧（delta / done）的 async generator。

    帧格式：
        event: delta  data: {"index": n, "text": "..."}   # n 为候选序号（1 基）
        event: done   data: {"candidates": ["...", ...]}
    """
    splitter = CandidateSplitter()
    async for delta in client.chat_completion_stream(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        depth=depth,
        user_params=user_params,
        mapping=mapping,
        context_length=context_length,
        knowledge_card_count=knowledge_card_count,
    ):
        for index, text in splitter.feed(delta):
            if index is None or not text:
                continue  # 分隔符前序言：丢弃，不发给前端
            yield sse_event("delta", {"index": index, "text": text})
    yield sse_event("done", {"candidates": splitter.finish()})
