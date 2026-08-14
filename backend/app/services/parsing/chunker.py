# backend/app/services/parsing/chunker.py
"""文档分块：按段落切分，每块目标 300~800 字，相邻块重叠 50~100 字（docs/TECH.md §6.2）。

输出片段字典列表：
    {"text": str, "tags": list[str], "start": int, "end": int}
- tags：Markdown 标题（`# `）上下文 + 高频双字关键词；
- start / end：片段在原文中的字符偏移（含重叠尾巴时，start 指向重叠起点）。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

# 分块参数（docs/TECH.md §6.2）
CHUNK_MIN = 300
CHUNK_MAX = 800
CHUNK_OVERLAP = 75

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")
_SENTENCE_END = "。！？；.!?;"
# 中文高频虚词（关键词统计时过滤单字停用词）
_STOP_CHARS = set(
    "的了是在我你他她它们和与等着过说这那有也就都不被把向从为又或者再很还已经一个"
)


def _split_paragraphs(text: str) -> list[dict[str, Any]]:
    """将文本按空行分隔为段落，返回带偏移的段落列表。"""
    paragraphs: list[dict[str, Any]] = []
    lines: list[str] = []
    seg_start: int | None = None
    seg_end = 0
    pos = 0
    n = len(text)
    while pos < n:
        nl = text.find("\n", pos)
        if nl == -1:
            line, end = text[pos:], n
        else:
            line, end = text[pos:nl], nl
        if line.strip():
            if seg_start is None:
                seg_start = pos
            lines.append(line)
            seg_end = end
        elif lines:
            paragraphs.append(
                {"text": "\n".join(lines), "start": seg_start, "end": seg_end}
            )
            lines, seg_start = [], None
        if nl == -1:
            break
        pos = nl + 1
    if lines:
        paragraphs.append(
            {"text": "\n".join(lines), "start": seg_start, "end": seg_end}
        )
    return paragraphs


def _split_by_sentences(text: str, max_chars: int) -> list[str]:
    """将长文本按句末标点切成 ≤max_chars 的片段（无标点则按字符硬切）。"""
    pieces: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            cut = -1
            for i in range(end - 1, start - 1, -1):
                if text[i] in _SENTENCE_END:
                    cut = i + 1
                    break
            if cut > start:
                end = cut
        pieces.append(text[start:end])
        start = end
    return pieces


def _pre_split_long(
    paragraphs: list[dict[str, Any]], max_chars: int
) -> list[dict[str, Any]]:
    """将超过 max_chars 的段落按句切分，保持偏移连续。"""
    out: list[dict[str, Any]] = []
    for para in paragraphs:
        text = para["text"]
        if len(text) <= max_chars:
            out.append(para)
            continue
        pos = para["start"]
        for piece in _split_by_sentences(text, max_chars):
            out.append({"text": piece, "start": pos, "end": pos + len(piece)})
            pos += len(piece)
    return out


def _extract_keywords(text: str, top_n: int = 3) -> list[str]:
    """简单关键词提取：CJK 连续串的双字词频统计（过滤停用字）。"""
    counter: Counter[str] = Counter()
    for run in _CJK_RUN_RE.findall(text):
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram[0] in _STOP_CHARS or bigram[1] in _STOP_CHARS:
                continue
            counter[bigram] += 1
    return [word for word, _ in counter.most_common(top_n)]


def _tags_for_segments(segments: list[dict[str, Any]]) -> list[str]:
    """片段标签：Markdown 标题 + 高频关键词，去重并限制数量。"""
    texts = [seg["text"] for seg in segments]
    tags: list[str] = []
    for text in texts:
        for line in text.split("\n"):
            match = _HEADING_RE.match(line.strip())
            if match and match.group(1).strip():
                tags.append(match.group(1).strip())
    tags.extend(_extract_keywords("\n".join(texts)))
    result: list[str] = []
    for tag in tags:
        if tag not in result and len(result) < 5:
            result.append(tag)
    return result


def _assemble_chunk(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """将段落（含可能的重叠尾巴）组装为输出片段。"""
    return {
        "text": "\n".join(seg["text"] for seg in segments),
        "tags": _tags_for_segments(segments),
        "start": segments[0]["start"],
        "end": segments[-1]["end"],
    }


def chunk_document(
    content_text: str,
    min_chars: int = CHUNK_MIN,
    max_chars: int = CHUNK_MAX,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """按段落将文档切分为知识片段，相邻块带字符重叠（用于检索连续性）。"""
    paragraphs = _split_paragraphs(content_text)
    if not paragraphs:
        return []
    paragraphs = _pre_split_long(paragraphs, max_chars)

    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_len = 0
    prev_chunk: dict[str, Any] | None = None

    index = 0
    while index < len(paragraphs):
        para = paragraphs[index]
        # 新块开头补上一块末尾的 overlap 字符（仅一次，然后重新处理同一段落）
        if prev_chunk is not None and not current:
            tail_len = min(overlap, prev_chunk["end"] - prev_chunk["start"])
            if tail_len > 0:
                tail = {
                    "text": prev_chunk["text"][-tail_len:],
                    "start": prev_chunk["end"] - tail_len,
                    "end": prev_chunk["end"],
                    "_overlap": True,
                }
                current.append(tail)
                current_len += len(tail["text"])
            prev_chunk = None

        # 若当前块仅含重叠尾巴（无真实段落），无论多大都追加，保证每轮推进一个段落
        has_real = any(not seg.get("_overlap") for seg in current)
        if current_len + len(para["text"]) <= max_chars or not has_real:
            current.append(para)
            current_len += len(para["text"])
            index += 1
        else:
            chunks.append(_assemble_chunk(current))
            prev_chunk = {
                "text": "\n".join(seg["text"] for seg in current),
                "start": current[0]["start"],
                "end": current[-1]["end"],
            }
            # 不推进 index：同一段落在下一轮（空 current + 重叠尾巴）重新处理
            current, current_len = [], 0

    if current:
        chunks.append(_assemble_chunk(current))

    return chunks
