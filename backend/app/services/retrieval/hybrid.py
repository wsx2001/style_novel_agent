# backend/app/services/retrieval/hybrid.py
"""Chroma 向量检索封装（docs/TECH.md §6.3 / §6.4）。

每个片段在 Chroma 中以 embedding + metadata 存储：
    metadata = {snippet_id, project_id, document_id, card_id, tags(JSON 字符串)}

embedder 参数：提供 `async embed_texts(texts) -> list[list[float]]` 的对象。
默认使用 LocalHashEmbedder（本地确定性向量，无网络可用）；接入真实 embedding
模型后传入 Embedder 实例即可升级为语义检索。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import EmbeddingFunction

from ...config import settings
from ..embedding.embedder import LocalHashEmbedder

logger = logging.getLogger(__name__)


class _UnusedEmbeddingFunction(EmbeddingFunction):
    """占位 embedding function：调用方总是显式传 embeddings，绝不应触发它。

    用于避免 Chroma 实例化默认 embedding function（ONNX 模型），保持纯显式向量写入。
    """

    def __init__(self) -> None:
        pass

    def __call__(self, input: Any) -> Any:
        raise RuntimeError("内部 embedding function 不应被调用，请直接传入 embeddings")


_UNUSED_EF = _UnusedEmbeddingFunction()


class HybridRetriever:
    """Chroma PersistentClient 的轻量封装：项目级 collection + snippet upsert/query。"""

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        embedder: Any = None,
    ) -> None:
        self._persist_dir = str(persist_dir or settings.chroma_persist_dir)
        self._embedder = embedder or LocalHashEmbedder()
        # 本地应用：关闭 Chroma 遥测，避免外部网络请求与日志噪音
        self._client = chromadb.PersistentClient(
            path=self._persist_dir,
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
        self._collections: dict[str, Any] = {}

    def _collection(self, project_id: str) -> Any:
        """获取（或创建）项目对应的 collection：project_{project_id}。"""
        name = f"project_{project_id}"
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name=name, embedding_function=_UNUSED_EF
            )
        return self._collections[name]

    async def upsert_snippets(
        self, project_id: str, snippets: list[dict[str, Any]]
    ) -> int:
        """批量生成 embedding 并写入项目 collection，返回写入条数。

        snippets 元素字段：id / text / tags / document_id / card_id。
        """
        if not snippets:
            return 0
        texts = [snip["text"] for snip in snippets]
        ids = [snip["id"] for snip in snippets]
        embeddings = await self._embedder.embed_texts(texts)
        metadatas = [
            {
                "snippet_id": snip["id"],
                "project_id": project_id,
                "document_id": snip.get("document_id") or "",
                "card_id": snip.get("card_id") or "",
                "tags": json.dumps(snip.get("tags") or [], ensure_ascii=False),
            }
            for snip in snippets
        ]
        collection = self._collection(project_id)
        collection.upsert(
            ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )
        return len(snippets)

    async def query_snippets(
        self, project_id: str, query_text: str, top_k: int = 10
    ) -> list[dict[str, Any]]:
        """将 query 文本向量化后检索 top_k 个相似片段，附带原始文本与 metadata。"""
        collection = self._collection(project_id)
        query_embedding = (await self._embedder.embed_texts([query_text]))[0]
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        items: list[dict[str, Any]] = []
        ids = result.get("ids") or [[]]
        documents = result.get("documents") or [[]]
        distances = result.get("distances") or [[]]
        metadatas = result.get("metadatas") or [[]]
        for i, sid in enumerate(ids[0]):
            meta = metadatas[0][i] or {}
            items.append(
                {
                    "id": sid,
                    "snippet_id": meta.get("snippet_id", sid),
                    "text": documents[0][i],
                    "distance": distances[0][i],
                    "card_id": meta.get("card_id") or None,
                    "document_id": meta.get("document_id") or None,
                    "tags": json.loads(meta.get("tags") or "[]"),
                }
            )
        return items

    async def recommend_cards(
        self,
        project_id: str,
        query_text: str,
        explicit_card_ids: list[str],
        top_n: int = 12,
        query_top_k: int = 20,
        snippets_per_card: int = 3,
    ) -> list[dict[str, Any]]:
        """检索尾部文本对应的片段，聚合推荐卡片并与显式卡片合并去重。

        （docs/TECH.md §6.5：章节续写/重写时，用尾部文本查 Chroma top_k 片段，
        按 card_id 聚合得到推荐卡片，与前端显式选择的卡片合并。）

        返回按 card_id 去重后的卡片引用列表：显式卡片在前，推荐卡片按相似度
        （最佳距离）升序，总条数不超过 top_n。每项
            {"card_id": str, "snippets": list[str]}   # 最多 snippets_per_card 条原文片段
        检索失败或 query_text 为空时回退为仅返回显式卡片，不中断生成流程。
        """
        explicit = [cid for cid in explicit_card_ids if cid]
        snippets_by_card: dict[str, list[str]] = {cid: [] for cid in explicit}

        grouped: dict[str, list[dict[str, Any]]] = {}
        if query_text and query_text.strip():
            try:
                snippets = await self.query_snippets(
                    project_id, query_text.strip(), top_k=query_top_k
                )
            except Exception:
                logger.warning("Chroma 检索失败，仅使用显式卡片（project=%s）", project_id)
                snippets = []
            for snip in snippets:
                cid = snip.get("card_id")
                if not cid:
                    continue
                grouped.setdefault(cid, []).append(snip)
            # 命中片段补充到对应卡片（含显式卡片），供 Prompt 引用原文
            for cid, snips in grouped.items():
                snippets_by_card.setdefault(cid, []).extend(
                    s["text"] for s in snips[:snippets_per_card]
                )
        # 推荐卡片按最佳距离升序（距离越小越相似）
        recommended = sorted(
            grouped, key=lambda cid: min(s["distance"] for s in grouped[cid])
        )

        order: list[str] = []
        for cid in explicit:  # 显式卡片全部保留（用户选择，不裁剪）
            if cid not in order:
                order.append(cid)
        for cid in recommended:
            if len(order) >= top_n:
                break
            if cid not in order:
                order.append(cid)

        return [
            {"card_id": cid, "snippets": snippets_by_card.get(cid, [])}
            for cid in order
        ]
