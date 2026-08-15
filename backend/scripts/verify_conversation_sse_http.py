# backend/scripts/verify_conversation_sse_http.py
"""对话消息发送 SSE HTTP 层验证脚本（docs/TECHv1.md §5.6 / §7.3；V1.1 §5.3）。

运行方式（在 backend/ 下）：
    python scripts/verify_conversation_sse_http.py

覆盖（ASGI 直接驱动，走真实依赖注入 + HTTP 响应体）：
- POST /projects/{project_id}/conversations 创建对话；
- POST /conversations/{conversation_id}/messages 触发流式回复，断言响应体为
  text/event-stream 且依次包含 start / delta×N / done 帧（前端 streamSSE 解析的格式）；
- 首次发送自动插入「模型已切换」系统消息（V1.1 §5.3，会话未配置模型时）；
- 流式完成后 GET /conversations/{conversation_id} 已持久化
  system（切换提示）+ user + assistant 三条消息；
- 解析失败（无提供商）时发送消息 → 400。

LLM 解析（resolve_llm）通过替换模块属性注入 MockClient（不发起真实网络请求）。
所有断言通过时打印 OK 汇总并以退出码 0 结束（使用临时 SQLite，不影响正式库）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# Windows 控制台可能为 GBK：强制 UTF-8 输出避免编码异常
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models import AppConfig, Base, ModelProvider, Project  # noqa: E402
from app.services.llm.prompts import (  # noqa: E402
    GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY,
)
from app.services.prompt_template import ensure_system_default_template  # noqa: E402

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


class MockClient:
    """模拟 LLM 客户端：chat_completion_stream 逐段产出正文。"""

    async def chat_completion_stream(self, messages, **kwargs):
        for chunk in ["你好！", "这是", "流式", "回复。"]:
            yield chunk


def parse_sse(body: str) -> list[tuple[str, str]]:
    """解析 SSE 文本：返回 [(event, data), ...]。"""
    frames: list[tuple[str, str]] = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        event = "message"
        data = ""
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        frames.append((event, data))
    return frames


async def main() -> None:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_conv_sse_test_")
    os.close(fd)
    engine = create_async_engine("sqlite+aiosqlite:///" + path.replace("\\", "/"))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_get_db():
            async with maker() as session:
                yield session

        from app.api.v1 import conversations as conv_module
        from app.api.v1.conversations import router as conv_router
        from app.services.llm.resolve import NoLLMConfigError, ResolvedLLM

        def make_resolved() -> ResolvedLLM:
            provider = ModelProvider(
                id="mock-provider", name="Mock提供商", type="custom"
            )
            return ResolvedLLM(
                provider=provider,
                provider_id=provider.id,
                model_id="mock-model",
                api_key="sk-mock",
                client=MockClient(),
            )

        async def fake_resolve_llm(db, **kwargs):
            return make_resolved()

        test_app = FastAPI()
        test_app.include_router(conv_router)
        test_app.dependency_overrides[get_db] = override_get_db
        # resolve_llm 在端点内直接调用（非 Depends），需替换模块属性
        conv_module.resolve_llm = fake_resolve_llm

        async with maker() as db:
            # 写入全局默认 AppConfig + 系统「自动模板」（系统提示词渲染所需）
            db.add(AppConfig(key=GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY, value=""))
            await db.commit()
            await ensure_system_default_template(db)

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # ---- 准备项目（conversations 路由不含项目创建，直接写库）+ 创建对话 ----
            async with maker() as db:
                proj = Project(title="测试书", genre="玄幻")
                db.add(proj)
                await db.commit()
                proj_id = proj.id
            check("项目已创建", bool(proj_id), str(proj_id))

            r = await client.post(
                f"/api/v1/projects/{proj_id}/conversations", json={"title": "对话A"}
            )
            check("创建对话 201", r.status_code == 201, str(r.status_code))
            conv_id = r.json()["id"]
            check("对话默认标题", r.json()["title"] == "对话A", str(r.json().get("title")))

            # ---- 发送消息（SSE 流式；会话未配置模型 → 自动插入「模型已切换」系统消息） ----
            r = await client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": "你好，帮我写一段开头"},
            )
            check("发送消息 200 text/event-stream", r.status_code == 200 and r.headers.get("content-type", "").startswith("text/event-stream"), f"{r.status_code} {r.headers.get('content-type')}")
            frames = parse_sse(r.text)
            events = [e for e, _ in frames]
            check("事件流含 start", "start" in events, str(events))
            check("事件流含 done", "done" in events, str(events))
            # 每帧 data 为 JSON，content 键为增量正文（与前端 streamSSE 解析一致）
            import json

            delta_contents = [json.loads(d)["content"] for e, d in frames if e == "delta"]
            check("事件流含 ≥1 个 delta", len(delta_contents) >= 1, str(len(delta_contents)))
            joined = "".join(delta_contents)
            check("delta 增量拼接=完整回复", joined == "你好！这是流式回复。", joined)
            done_data = next((d for e, d in frames if e == "done"), "{}")
            check("done 携带 message_id", "message_id" in done_data, done_data)

            # ---- 流式完成后消息持久化：切换提示 + user + assistant ----
            r = await client.get(f"/api/v1/conversations/{conv_id}")
            msgs = r.json().get("messages", [])
            roles = [m["role"] for m in msgs]
            check("持久化 system+user+assistant 三条", roles == ["system", "user", "assistant"], str(roles))
            switch_msg = msgs[0]
            check("切换提示内容正确", switch_msg["content"] == "模型已切换为：Mock提供商 · mock-model", str(switch_msg.get("content")))
            assistant = next((m for m in msgs if m["role"] == "assistant"), {})
            check("assistant 内容为完整回复", assistant.get("content") == "你好！这是流式回复。", str(assistant.get("content"))[:40])
            check("assistant metadata 记录模型", assistant.get("metadata", {}).get("model") == "mock-model", str(assistant.get("metadata")))
            # 会话已记住当前模型（§5.3）
            check("会话记住当前模型", r.json().get("current_provider_id") == "mock-provider" and r.json().get("current_model_id") == "mock-model", str(r.json().get("current_model_id")))

            # ---- 解析失败（无提供商）→ 400 ----
            async def raise_no_config(db, **kwargs):
                raise NoLLMConfigError("请先配置模型提供商")

            conv_module.resolve_llm = raise_no_config
            r = await client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": "应该失败"},
            )
            check("无提供商发送 400", r.status_code == 400, str(r.status_code))
    finally:
        await engine.dispose()
        if os.path.exists(path):
            try:
                os.remove(path)
            except PermissionError:
                pass  # Windows 偶发连接未完全释放，忽略清理失败

    print(f"\n结果：{_passed} 通过，{_failed} 失败")
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
