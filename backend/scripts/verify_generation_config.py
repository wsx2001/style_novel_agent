# backend/scripts/verify_generation_config.py
"""续写/重写 model_config 与提示词模板验证脚本（docs/TECHv1.md §5.5 / §7.1 / §7.2；V1.1 §5.4）。

运行方式（在 backend/ 下）：
    python scripts/verify_generation_config.py

覆盖：
- schema：ContinueRequest / RewriteRequest 接受 model_config 键（别名）与
  system_prompt_template_id、provider_id/model_id，缺省 None；
- resolve_model_config 优先级：请求 > 项目默认 > 全局默认；
- resolve_generation_system_prompt 优先级：请求模板 > 项目默认 > 全局默认 > 内置兜底，
  以及模板不存在 / 跨项目模板报错；
- 续写/重写 API（ASGI 驱动 + Mock LLM 客户端）：
  请求的 model_config 生效（depth/temperature/max_tokens 透传 LLM）、
  系统提示词渲染占位符、SSE 流式（start/delta/done）正常、
  生成记录记录实际提供商/模型（provider_id/model_id）；
- 错误路径：请求模板不存在 / 跨项目模板 → 400。
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
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models import (  # noqa: E402
    AppConfig,
    Base,
    Chapter,
    KnowledgeCard,
    ModelProvider,
    Project,
    PromptTemplate,
)
from app.schemas.generation import ContinueRequest, RewriteRequest  # noqa: E402
from app.services.generation import (  # noqa: E402
    GLOBAL_DEFAULT_MODEL_CONFIG_KEY,
    GenerationConfigError,
    resolve_generation_system_prompt,
    resolve_model_config,
)
from app.services.llm.prompts import GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY  # noqa: E402

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


class MockLLMClient:
    """记录每次流式调用的 messages/kwargs，产出固定增量（含候选分隔符）。"""

    def __init__(self, calls: list) -> None:
        self.calls = calls
        self.chunks = ["序言", "<<<CANDIDATE_1>>>", "候选正文"]

    async def chat_completion_stream(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        for chunk in self.chunks:
            yield chunk


def test_schemas() -> None:
    print("[1] schema 新字段（model_config 别名 / system_prompt_template_id / provider_id/model_id）")
    req = ContinueRequest.model_validate({
        "prompt": "写激烈一些",
        "model_config": {"depth": "high", "temperature": 0.5, "max_tokens": 4096},
        "system_prompt_template_id": "tpl1",
        "provider_id": "p1",
        "model_id": "gpt-4o",
    })
    check("continue 接受 model_config 键", req.request_model_config == {"depth": "high", "temperature": 0.5, "max_tokens": 4096}, str(req.request_model_config))
    check("continue system_prompt_template_id", req.system_prompt_template_id == "tpl1")
    check("continue provider_id/model_id 透传", req.provider_id == "p1" and req.model_id == "gpt-4o", str(req.provider_id))
    check("continue 缺省 model_config=None", ContinueRequest.model_validate({}).request_model_config is None)
    check("continue 缺省 template=None", ContinueRequest.model_validate({}).system_prompt_template_id is None)
    check("continue 缺省 provider/model=None", ContinueRequest.model_validate({}).provider_id is None and ContinueRequest.model_validate({}).model_id is None)

    rw = RewriteRequest.model_validate({"selected_text": "段落", "model_config": {"depth": "medium"}})
    check("rewrite 接受 model_config", rw.request_model_config == {"depth": "medium"}, str(rw.request_model_config))
    check("rewrite 缺省 template=None", RewriteRequest.model_validate({"selected_text": "x"}).system_prompt_template_id is None)


async def test_resolve_model_config(db) -> None:
    print("[2] resolve_model_config 优先级（请求 > 项目 > 全局）")
    db.add(AppConfig(key=GLOBAL_DEFAULT_MODEL_CONFIG_KEY, value={"depth": "low", "temperature": 0.9}))
    await db.commit()
    proj = Project(title="配置书", default_model_config={"depth": "medium", "temperature": 0.6, "max_tokens": 1024})
    empty = Project(title="空默认书", default_model_config={})
    db.add_all([proj, empty])
    await db.commit()

    out = await resolve_model_config(db, proj.id, {"depth": "high", "temperature": 0.5})
    check("请求配置优先", out == {"depth": "high", "temperature": 0.5}, str(out))
    out = await resolve_model_config(db, proj.id, None)
    check("回退项目默认", out == {"depth": "medium", "temperature": 0.6, "max_tokens": 1024}, str(out))
    out = await resolve_model_config(db, empty.id, None)
    check("项目空配置回退全局", out == {"depth": "low", "temperature": 0.9}, str(out))
    out = await resolve_model_config(db, "no-such", None)
    check("项目不存在回退全局", out == {"depth": "low", "temperature": 0.9}, str(out))
    out = await resolve_model_config(db, proj.id, {})
    check("空 dict 请求视为未提供", out == {"depth": "medium", "temperature": 0.6, "max_tokens": 1024}, str(out))


async def test_resolve_system_prompt(db) -> None:
    print("[3] resolve_generation_system_prompt 优先级")
    proj = Project(title="提示词书")
    db.add(proj)
    await db.flush()
    ctx = {"PROJECT_INFO": "书名：提示词书", "USER_INPUT": "继续"}

    out = await resolve_generation_system_prompt(db, proj.id, None, ctx, builtin="内置续写提示")
    check("无模板回退内置", out == "内置续写提示", out)

    global_tpl = PromptTemplate(name="全局默认", content="全局：{{USER_INPUT}}", scope="global", is_system=True)
    db.add(global_tpl)
    await db.commit()
    db.add(AppConfig(key=GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY, value=global_tpl.id))
    await db.commit()
    out = await resolve_generation_system_prompt(db, proj.id, None, ctx, builtin="内置")
    check("回退全局默认模板并渲染", out == "全局：继续", out)

    proj_tpl = PromptTemplate(name="项目默认", content="项目：{{PROJECT_INFO}}", scope="project", project_id=proj.id)
    db.add(proj_tpl)
    await db.commit()
    proj.default_prompt_template_id = proj_tpl.id
    await db.commit()
    out = await resolve_generation_system_prompt(db, proj.id, None, ctx, builtin="内置")
    check("项目默认优先于全局", out == "项目：书名：提示词书", out)

    req_tpl = PromptTemplate(name="请求模板", content="请求：{{USER_INPUT}}", scope="project", project_id=proj.id)
    db.add(req_tpl)
    await db.commit()
    out = await resolve_generation_system_prompt(db, proj.id, req_tpl.id, ctx, builtin="内置")
    check("请求模板优先并渲染", out == "请求：继续", out)
    out = await resolve_generation_system_prompt(db, proj.id, global_tpl.id, ctx, builtin="内置")
    check("全局模板任意项目可用", out == "全局：继续", out)

    try:
        await resolve_generation_system_prompt(db, proj.id, "no-such", ctx, builtin="内置")
        check("请求模板不存在报错", False)
    except GenerationConfigError:
        check("请求模板不存在报错", True)

    other = Project(title="其它书")
    db.add(other)
    await db.flush()
    other_tpl = PromptTemplate(name="别人的", content="x", scope="project", project_id=other.id)
    db.add(other_tpl)
    await db.commit()
    try:
        await resolve_generation_system_prompt(db, proj.id, other_tpl.id, ctx, builtin="内置")
        check("跨项目模板报错", False)
    except GenerationConfigError:
        check("跨项目模板报错", True)


async def test_generation_api(client: AsyncClient, maker, mock_client: MockLLMClient) -> None:
    print("[4] 续写/重写 API：model_config 与模板生效 + 流式正常")
    async with maker() as db:
        proj = Project(title="生成书", genre="玄幻", default_model_config={"depth": "medium", "temperature": 0.6, "max_tokens": 1024})
        other = Project(title="其它书")
        db.add_all([proj, other])
        await db.flush()
        chap = Chapter(project_id=proj.id, title="第一章", content="山巅有一棵老松。")
        style = KnowledgeCard(project_id=proj.id, card_type="style", title="文风卡", content_json={"视角": "冷峻"})
        db.add_all([chap, style])
        await db.flush()
        tpl = PromptTemplate(
            name="续写模板",
            content="你是续写助手。\n项目：{{PROJECT_INFO}}\n章节：{{CURRENT_CHAPTER}}\n知识库：{{KNOWLEDGE_BASE}}\n输入：{{USER_INPUT}}",
            scope="project",
            project_id=proj.id,
        )
        other_tpl = PromptTemplate(name="别人的模板", content="别人的", scope="project", project_id=other.id)
        db.add_all([tpl, other_tpl])
        await db.commit()
        ids = {"proj": proj.id, "chap": chap.id, "style": style.id, "tpl": tpl.id, "other_tpl": other_tpl.id}

    # ---- 续写：请求 model_config + 模板生效 ----
    mock_client.calls.clear()
    resp = await client.post(
        f"/api/v1/chapters/{ids['chap']}/generate/continue",
        json={
            "prompt": "写激烈一些",
            "card_ids": [ids["style"]],
            "target_words": 300,
            "model_config": {"depth": "high", "temperature": 0.5},
            "system_prompt_template_id": ids["tpl"],
        },
    )
    check("续写 200", resp.status_code == 200, str(resp.status_code))
    text = resp.text
    check("续写 SSE start/delta/done", "event: start" in text and "event: delta" in text and "event: done" in text)
    check("续写候选正文下发", "候选正文" in text)
    sent, kwargs = mock_client.calls[0]
    sys_msg = sent[0]["content"]
    check("system 为渲染后的模板", "你是续写助手" in sys_msg, sys_msg[:100])
    check("system 渲染项目信息", "生成书" in sys_msg, sys_msg[:100])
    check("system 渲染章节", "第一章" in sys_msg and "老松" in sys_msg, sys_msg[:120])
    check("system 渲染知识库", '"title": "文风卡"' in sys_msg, sys_msg[:120])
    check("system 渲染用户输入", "写激烈一些" in sys_msg, sys_msg[:120])
    check("depth 来自请求 model_config", kwargs["depth"] == "high", str(kwargs.get("depth")))
    check("temperature 来自请求 model_config", kwargs["user_params"]["temperature"] == 0.5, str(kwargs.get("user_params")))
    check("max_tokens 回退默认", kwargs["user_params"]["max_tokens"] == 2048, str(kwargs.get("user_params")))
    check("knowledge_card_count 传入", kwargs["knowledge_card_count"] == 1, str(kwargs.get("knowledge_card_count")))

    # ---- 续写：未提供 model_config → 回退项目默认 ----
    mock_client.calls.clear()
    resp = await client.post(
        f"/api/v1/chapters/{ids['chap']}/generate/continue",
        json={"prompt": "继续", "target_words": 300},
    )
    _, kwargs = mock_client.calls[0]
    check("续写缺省回退项目默认 depth", kwargs["depth"] == "medium", str(kwargs.get("depth")))
    check("续写缺省回退项目默认 temperature", kwargs["user_params"]["temperature"] == 0.6, str(kwargs.get("user_params")))
    check("续写缺省回退项目默认 max_tokens", kwargs["user_params"]["max_tokens"] == 1024, str(kwargs.get("user_params")))

    # ---- 续写：请求模板不存在 → 400 ----
    resp = await client.post(
        f"/api/v1/chapters/{ids['chap']}/generate/continue",
        json={"prompt": "x", "target_words": 300, "system_prompt_template_id": "no-such"},
    )
    check("续写模板不存在 400", resp.status_code == 400, str(resp.status_code))
    # 跨项目模板 → 400
    resp = await client.post(
        f"/api/v1/chapters/{ids['chap']}/generate/continue",
        json={"prompt": "x", "target_words": 300, "system_prompt_template_id": ids["other_tpl"]},
    )
    check("续写跨项目模板 400", resp.status_code == 400, str(resp.status_code))

    # ---- 重写：请求 model_config + 模板生效 ----
    mock_client.calls.clear()
    resp = await client.post(
        f"/api/v1/chapters/{ids['chap']}/generate/rewrite",
        json={
            "selected_text": "山巅有一棵老松。",
            "instruction": "改得更有张力",
            "card_ids": [ids["style"]],
            "style_card_id": ids["style"],
            "model_config": {"depth": "extreme", "temperature": 0.3, "max_tokens": 4096},
            "system_prompt_template_id": ids["tpl"],
        },
    )
    check("重写 200", resp.status_code == 200, str(resp.status_code))
    text = resp.text
    check("重写 SSE start/delta/done", "event: start" in text and "event: done" in text)
    sent, kwargs = mock_client.calls[0]
    sys_msg = sent[0]["content"]
    check("重写 system 渲染模板", "你是续写助手" in sys_msg and "改得更有张力" in sys_msg, sys_msg[:120])
    check("重写 depth 生效", kwargs["depth"] == "extreme", str(kwargs.get("depth")))
    check("重写 temperature/max_tokens 生效", kwargs["user_params"]["temperature"] == 0.3 and kwargs["user_params"]["max_tokens"] == 4096, str(kwargs.get("user_params")))

    # ---- 重写：缺省配置回退 ----
    mock_client.calls.clear()
    resp = await client.post(
        f"/api/v1/chapters/{ids['chap']}/generate/rewrite",
        json={"selected_text": "山巅有一棵老松。"},
    )
    _, kwargs = mock_client.calls[0]
    check("重写缺省回退项目默认", kwargs["depth"] == "medium" and kwargs["user_params"]["temperature"] == 0.6, str(kwargs.get("user_params")))

    # ---- 生成记录记录实际提供商/模型（V1.1 §4.5） ----
    from app.models import GenerationRecord

    async with maker() as db:
        rec = (
            await db.execute(
                select(GenerationRecord)
                .where(GenerationRecord.project_id == ids["proj"])
                .order_by(GenerationRecord.created_at.desc())
            )
        ).scalars().first()
        check(
            "生成记录记录提供商/模型",
            rec is not None and rec.provider_id == "mock-provider" and rec.model_id == "mock-model",
            f"{rec.provider_id if rec else None}/{rec.model_id if rec else None}",
        )


async def main() -> None:
    test_schemas()

    fd, path = tempfile.mkstemp(suffix=".db", prefix="ff_gen_cfg_test_")
    os.close(fd)
    engine = create_async_engine("sqlite+aiosqlite:///" + path.replace("\\", "/"))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_get_db():
            async with maker() as session:
                yield session

        import app.api.v1.generations as generations_mod

        from app.api.v1.generations import router as generations_router

        calls: list = []
        mock_client = MockLLMClient(calls)

        async def fake_resolve_llm(db, **kwargs):
            from app.services.llm.resolve import ResolvedLLM

            provider = ModelProvider(id="mock-provider", name="Mock", type="custom")
            return ResolvedLLM(
                provider=provider,
                provider_id=provider.id,
                model_id="mock-model",
                api_key="sk-test",
                client=mock_client,
            )

        async def fake_select_cards(db, project_id, query_text, explicit_card_ids, resolved):
            result = await db.execute(
                select(KnowledgeCard).where(KnowledgeCard.project_id == project_id)
            )
            cards = list(result.scalars().all())
            return cards, {c.id: [] for c in cards}

        # 替换模块级依赖：resolve_llm 与 _select_cards 打桩避免真实网络调用
        generations_mod.resolve_llm = fake_resolve_llm
        generations_mod._select_cards = fake_select_cards

        test_app = FastAPI()
        test_app.include_router(generations_router)
        test_app.dependency_overrides[get_db] = override_get_db

        async with maker() as db:
            await test_resolve_model_config(db)
        async with maker() as db:
            await test_resolve_system_prompt(db)

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await test_generation_api(client, maker, mock_client)
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
