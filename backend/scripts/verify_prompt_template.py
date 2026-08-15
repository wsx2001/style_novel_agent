# backend/scripts/verify_prompt_template.py
"""系统提示词模板验证脚本（docs/TECHv1.md §4.3 / §5.7 / §7.1）。

运行方式（在 backend/ 下）：
    python scripts/verify_prompt_template.py

覆盖：
- render_system_prompt 占位符替换（含 dict/list 的 JSON 序列化）；
- 模板服务 CRUD / 过滤 / 复制 / 系统模板保护 / scope 校验；
- get_effective_system_prompt 优先级（覆盖 > 会话模板 > 项目默认 > 全局默认）；
- build_context_for_prompt 上下文构建。
所有断言通过时打印 OK 汇总并以退出码 0 结束（使用临时 SQLite，不影响正式库）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

# Windows 控制台可能为 GBK：强制 UTF-8 输出避免编码异常
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models import AppConfig, Base, Chapter, Conversation, KnowledgeCard, Message, Project  # noqa: E402
from app.services.llm.prompts import (  # noqa: E402
    GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY,
    SYSTEM_PROMPT_PLACEHOLDERS,
    SYSTEM_PROMPT_VARIABLES,
    build_context_for_prompt,
    get_effective_system_prompt,
    render_system_prompt,
)
from app.services.prompt_template import (  # noqa: E402
    PromptTemplateNotFound,
    PromptTemplateProtected,
    PromptTemplateValidationError,
    create_prompt_template,
    delete_prompt_template,
    duplicate_prompt_template,
    get_prompt_template_by_id,
    list_prompt_templates,
    update_prompt_template,
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


def test_placeholder_defs() -> None:
    print("[1] 占位符变量列表")
    expected = ("KNOWLEDGE_BASE", "CURRENT_CHAPTER", "STYLE_CARD",
                "USER_INPUT", "PROJECT_INFO", "CONVERSATION_HISTORY")
    check("变量列表与 §7.1 一致", tuple(SYSTEM_PROMPT_VARIABLES) == expected, str(SYSTEM_PROMPT_VARIABLES))
    check("占位符含 {{PROJECT_INFO}}", "{{PROJECT_INFO}}" in SYSTEM_PROMPT_PLACEHOLDERS)
    check("占位符数量一致", len(SYSTEM_PROMPT_PLACEHOLDERS) == len(expected))


def test_render() -> None:
    print("[2] render_system_prompt")
    tpl = "项目：{{PROJECT_INFO}}\n用户输入：{{USER_INPUT}}\n知识库：{{KNOWLEDGE_BASE}}\n文风：{{STYLE_CARD}}"
    context = {
        "PROJECT_INFO": {"title": "剑来", "genre": "玄幻"},
        "USER_INPUT": "帮我续写",
        "KNOWLEDGE_BASE": [{"title": "主角", "性格": "坚韧"}],
        "STYLE_CARD": "冷峻克制",
    }
    out = render_system_prompt(tpl, context)
    check("dict 值 JSON 序列化", '"genre": "玄幻"' in out, out)
    check("list 值 JSON 序列化", '"性格": "坚韧"' in out, out)
    check("普通字符串替换", "帮我续写" in out, out)
    check("无多余占位符残留", "{{" not in out, out)
    # 未提供的占位符原样保留
    out2 = render_system_prompt("剩余：{{CURRENT_CHAPTER}}", {"USER_INPUT": "x"})
    check("未提供占位符保留", out2 == "剩余：{{CURRENT_CHAPTER}}", out2)
    check("空模板返回空串", render_system_prompt("", {"USER_INPUT": "x"}) == "")


async def test_template_service(db) -> None:
    print("[3] 模板服务 CRUD")
    proj = Project(title="测试书", genre="玄幻")
    db.add(proj)
    await db.flush()

    g = await create_prompt_template(db, "全局文风", "全局：{{PROJECT_INFO}}", "global")
    check("create global 成功", g.scope == "global" and g.is_system is False)
    p = await create_prompt_template(db, "项目文风", "项目：{{USER_INPUT}}", "project", project_id=proj.id)
    check("create project 成功", p.project_id == proj.id)

    got = await get_prompt_template_by_id(db, g.id)
    check("get by id", got is not None and got.name == "全局文风")
    check("get 不存在返回 None", await get_prompt_template_by_id(db, "no-such-id") is None)

    lst = await list_prompt_templates(db)
    check("list 全部 = 2", len(lst) == 2, str(len(lst)))
    lst_global = await list_prompt_templates(db, scope="global")
    check("list scope=global = 1", len(lst_global) == 1, str(len(lst_global)))
    lst_proj = await list_prompt_templates(db, scope="project", project_id=proj.id)
    check("list scope+project 过滤 = 1", len(lst_proj) == 1 and lst_proj[0].id == p.id)

    u = await update_prompt_template(db, g.id, name="全局文风v2", content="全局v2：{{PROJECT_INFO}}")
    check("update name/content", u.name == "全局文风v2" and "v2" in u.content)

    d = await duplicate_prompt_template(db, g.id, "复制文风", "project", proj.id)
    check("duplicate 复制内容与作用域", d.content == u.content and d.scope == "project"
          and d.project_id == proj.id and d.is_system is False)

    sys_tpl = await create_prompt_template(db, "系统模板", "系统", "global", is_system=True)
    try:
        await delete_prompt_template(db, sys_tpl.id)
        check("系统模板拒绝删除", False)
    except PromptTemplateProtected:
        check("系统模板拒绝删除", True)
    await delete_prompt_template(db, p.id)
    check("删除普通模板", await get_prompt_template_by_id(db, p.id) is None)
    try:
        await delete_prompt_template(db, "no-such-id")
        check("删除不存在抛 NotFound", False)
    except PromptTemplateNotFound:
        check("删除不存在抛 NotFound", True)

    try:
        await create_prompt_template(db, "bad", "x", "project")
        check("project scope 无 project_id 拒绝", False)
    except PromptTemplateValidationError:
        check("project scope 无 project_id 拒绝", True)


async def test_priority(db) -> None:
    print("[4] 系统提示词优先级")
    proj = Project(title="优先级书")
    db.add(proj)
    await db.flush()
    ctx = {"USER_INPUT": "你好"}

    global_tpl = await create_prompt_template(db, "全局默认", "全局默认内容", "global")
    db.add(AppConfig(key=GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY, value=global_tpl.id))
    await db.commit()

    out = await get_effective_system_prompt(db, proj.id, None, ctx)
    check("无配置回退全局默认", "全局默认内容" in out, out)

    proj_tpl = await create_prompt_template(db, "项目默认", "项目默认内容", "project", project_id=proj.id)
    proj.default_prompt_template_id = proj_tpl.id
    await db.commit()
    out = await get_effective_system_prompt(db, proj.id, None, ctx)
    check("项目默认优先于全局", "项目默认内容" in out, out)

    conv_tpl = await create_prompt_template(db, "会话模板", "会话模板内容", "project", project_id=proj.id)
    conv = Conversation(project_id=proj.id, title="会话", system_prompt_template_id=conv_tpl.id)
    db.add(conv)
    await db.commit()
    out = await get_effective_system_prompt(db, proj.id, conv, ctx)
    check("会话模板优先于项目", "会话模板内容" in out, out)

    conv.system_prompt_override = "覆盖内容 {{USER_INPUT}}"
    await db.commit()
    out = await get_effective_system_prompt(db, proj.id, conv, ctx)
    check("会话覆盖优先且渲染", out == "覆盖内容 你好", out)

    await db.execute(delete(AppConfig).where(AppConfig.key == GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY))
    await db.commit()
    out = await get_effective_system_prompt(db, None, None, ctx)
    check("无任何模板返回空串", out == "", out)


async def test_build_context(db) -> None:
    print("[5] build_context_for_prompt")
    proj = Project(title="构建书", description="一个测试项目", genre="仙侠")
    db.add(proj)
    await db.flush()
    chap = Chapter(project_id=proj.id, title="第一章", content="山巅有一棵老松。")
    db.add(chap)
    await db.flush()
    style = KnowledgeCard(project_id=proj.id, card_type="style", title="文风卡",
                          content_json={"视角": "第三人称", "节奏": "舒缓"})
    db.add(style)
    conv = Conversation(project_id=proj.id, title="对话")
    db.add(conv)
    await db.flush()
    now = datetime.utcnow()
    db.add_all([
        Message(conversation_id=conv.id, role="user", content="你好", created_at=now),
        Message(conversation_id=conv.id, role="assistant", content="你好呀",
                created_at=now + timedelta(seconds=1)),
    ])
    await db.commit()

    ctx = await build_context_for_prompt(
        db, proj.id, chap.id, conv,
        user_input="继续", knowledge_cards=[style], style_card=style,
    )
    check("PROJECT_INFO 含书名与简介", "构建书" in ctx["PROJECT_INFO"] and "测试项目" in ctx["PROJECT_INFO"], ctx["PROJECT_INFO"])
    check("CURRENT_CHAPTER 含标题与正文", "第一章" in ctx["CURRENT_CHAPTER"] and "老松" in ctx["CURRENT_CHAPTER"], ctx["CURRENT_CHAPTER"])
    check("KNOWLEDGE_BASE 含卡片", '"title": "文风卡"' in ctx["KNOWLEDGE_BASE"], ctx["KNOWLEDGE_BASE"])
    check("STYLE_CARD 含结构化内容", '"视角": "第三人称"' in ctx["STYLE_CARD"], ctx["STYLE_CARD"])
    check("USER_INPUT 透传", ctx["USER_INPUT"] == "继续")
    history = ctx["CONVERSATION_HISTORY"]
    check("CONVERSATION_HISTORY 正序含 user 在前", history.find("user: 你好") < history.find("assistant: 你好呀"), history)

    ctx2 = await build_context_for_prompt(db, None, None, None, knowledge_cards=[])
    check("空上下文友好缺省", ctx2["KNOWLEDGE_BASE"] == "（无）" and ctx2["STYLE_CARD"] == "（无）"
          and ctx2["USER_INPUT"] == "" and ctx2["CONVERSATION_HISTORY"] == "")


async def main() -> None:
    test_placeholder_defs()
    test_render()

    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_prompt_tpl_test_")
    os.close(fd)
    try:
        url = "sqlite+aiosqlite:///" + path.replace("\\", "/")
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            await test_template_service(db)
            await test_priority(db)
            await test_build_context(db)
        await engine.dispose()
    finally:
        if os.path.exists(path):
            os.remove(path)

    print(f"\n结果：{_passed} 通过，{_failed} 失败")
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
