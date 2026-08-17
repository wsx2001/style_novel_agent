# backend/tests/test_document_import.py
"""文档确认导入回归测试：远程 embedding 失败时回退本地哈希向量，导入不中断。

覆盖 bugfix：
1. 提供商有 Key 但缺少 embedding 模型（Error code: 404）时，confirm_import
   原先整体 502、卡片无法入库；修复后在 FallbackEmbedder 内部降级，且只使用
   一个 HybridRetriever / Chroma 客户端（同路径二次打开会触发底层段错误，
   表现为前端「Network Error」）；
2. 解析结果 manual_confirm 存 null 时 GET /parse-result 不 500；
3. Chroma 级写入失败仍抛 502，卡片不落库。
"""
from __future__ import annotations

import uuid

import pytest

import app.api.v1.documents as documents_api
from app.config import settings
from app.models import Document, KnowledgeCard, KnowledgeSnippet, Project
from app.schemas.card import ConfirmImportCard, ConfirmImportRequest
from app.services.embedding.embedder import FallbackEmbedder, LocalHashEmbedder

pytestmark = pytest.mark.anyio


async def _fake_resolve_embedding(*args, **kwargs):
    """模拟解析出提供商 + Key（走远程 Embedder 分支，而非 NoLLMConfigError 回退）。"""
    return (
        type("Provider", (), {"base_url": "https://mock.example/v1"})(),
        "sk-dummy",
    )


def _make_document(project_id: str, text: str, manual_confirm: bool = True) -> Document:
    return Document(
        id=str(uuid.uuid4()),
        project_id=project_id,
        filename="test.md",
        file_type="md",
        file_size=10,
        content_text=text,
        status="parsed",
        parse_threshold="medium",
        require_manual_confirm=manual_confirm,
        imported_at="",
        parse_result_json={"candidates": [], "threshold": "medium"},
    )


def _make_payload(document_id: str) -> ConfirmImportRequest:
    return ConfirmImportRequest(
        cards=[
            ConfirmImportCard(
                card_type="character",
                title="阿离",
                content_json={"身份": "剑修"},
                tags=["主角"],
                snippet_ids=[f"{document_id}:0"],
            )
        ]
    )


async def test_parse_result_payload_defaults_none_manual_confirm(session_factory):
    """GET /parse-result 对存量数据 manual_confirm=None 时回退文档级默认，不抛 500。

    bugfix：解析请求未传 manual_confirm 时 parse_result_json 会存 null，而
    ParseResultRead.manual_confirm 为 bool（非空），响应校验直接 500——重启后
    前端「查看解析结果」即失败。修复后回退 document.require_manual_confirm。
    """
    project = Project(id=str(uuid.uuid4()), title="测试项目")
    document = _make_document(project.id, "测试")
    document.parse_result_json = {
        "candidates": [
            {
                "card_type": "character",
                "title": "阿离",
                "content_json": {"身份": "剑修"},
                "snippet_ids": [],
            }
        ],
        "threshold": "medium",
        "manual_confirm": None,  # 解析请求未传该字段时的历史存量数据
        "extracted_at": "2026-08-16T00:00:00",
    }
    async with session_factory() as db:
        db.add_all([project, document])
        await db.commit()
        payload = await documents_api.get_document_parse_result(document.id, db)

    assert payload["manual_confirm"] is True  # 而非 None（None 会让响应校验 500）
    assert payload["candidates"][0]["title"] == "阿离"


async def test_fallback_embedder_returns_remote_when_ok():
    """FallbackEmbedder：远程成功时原样返回远程向量，不触发回退。"""

    class _RemoteOk:
        async def embed_texts(self, texts):
            return [[1.0, 2.0], [3.0, 4.0]]

    emb = FallbackEmbedder(remote=_RemoteOk(), local=LocalHashEmbedder())
    vectors = await emb.embed_texts(["a", "b"])
    assert vectors == [[1.0, 2.0], [3.0, 4.0]]


