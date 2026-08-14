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
from typing import Any, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import EmbeddingFunction

from ...config import settings
from ..embedding.embedder import LocalHashEmbedder


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
