# backend/scripts/verify_conversation.py
"""对话功能验证脚本（docs/TECHv1.md §4.4 / §5.6 / §7.3）。

运行方式（在 backend/ 下）：
    python scripts/verify_conversation.py

覆盖：
- schema 别名：ConversationRead / ConversationCreate 对外键 model_config；
- 对话 CRUD（create/list/get/update/delete）与项目归属 / 章节归属 / 模板存在性校验；
- get_messages 时间正序；
- send_message 流式对话：SSE 帧序列（start/delta/done）、系统提示词渲染
  （{{PROJECT_INFO}}/{{USER_INPUT}} 等占位符）、user/assistant 消息持久化与完整内容；
- send_message 错误路径：LLM 抛异常时产出 error 帧且不落 assistant 消息。
所有断言通过时打印 OK 汇总并以退出码 0 结束（使用临时 SQLite，不影响正式库）。
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

from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models import (  # noqa: E402
    AppConfig,
    Base,
    Chapter,
    Conversation,
    Message,
    Project,
    PromptTemplate,
)
from app.schemas.conversation import (  # noqa: E402
    ConversationCreate,
    ConversationDetailRead,
    ConversationRead,
    MessageRead,
    MessageSendRequest,
)
from app.services.conversation import (  # noqa: E402
    ConversationNotFound,
    ConversationValidationError,
    ProjectNotFound,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_messages,
    list_conversations,
    send_message,
    update_conversation,
)
from app.services.llm.prompts import (  # noqa: E402
    GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY,
    get_effective_system_prompt,
)

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
    """模拟 LLM 客户端：流式产出固定增量，可配置抛异常；记录每次调用的 messages/params。"""

    def __init__(self, chunks: list[str] | None = None, error: Exception | None = None) -> None:
        self.chunks = chunks or ["你好，", "我是助手。"]
        self.error = error
        self.calls: list[tuple[list[dict], dict]] = []

    async def chat_completion_stream(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield chunk


class MockConfig:
    model = "mock-model"


async def _seed(db, title="测试项目"):
    """构造项目 + 章节 + 模板，返回 (project, chapter, template)。"""
    proj = Project(title=title, description="一个测试项目", genre="玄幻")
    db.add(proj)
    await db.flush()
    chap = Chapter(project_id=proj.id, title="第一章", content="山巅有一棵老松。")
    db.add(chap)
    tpl = PromptTemplate(
        name="对话模板",
        content="项目：{{PROJECT_INFO}}\n用户输入：{{USER_INPUT}}\n章节：{{CURRENT_CHAPTER}}\n知识库：{{KNOWLEDGE_BASE}}",
        scope="global",
        is_system=True,
    )
    db.add(tpl)
    await db.commit()
    return proj, chap, tpl


async def test_schemas(db) -> None:
    print("[1] schema 别名（model_config 对外键）")
    create = ConversationCreate.model_validate(
        {"title": "对话A", "model_config": {"depth": "high"}}
    )
    dumped = create.model_dump(by_alias=True)
    check("create 接受 model_config 键", dumped.get("model_config") == {"depth": "high"}, str(dumped))
    check("create 缺省 model_config=None", ConversationCreate.model_validate({}).model_dump(by_alias=True).get("model_config") is None)

    msg = Message(conversation_id="x", role="user", content="你好",
                  message_metadata={"model": "gpt-4o"})
    db.add(msg)
    await db.flush()  # 触发 id / created_at 默认值
    msg_read = MessageRead.model_validate(msg)
    check("MessageRead 序列化键为 metadata", msg_read.model_dump(by_alias=True).get("metadata") == {"model": "gpt-4o"})
    send = MessageSendRequest.model_validate({"content": "继续写"})
    check("MessageSendRequest content 解析", send.content == "继续写")


async def test_crud(db) -> None:
    print("[2] 对话 CRUD 与校验")
    proj, chap, tpl = await _seed(db)

    conv = await create_conversation(db, proj.id, title="初始对话")
    check("create 默认 model_config", conv.model_config == {"depth": "auto", "temperature": 0.7, "max_tokens": 2048}, str(conv.model_config))
    check("create 默认 title 新对话", conv.title == "初始对话")

    conv2 = await create_conversation(
        db, proj.id, title="带章节", chapter_id=chap.id,
        model_config={"depth": "medium", "temperature": 0.5, "max_tokens": 1024},
        system_prompt_template_id=tpl.id,
    )
    check("create 带章节与模板", conv2.chapter_id == chap.id and conv2.system_prompt_template_id == tpl.id)
    check("create model_config 透传", conv2.model_config.get("depth") == "medium", str(conv2.model_config))

    try:
        await create_conversation(db, "no-such-project")
        check("项目不存在抛 ProjectNotFound", False)
    except ProjectNotFound:
        check("项目不存在抛 ProjectNotFound", True)

    # 章节属于其它项目
    other_proj = Project(title="其它项目")
    db.add(other_proj)
    await db.flush()
    other_chap = Chapter(project_id=other_proj.id, title="别人章节")
    db.add(other_chap)
    await db.commit()
    try:
        await create_conversation(db, proj.id, chapter_id=other_chap.id)
        check("章节不属于该项目抛校验错误", False)
    except ConversationValidationError:
        check("章节不属于该项目抛校验错误", True)

    try:
        await create_conversation(db, proj.id, system_prompt_template_id="no-such-tpl")
        check("模板不存在抛校验错误", False)
    except ConversationValidationError:
        check("模板不存在抛校验错误", True)

    lst = await list_conversations(db, proj.id)
    check("list 项目下对话 = 2", len(lst) == 2, str(len(lst)))
    lst_other = await list_conversations(db, other_proj.id)
    check("list 过滤项目 = 0", len(lst_other) == 0, str(len(lst_other)))

    got = await get_conversation(db, conv.id)
    check("get by id", got.id == conv.id)
    check("get 含消息集合", got.messages == [])
    try:
        await get_conversation(db, "no-such-id")
        check("get 不存在抛 NotFound", False)
    except ConversationNotFound:
        check("get 不存在抛 NotFound", True)

    u = await update_conversation(db, conv.id, title="改名", model_config={"depth": "high", "temperature": 0.3, "max_tokens": 4096})
    check("update title/model_config", u.title == "改名" and u.model_config.get("depth") == "high", str(u.model_config))
    u2 = await update_conversation(db, conv.id, system_prompt_override="临时覆盖：{{USER_INPUT}}")
    check("update 会话覆盖", u2.system_prompt_override == "临时覆盖：{{USER_INPUT}}")
    u3 = await update_conversation(db, conv.id, system_prompt_template_id=tpl.id)
    check("update 会话模板", u3.system_prompt_template_id == tpl.id)
    try:
        await update_conversation(db, conv.id, system_prompt_template_id="bad")
        check("update 模板不存在抛校验错误", False)
    except ConversationValidationError:
        check("update 模板不存在抛校验错误", True)
    try:
        await update_conversation(db, "no-such-id", title="x")
        check("update 不存在抛 NotFound", False)
    except ConversationNotFound:
        check("update 不存在抛 NotFound", True)

    await delete_conversation(db, conv2.id)
    deleted_ok = await end_raises(db, conv2.id)
    check("delete 后 get 抛 NotFound", deleted_ok)
    try:
        await delete_conversation(db, conv2.id)
        check("delete 不存在抛 NotFound", False)
    except ConversationNotFound:
        check("delete 不存在抛 NotFound", True)


async def end_raises(db, entity_id: str) -> bool:
    """封装：断言 delete 后 get 抛 NotFound。"""
    try:
        await get_conversation(db, entity_id)
        return False
    except ConversationNotFound:
        return True


async def test_send_message(db) -> None:
    print("[3] send_message 流式对话")
    proj, chap, tpl = await _seed(db, title="对话书")
    conv = await create_conversation(db, proj.id, title="流式对话", chapter_id=chap.id, system_prompt_template_id=tpl.id)

    client = MockClient()
    config = MockConfig()
    frames = [f async for f in send_message(db, conv.id, "帮我写一段", client=client, config=config)]

    check("帧数 >= 4", len(frames) >= 4, str(len(frames)))
    start = frames[0]
    check("首帧 start", start.startswith("event: start"), start)
    delta_texts = [f for f in frames if f.startswith("event: delta")]
    check("delta 帧含增量", any("你好，" in f for f in delta_texts) and any("我是助手。" in f for f in delta_texts), str(delta_texts))
    done = [f for f in frames if f.startswith("event: done")]
    check("存在 done 帧", len(done) == 1, str(done))
    done_data = json.loads(done[0].split("data: ", 1)[1])
    check("done 含 message_id", "message_id" in done_data and done_data["message_id"], str(done_data))

    # 消息已持久化：user 在前，assistant 在后，assistant 内容为完整拼接
    msgs = await get_messages(db, conv.id)
    check("消息数 = 2", len(msgs) == 2, str(len(msgs)))
    check("user 在前", msgs[0].role == "user" and msgs[0].content == "帮我写一段")
    check("assistant 完整内容", msgs[1].role == "assistant" and msgs[1].content == "你好，我是助手。", repr(msgs[1].content))
    check("assistant metadata 记录模型", msgs[1].message_metadata.get("model") == "mock-model", str(msgs[1].message_metadata))

    # 检查发送给 LLM 的消息数组：[system, ...history[-20:], user]
    assert client.calls, "MockClient 应被调用"
    sent_messages, kwargs = client.calls[0]
    check("首条为 system", sent_messages[0]["role"] == "system", str(sent_messages[0]))
    check("system 渲染了项目信息", "对话书" in sent_messages[0]["content"], sent_messages[0]["content"][:200])
    check("system 渲染了用户输入", "帮我写一段" in sent_messages[0]["content"], sent_messages[0]["content"][:200])
    check("system 渲染了章节", "第一章" in sent_messages[0]["content"] and "老松" in sent_messages[0]["content"])
    check("末条为 user", sent_messages[-1] == {"role": "user", "content": "帮我写一段"}, str(sent_messages[-1]))
    check("depth 来自会话配置", kwargs.get("depth") == "auto", str(kwargs.get("depth")))
    check("temperature/max_tokens 透传", kwargs.get("user_params") == {"temperature": 0.7, "max_tokens": 2048}, str(kwargs.get("user_params")))
    check("context_length 计算", kwargs.get("context_length") == sum(len(m["content"]) for m in sent_messages), str(kwargs.get("context_length")))

    # 历史截断：再次发送后，发送的消息数组应含 2 条历史 + 新 user
    client2 = MockClient(chunks=["第二回复"])
    frames2 = [f async for f in send_message(db, conv.id, "第二条", client=client2, config=config)]
    check("第二轮 done", any(f.startswith("event: done") for f in frames2))
    sent2 = client2.calls[0][0]
    check("历史带入（user+assistant+user）", [m["role"] for m in sent2] == ["system", "user", "assistant", "user"], str([m["role"] for m in sent2]))
    check("历史内容正序", sent2[1]["content"] == "帮我写一段" and sent2[2]["content"] == "你好，我是助手。", str(sent2[1:3]))

    # 详情端点用的 get_conversation 含消息
    detail = await get_conversation(db, conv.id)
    detail_read = ConversationDetailRead.model_validate(detail)
    check("详情含消息", len(detail_read.messages) == 4, str(len(detail_read.messages)))


async def test_send_error(db) -> None:
    print("[4] send_message 错误路径")
    proj, _, _ = await _seed(db, title="错误书")
    conv = await create_conversation(db, proj.id)
    failing = MockClient(error=RuntimeError("模型挂了"))
    frames = [f async for f in send_message(db, conv.id, "你好", client=failing, config=MockConfig())]
    errors = [f for f in frames if f.startswith("event: error")]
    check("LLM 异常产出 error 帧", len(errors) == 1, str(errors))
    msgs = await get_messages(db, conv.id)
    check("user 消息已保存", len(msgs) == 1 and msgs[0].role == "user", str(len(msgs)))
    check("未落 assistant 消息", all(m.role != "assistant" for m in msgs))


async def test_priority_and_custom_mapping(db) -> None:
    print("[5] 系统提示词优先级（会话覆盖 > 会话模板 > 全局默认）")
    proj, _, _ = await _seed(db, title="优先级书")
    conv = await create_conversation(db, proj.id)
    ctx = {"USER_INPUT": "你好"}
    global_tpl = await create_tpl(db, "全局默认", "全局默认内容")
    db.add(AppConfig(key=GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY, value=global_tpl.id))
    await db.commit()
    out = await get_effective_system_prompt(db, proj.id, conv, ctx)
    check("无模板回退全局默认", "全局默认内容" in out, out)
    await update_conversation(db, conv.id, system_prompt_override="覆盖：{{USER_INPUT}}")
    out = await get_effective_system_prompt(db, proj.id, conv, ctx)
    check("会话覆盖优先", out == "覆盖：你好", out)
    await db.execute(delete(AppConfig).where(AppConfig.key == GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY))
    await db.commit()


async def create_tpl(db, name: str, content: str) -> PromptTemplate:
    tpl = PromptTemplate(name=name, content=content, scope="global", is_system=True)
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return tpl


async def main() -> None:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_conv_test_")
    os.close(fd)
    engine = create_async_engine("sqlite+aiosqlite:///" + path.replace("\\", "/"))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            await test_schemas(db)
            await test_crud(db)
            await test_send_message(db)
            await test_send_error(db)
            await test_priority_and_custom_mapping(db)
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