async def test_fallback_embedder_falls_back_to_local_on_remote_error():
    """FallbackEmbedder：远程抛 404 时回退本地哈希向量（256 维、确定性）。"""

    class _RemoteFail:
        async def embed_texts(self, texts):
            raise RuntimeError("Error code: 404")

    emb = FallbackEmbedder(remote=_RemoteFail(), local=LocalHashEmbedder())
    vectors = await emb.embed_texts(["hello", "世界"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 256
    # 本地哈希确定性：同一输入两次结果一致（且非零向量）
    again = await emb.embed_texts(["hello", "世界"])
    assert again == vectors


class _EmbedderRecordingRetriever:
    """捕获 embedder 并驱动其 embed_texts 的 HybridRetriever 替身。

    验证 confirm_import 只构造一个 retriever（不回退新建 Chroma 客户端——
    同路径二次打开会段错误），远程失败由 FallbackEmbedder 在 embed_texts 内兜底。
    """

    instances = 0

    def __init__(self, *args, **kwargs) -> None:
        type(self).instances += 1
        self.embedder = kwargs.get("embedder")

    async def upsert_snippets(self, project_id, snippets) -> int:
        await self.embedder.embed_texts([s["text"] for s in snippets])
        return len(snippets)


async def test_confirm_import_falls_back_to_local_embedding_on_remote_failure(
    session_factory, monkeypatch
):
    """远程 embedding 抛 404 时，单 retriever 内回退本地哈希完成导入，不 502。"""
    _EmbedderRecordingRetriever.instances = 0

    class _RemoteFailEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def embed_texts(self, texts):
            raise RuntimeError("Error code: 404")

    # 远程必败 + retriever 捕获 embedder + 解析出 Key（走远程 Embedder 分支）
    monkeypatch.setattr(documents_api, "Embedder", _RemoteFailEmbedder)
    monkeypatch.setattr(documents_api, "HybridRetriever", _EmbedderRecordingRetriever)
    monkeypatch.setattr(documents_api, "resolve_embedding", _fake_resolve_embedding)

    project = Project(id=str(uuid.uuid4()), title="测试项目")
    document = _make_document(project.id, "这是第一章的设定：主角名为阿离，职业是剑修。")
    payload = _make_payload(document.id)

    async with session_factory() as db:
        db.add_all([project, document])
        await db.commit()
        response = await documents_api.confirm_import(document.id, payload, db)

    # 关键回归：全程只建一个 retriever（FallbackEmbedder 内部兜底，不新建 Chroma 客户端）
    assert _EmbedderRecordingRetriever.instances == 1
    assert response["snippet_count"] == 1
    assert response["cards"][0].title == "阿离"

    # 导入成功后文档置 imported、片段与卡片已入库、解析结果暂存未丢失
    async with session_factory() as db:
        doc = await db.get(Document, document.id)
        assert doc.status == "imported"
        assert doc.parse_result_json is not None
        assert await db.get(KnowledgeSnippet, f"{document.id}:0") is not None
        assert await db.get(KnowledgeCard, response["cards"][0].id) is not None


async def test_confirm_import_writes_local_hash_to_real_chroma(
    session_factory, tmp_data_dir, monkeypatch
):
    """端到端：无提供商时用本地哈希向量写入真实 Chroma，导入成功。

    回归 bugfix：chromadb 1.5.9 的 Rust 写入路径在 Windows 上段错误崩溃（前端
    表现为「Network Error」）；requirements 已锁定 0.6.x。此测试走真实
    Chroma 写入路径，一旦写入崩溃（段错误）pytest 进程将直接挂掉。
    """
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_data_dir / "chroma"))

    project = Project(id=str(uuid.uuid4()), title="测试项目")
    document = _make_document(project.id, "这是第一章的设定：主角名为阿离，职业是剑修。")
    payload = _make_payload(document.id)

    async with session_factory() as db:
        db.add_all([project, document])
        await db.commit()
        response = await documents_api.confirm_import(document.id, payload, db)

    assert response["snippet_count"] == 1
    async with session_factory() as db:
        doc = await db.get(Document, document.id)
        assert doc.status == "imported"


async def test_confirm_import_chroma_write_failure_raises_502(
    session_factory, monkeypatch
):
    """Chroma 级写入失败（如维度不一致 / 磁盘错误）仍抛 502「embedding 存储失败」。"""
    _EmbedderRecordingRetriever.instances = 0

    class _AlwaysFailRetriever:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def upsert_snippets(self, project_id, snippets):
            raise RuntimeError("Error code: 404")

    monkeypatch.setattr(documents_api, "HybridRetriever", _AlwaysFailRetriever)
    monkeypatch.setattr(documents_api, "resolve_embedding", _fake_resolve_embedding)

    project = Project(id=str(uuid.uuid4()), title="测试项目")
    document = _make_document(project.id, "短文本，分一块。")
    payload = _make_payload(document.id)

    async with session_factory() as db:
        db.add_all([project, document])
        await db.commit()
        with pytest.raises(Exception) as exc_info:
            await documents_api.confirm_import(document.id, payload, db)
        assert "embedding 存储失败" in str(exc_info.value)
