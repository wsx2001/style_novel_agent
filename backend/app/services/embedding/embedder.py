# backend/app/services/embedding/embedder.py
"""文本向量化（docs/TECH.md §6.1）。

- Embedder：调用 OpenAI-compatible embeddings 端点（如 text-embedding-3-small），
  base_url / api_key / model 从用户配置动态传入；
- LocalHashEmbedder：无 API Key 时的本地回退，字符 n-gram 哈希向量
  （确定性、零依赖，仅用于离线体验，替换为真实 embedding 模型即可升级）。

统一接口：`async embed_texts(texts: list[str]) -> list[list[float]]`。
"""
from __future__ import annotations

import hashlib
import math

from openai import AsyncOpenAI

from ..llm.client import DEFAULT_TIMEOUT

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 32


class Embedder:
    """远程文本向量化：批量调用 OpenAI-compatible embeddings 接口。"""

    def __init__(
        self, api_key: str, base_url: str, model: str | None = None
    ) -> None:
        self.model = model or DEFAULT_EMBEDDING_MODEL
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=DEFAULT_TIMEOUT,
            max_retries=1,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """将文本列表向量化，返回与输入同序的向量列表（批量调用）。"""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            response = await self._client.embeddings.create(
                model=self.model, input=batch
            )
            # 按 index 排序保证与输入同序
            rows = sorted(response.data, key=lambda item: item.index)
            vectors.extend([row.embedding for row in rows])
        return vectors


class LocalHashEmbedder:
    """本地离线嵌入：字符 1~3-gram 哈希为固定维度向量（L2 归一化）。

    确定性（blake2b，非进程随机），适合无网络时的功能验证与本地检索。
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for n in (1, 2, 3):
            if len(text) < n:
                continue
            for i in range(len(text) - n + 1):
                gram = text[i : i + n]
                digest = hashlib.blake2b(
                    gram.encode("utf-8"), digest_size=8
                ).hexdigest()
                h = int(digest, 16)
                vector[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]
