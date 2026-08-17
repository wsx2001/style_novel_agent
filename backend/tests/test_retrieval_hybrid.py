# backend/tests/test_retrieval_hybrid.py
"""Chroma 检索封装（HybridRetriever）的回归测试。

主要覆盖 `upsert_snippets` 在 Windows 上必须分批写入的行为 —— chroma-hnswlib
0.7.6 在 Windows 下单次 upsert ≥ ~100 条时会触发 MSVCP140.dll 原生段错误
（0xC0000005），从而拖垮整个 uvicorn 进程。本测试以 N=280 的真实负载写入
临时 Chroma 目录，断言 `upsert_snippets` 不再一次性喂入 ≥100 条。
"""
from __future__ import annotations

import tempfile
import uuid
from typing import Any

import pytest

from app.services.embedding.embedder import LocalHashEmbedder
from app.services.retrieval.hybrid import (
    UPSERT_BATCH_SIZE,
    HybridRetriever,
)


pytestmark = pytest.mark.anyio


class _RecordingCollection:
    """记录每次 `upsert` 调用 payload 大小的最小桩集合。"""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def upsert(self, *, ids, embeddings, documents, metadatas) -> None:
        del embeddings, documents, metadatas
        self.calls.append(list(ids))


class _StubClient:
    """仅实现 HybridRetriever 需要的两个方法。"""

    def __init__(self) -> None:
        self.collections: dict[str, _RecordingCollection] = {}

    def get_or_create_collection(self, name: str, **_kwargs: Any):
        col = self.collections.setdefault(name, _RecordingCollection())
        return col


class _ConstantEmbedder:
    """固定 256 维向量，避免真实模型依赖。"""

    dim = 256

    async def embed_texts(self, texts):
        return [[0.1] * self.dim for _ in texts]


async def test_upsert_snippets_batches_under_threshold() -> None:
    """280 条一次写入必须被切到每批 ≤ UPSERT_BATCH_SIZE。"""
    retriever = HybridRetriever(
        persist_dir=tempfile.mkdtemp(prefix="ff_hybrid_"),
        embedder=_ConstantEmbedder(),
    )
    # 注入桩客户端，避免命中真实 Chroma 路径
    stub = _StubClient()
    retriever._client = stub  # type: ignore[attr-defined]

    project_id = str(uuid.uuid4())
    n = 280
    snippets = [
        {
            "id": f"doc:{i}",
            "text": f"片段 {i}：用于回归测试的占位文本。",
            "tags": ["regression"],
            "document_id": "doc-1",
            "card_id": None,
        }
        for i in range(n)
    ]
    written = await retriever.upsert_snippets(project_id, snippets)

    assert written == n
    col = stub.collections[f"project_{project_id}"]
    assert col.calls, "expected at least one upsert call"
    # 关键断言：单批长度必须 ≤ UPSERT_BATCH_SIZE
    for ids in col.calls:
        assert len(ids) <= UPSERT_BATCH_SIZE, (
            f"upsert batch size {len(ids)} exceeds safety threshold "
            f"{UPSERT_BATCH_SIZE} (Windows chroma-hnswlib segfault)"
        )
    # 所有 id 都必须被写过一次（顺序保留）
    flattened = [sid for ids in col.calls for sid in ids]
    assert flattened == [s["id"] for s in snippets]


async def test_upsert_snippets_empty_returns_zero() -> None:
    """空入参短路：不应触发 embedder，也不应调用 collection。"""
    retriever = HybridRetriever(
        persist_dir=tempfile.mkdtemp(prefix="ff_hybrid_"),
        embedder=_ConstantEmbedder(),
    )
    stub = _StubClient()
    retriever._client = stub  # type: ignore[attr-defined]
    n = await retriever.upsert_snippets(str(uuid.uuid4()), [])
    assert n == 0
    assert stub.collections == {}


async def test_upsert_snippets_below_threshold_single_call() -> None:
    """N < UPSERT_BATCH_SIZE 时只产生一次 upsert 调用。"""
    retriever = HybridRetriever(
        persist_dir=tempfile.mkdtemp(prefix="ff_hybrid_"),
        embedder=_ConstantEmbedder(),
    )
    stub = _StubClient()
    retriever._client = stub  # type: ignore[attr-defined]

    project_id = str(uuid.uuid4())
    snippets = [
        {"id": f"doc:{i}", "text": f"t{i}", "tags": [], "document_id": "", "card_id": None}
        for i in range(10)
    ]
    await retriever.upsert_snippets(project_id, snippets)
    col = stub.collections[f"project_{project_id}"]
    assert len(col.calls) == 1
    assert len(col.calls[0]) == 10


def test_upsert_batch_size_is_below_known_segfault_threshold() -> None:
    """守门常量：不要在不知情的情况下把阈值调到 ≥100。"""
    assert UPSERT_BATCH_SIZE < 100, (
        "UPSERT_BATCH_SIZE must stay below the Windows chroma-hnswlib "
        "single-call segfault threshold (~100)"
    )


def test_local_hash_embedder_is_default() -> None:
    """HybridRetriever 默认 embedder 必须是本地哈希回退（无网络依赖）。"""
    retriever = HybridRetriever(persist_dir=tempfile.mkdtemp(prefix="ff_hybrid_"))
    assert isinstance(retriever._embedder, LocalHashEmbedder)