# backend/scripts/verify_document_parse_sse.py
"""文档解析 SSE 端点验证脚本（不发起真实 HTTP）。

运行方式（在 backend/ 下）：
    python scripts/verify_document_parse_sse.py

覆盖 POST /api/v1/documents/{id}/parse 的 SSE 契约：
- 流开始前置 document.status = "parsing"；
- 小文档（≤ SAFE_SINGLE_UNIT_CHARS）触发整篇单单元解析（single_unit=True），
  产出 progress 帧（start / done，index=0、total=1、label=全文）；
- 产出 done 帧（合并候选）；
- 流结束 document.status = "parsed" 并暂存 parse_result_json。

resolve_llm 被 monkeypatch 为返回 stub LLMClient（duck-typed chat_completion
返回合法抽取 JSON），全程不发起真实网络请求。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

# Windows 控制台可能为 GBK：强制 UTF-8 输出避免编码异常
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models import Base, Document  # noqa: E402

_passed = 0
_failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [OK] {label}")
    else:
        _failed += 1
        print(f"  [FAIL] {label}  {detail}")


VALID_RESULT = {
    "style": {"叙事视角": "第一人称"},
    "characters": [{"name": "主角", "description": "来自异世界"}],
    "worldSettings": [],
    "terms": [],
    "keyEvents": [],
}


class _StubClient:
    """模拟 LLMClient：每次调用返回合法抽取 JSON（不发起真实请求）。"""

    async def chat_completion(self, messages, **kwargs) -> str:
        return json.dumps(VALID_RESULT, ensure_ascii=False)


class _StubProvider:
    """模拟 ModelProvider：models_json 为空（supports_1m_context 缺省 False）。"""

    models_json: list[dict] = []


CHAPTER_TEXT = (
    "第一章 初入江湖\n他踏入城门。\n\n"
    "第二章 故人\n旧友来访。\n\n"
    "第三章 抉择\n他做出了决定。\n"
)


async def main() -> None:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_doc_parse_sse_")
    os.close(fd)
    engine = create_async_engine("sqlite+aiosqlite:///" + path.replace("\\", "/"))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_get_db():
            async with maker() as session:
                yield session

        from app.api.v1 import documents as documents_api

        test_app = FastAPI()
        test_app.include_router(documents_api.router)
        test_app.dependency_overrides[get_db] = override_get_db

        # stub resolve_llm：返回带 client 与 provider.models_json 的解析结果（duck-typed）
        async def _fake_resolve_llm(db, project_id=None, **kwargs):
            class _Resolved:
                client = _StubClient()
                provider = _StubProvider()

            return _Resolved()

        documents_api.resolve_llm = _fake_resolve_llm

        # 准备一条文档记录（含多章标题，但字符数 ≤ SAFE_SINGLE_UNIT_CHARS →
        # 触发整篇单单元解析）
        async with maker() as db:
            doc = Document(
                project_id="proj-1",
                filename="测试小说.txt",
                file_type="txt",
                file_size=len(CHAPTER_TEXT),
                content_text=CHAPTER_TEXT,
                status="pending",
                parse_threshold="medium",
                require_manual_confirm=True,
                imported_at="",
            )
            db.add(doc)
            await db.commit()
            document_id = doc.id

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as ac:
            resp = await ac.post(f"/api/v1/documents/{document_id}/parse", json={"threshold": "medium"})
            body = resp.text
            status = resp.status_code

        check("HTTP 200", status == 200, f"status={status}")
        check("content-type 为 SSE", "text/event-stream" in resp.headers.get("content-type", ""), resp.headers.get("content-type", ""))

        # 解析 SSE 帧
        frames: list[tuple[str, dict]] = []
        for frame in body.split("\n\n"):
            if not frame.strip():
                continue
            event, data = "", ""
            for line in frame.split("\n"):
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
            if data:
                frames.append((event, json.loads(data)))

        events = [e for e, _ in frames]
        check("含 done 事件", "done" in events, f"events={events}")
        progress = [d for e, d in frames if e == "progress"]
        starts = [d for d in progress if d["status"] == "start"]
        dones = [d for d in progress if d["status"] == "done"]
        check("1 个 start 帧（整篇单单元）", len(starts) == 1, f"starts={len(starts)}")
        check("1 个 done 帧", len(dones) == 1, f"dones={len(dones)}")
        check("帧含 total=1", all(d["total"] == 1 for d in progress), f"total={[d['total'] for d in progress]}")
        check("label 为「全文」", starts and starts[0]["label"] == "全文", f"label={[d['label'] for d in starts]}")
        check("done 帧为整篇单帧", dones and dones[0]["index"] == 0, f"indices={[d['index'] for d in dones]}")
        check("done 帧含 result 计数", all(d.get("result", {}).get("characters") == 1 for d in dones), "result.characters 应=1")

        done_frames = [d for e, d in frames if e == "done"]
        candidates = done_frames[0]["candidates"]
        check("done 帧含合并候选", len(candidates) == 2, f"candidates={len(candidates)}")
        check("候选含 style 卡", any(c["card_type"] == "style" for c in candidates), "")
        check("候选含 character 卡", any(c["card_type"] == "character" for c in candidates), "")

        # 落库状态
        async with maker() as db:
            doc = await db.get(Document, document_id)
            check("状态置为 parsed", doc.status == "parsed", f"status={doc.status}")
            stored = doc.parse_result_json or {}
            check("parse_result_json 已暂存", len(stored.get("candidates", [])) == 2, "")

    finally:
        await engine.dispose()

    print(f"\n结果：{_passed} 通过 / {_failed} 失败")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
