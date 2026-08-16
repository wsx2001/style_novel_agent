# backend/app/api/v1/generations.py
"""AI 生成 API（docs/TECH.md §5.5；V1 支持 model_config / system_prompt_template_id，docs/TECHv1.md §5.5）。

- POST /chapters/{chapter_id}/generate/continue  续写（SSE 流式，多候选）
- POST /chapters/{chapter_id}/generate/rewrite   重写（SSE 流式，多候选）
- POST /projects/{project_id}/generate/inspire   灵感生成（简单实现，同步返回）
- GET  /projects/{project_id}/generations        生成记录列表（?type=&chapter_id=&q=）

续写/重写可传入 model_config（depth/temperature/max_tokens）与 system_prompt_template_id；
未提供时按 请求 > 项目默认 > 全局默认 解析模型配置与系统提示词（docs/TECHv1.md §7.1）。

错误处理：未配置 API Key → 400；请求模板不存在/作用域不匹配 → 400；解密失败 → 500；LLM 调用失败：
    续写/重写（已进入流式）→ SSE error 事件 + 记录 status=failed；
    灵感（同步调用）→ 502。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import (
    Chapter,
    GenerationCardLink,
    GenerationRecord,
    KnowledgeCard,
    Project,
)
from ...schemas.generation import (
    ContinueRequest,
    GenerationRead,
    GenerationType,
    InspireRequest,
    InspireResponse,
    RewriteRequest,
)
from ...services.embedding.embedder import Embedder
from ...services.generation import (
    GenerationConfigError,
    resolve_generation_system_prompt,
    resolve_model_config,
)
from ...services.llm.prompts import (
    CONTINUE_SYSTEM_PROMPT,
    CONTINUE_USER_TEMPLATE,
    INSPIRE_SYSTEM_PROMPT,
    INSPIRE_USER_TEMPLATE,
    REWRITE_SYSTEM_PROMPT,
    REWRITE_USER_TEMPLATE,
    build_context_for_prompt,
    candidate_delimiter_list,
)
from ...services.llm.resolve import NoLLMConfigError, ResolvedLLM, resolve_llm
from ...services.llm.stream import CandidateSplitter, sse_event
from ...services.retrieval.hybrid import HybridRetriever

router = APIRouter(prefix="/api/v1", tags=["generations"])

logger = logging.getLogger(__name__)

# 生成参数（docs/TECH.md §7）
TAIL_CONTEXT_CHARS = 1500  # 续写使用的章节尾部上下文长度
DEFAULT_MAX_TOKENS = 0  # 默认无上限：0 表示省略 max_tokens，交由提供商默认输出上限
RECOMMEND_TOP_N = 12  # 送入 Prompt 的卡片数上限（docs/TECH.md §6.5：8~12）


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    """按 id 查询项目，不存在则抛 404。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


async def _get_chapter_or_404(chapter_id: str, db: AsyncSession) -> Chapter:
    """按 id 查询章节，不存在则抛 404。"""
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"章节 {chapter_id} 不存在",
        )
    return chapter


def _card_item(card: KnowledgeCard, snippets: list[str]) -> dict[str, Any]:
    """将卡片转为 Prompt 引用的紧凑字典（标题 + 结构化字段 + 原文片段溯源）。"""
    item: dict[str, Any] = {"title": card.title}
    item.update(card.content_json or {})
    if snippets:
        item["原文片段"] = snippets
    return item


def _json_section(
    cards: list[KnowledgeCard], snippets_by_card: dict[str, list[str]]
) -> str:
    """将一组卡片编码为 JSON 文本（空组返回“（无）”）。"""
    if not cards:
        return "（无）"
    items = [_card_item(c, snippets_by_card.get(c.id, [])) for c in cards]
    return json.dumps(items, ensure_ascii=False, indent=1)


def _split_by_type(
    cards: list[KnowledgeCard], snippets_by_card: dict[str, list[str]]
) -> dict[str, str]:
    """按 card_type 分组为角色/世界观/术语三个 Prompt 区块（JSON 文本）。"""
    groups: dict[str, list[KnowledgeCard]] = {"character": [], "world": [], "term": []}
    for card in cards:
        if card.card_type in groups:
            groups[card.card_type].append(card)
    return {key: _json_section(value, snippets_by_card) for key, value in groups.items()}


def _style_card(
    cards: list[KnowledgeCard], preferred_id: Optional[str]
) -> Optional[KnowledgeCard]:
    """取文风卡：优先 preferred_id，其次卡片列表中第一张 style 卡。"""
    if preferred_id:
        for card in cards:
            if card.id == preferred_id:
                return card
    for card in cards:
        if card.card_type == "style":
            return card
    return None


async def _select_cards(
    db: AsyncSession,
    project_id: str,
    query_text: str,
    explicit_card_ids: list[str],
    resolved: ResolvedLLM,
) -> tuple[list[KnowledgeCard], dict[str, list[str]]]:
    """加载显式卡片 + Chroma 推荐卡片，返回 (卡片列表, card_id -> 原文片段)。

    检索失败时静默回退为仅显式卡片（生成流程不因推荐失败而中断）。
    """
    explicit: list[KnowledgeCard] = []
    if explicit_card_ids:
        result = await db.execute(
            select(KnowledgeCard).where(
                KnowledgeCard.project_id == project_id,
                KnowledgeCard.id.in_(explicit_card_ids),
            )
        )
        by_id = {c.id: c for c in result.scalars().all()}
        explicit = [by_id[cid] for cid in explicit_card_ids if cid in by_id]

    if query_text and query_text.strip():
        try:
            embedder = Embedder(
                api_key=resolved.api_key,
                base_url=resolved.provider.base_url or None,
                model=resolved.model_id,
            )
            retriever = HybridRetriever(embedder=embedder)
            recommended = await retriever.recommend_cards(
                project_id,
                query_text,
                explicit_card_ids=[c.id for c in explicit],
                top_n=RECOMMEND_TOP_N,
            )
        except Exception as exc:
            logger.warning("生成前检索推荐卡片失败，仅使用显式卡片：%s", exc)
            recommended = []
        recommended_ids = [item["card_id"] for item in recommended]
        if recommended_ids:
            result = await db.execute(
                select(KnowledgeCard).where(
                    KnowledgeCard.project_id == project_id,
                    KnowledgeCard.id.in_(recommended_ids),
                )
            )
            rec_by_id = {c.id: c for c in result.scalars().all()}
            seen = {c.id for c in explicit}
            for item in recommended:
                card = rec_by_id.get(item["card_id"])
                if card is None:
                    continue
                if card.id not in seen:
                    explicit.append(card)
                    seen.add(card.id)
    else:
        recommended = []

    snippets_by_card: dict[str, list[str]] = {c.id: [] for c in explicit}
    for item in recommended:
        if item["snippets"]:
            snippets_by_card[item["card_id"]] = item["snippets"]
    return explicit, snippets_by_card


def _build_continue_messages(
    payload: ContinueRequest,
    tail: str,
    cards: list[KnowledgeCard],
    snippets_by_card: dict[str, list[str]],
    style: Optional[KnowledgeCard],
    system_prompt: str,
) -> list[dict[str, str]]:
    """组装续写 Prompt（docs/TECH.md §7.1；系统提示词由调用方解析传入）。"""
    sections = _split_by_type(cards, snippets_by_card)
    extra = ""
    if payload.prompt and payload.prompt.strip():
        extra = f"- 额外要求：{payload.prompt.strip()}"
    user = CONTINUE_USER_TEMPLATE.format(
        style_card_json=_json_section([style], snippets_by_card) if style else "（无）",
        character_cards_json=sections["character"],
        world_cards_json=sections["world"],
        term_cards_json=sections["term"],
        chapter_tail_context=tail or "（空）",
        target_words=payload.target_words,
        narrative_view=payload.view or "维持与当前正文一致",
        extra_requirements=extra,
        candidate_count=payload.candidate_count,
        candidate_delimiters=candidate_delimiter_list(payload.candidate_count),
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def _build_rewrite_messages(
    payload: RewriteRequest,
    cards: list[KnowledgeCard],
    snippets_by_card: dict[str, list[str]],
    style: Optional[KnowledgeCard],
    system_prompt: str,
) -> list[dict[str, str]]:
    """组装重写 Prompt（docs/TECH.md §7.2；系统提示词由调用方解析传入）。"""
    sections = _split_by_type(cards, snippets_by_card)
    user = REWRITE_USER_TEMPLATE.format(
        style_card_json=_json_section([style], snippets_by_card) if style else "（无）",
        character_cards_json=sections["character"],
        term_cards_json=sections["term"],
        world_cards_json=sections["world"],
        selected_text=payload.selected_text,
        instruction=payload.instruction or "保持原意，优化表达",
        target_words=payload.target_words,
        candidate_count=payload.candidate_count,
        candidate_delimiters=candidate_delimiter_list(payload.candidate_count),
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def _create_record(
    *,
    project_id: str,
    chapter_id: Optional[str],
    generation_type: str,
    input_text: Optional[str],
    params: dict[str, Any],
    provider_id: Optional[str] = None,
    model_id: Optional[str] = None,
) -> GenerationRecord:
    """构建生成记录（status=streaming）；卡片关联在调用方 flush 后添加。

    provider_id / model_id 为本次生成实际使用的提供商与模型（docs/TECHv1.1.md §4.5）。
    """
    return GenerationRecord(
        project_id=project_id,
        chapter_id=chapter_id,
        generation_type=generation_type,
        status="streaming",
        input_text=input_text,
        params_json=params,
        output_candidates=[],
        provider_id=provider_id,
        model_id=model_id,
    )


@router.post(
    "/chapters/{chapter_id}/generate/continue",
    summary="续写（SSE 流式，多候选）",
    responses={
        200: {
            "description": "SSE 事件流（start / delta / done / error）",
        }
    },
)
async def generate_continue(
    chapter_id: str,
    payload: ContinueRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """续写章节尾部：检索推荐卡片 → 组装 Prompt → 流式生成多候选（SSE）。

    SSE 事件：
        event: start   data: {"generation_id", "type"}
        event: delta   data: {"index", "text"}          # 逐段正文
        event: done    data: {"candidates": [...]}
        event: error   data: {"message"}                # LLM 失败/流中断
    """
    chapter = await _get_chapter_or_404(chapter_id, db)
    try:
        resolved = await resolve_llm(
            db,
            project_id=chapter.project_id,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
        )
    except NoLLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    client = resolved.client

    tail = chapter.content[-TAIL_CONTEXT_CHARS:]
    cards, snippets_by_card = await _select_cards(
        db, chapter.project_id, tail, payload.card_ids, resolved
    )
    style = _style_card(cards, None)

    # V1：解析模型配置（请求 > 项目默认 > 全局默认）与系统提示词（docs/TECHv1.md §7.1）
    config_dict = await resolve_model_config(
        db, chapter.project_id, payload.request_model_config
    )
    depth = config_dict.get("depth", "auto")
    temperature = config_dict.get("temperature", payload.temperature)
    max_tokens = config_dict.get("max_tokens", DEFAULT_MAX_TOKENS)

    context = await build_context_for_prompt(
        db,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        knowledge_cards=cards,
        style_card=style,
        user_input=payload.prompt,
    )
    try:
        system_prompt = await resolve_generation_system_prompt(
            db,
            chapter.project_id,
            payload.system_prompt_template_id,
            context,
            builtin=CONTINUE_SYSTEM_PROMPT,
        )
    except GenerationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    messages = _build_continue_messages(
        payload, tail, cards, snippets_by_card, style, system_prompt
    )

    record = _create_record(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        generation_type="continue",
        input_text=tail or chapter.content,
        provider_id=resolved.provider_id,
        model_id=resolved.model_id,
        params={
            "target_words": payload.target_words,
            "temperature": temperature,
            "depth": depth,
            "model_config": config_dict,
            "view": payload.view,
            "prompt": payload.prompt,
            "candidate_count": payload.candidate_count,
            "system_prompt_template_id": payload.system_prompt_template_id,
            "card_ids": [c.id for c in cards],
        },
    )
    db.add(record)
    await db.flush()
    for card in cards:
        db.add(GenerationCardLink(generation_id=record.id, card_id=card.id))
    await db.commit()
    await db.refresh(record)

    async def event_stream():
        splitter = CandidateSplitter()
        try:
            yield sse_event("start", {"generation_id": record.id, "type": "continue"})
            async for delta in client.chat_completion_stream(
                messages,
                model=resolved.model_id,
                depth=depth,
                user_params={"temperature": temperature, "max_tokens": max_tokens},
                context_length=sum(len(m["content"]) for m in messages),
                knowledge_card_count=len(cards),
            ):
                for index, text in splitter.feed(delta):
                    if index is None or not text:
                        continue
                    yield sse_event("delta", {"index": index, "text": text})
            candidates = splitter.finish()
            record.status = "completed"
            record.output_candidates = candidates
            await db.commit()
            yield sse_event("done", {"candidates": candidates})
        except Exception as exc:
            logger.exception("续写流式生成失败")
            record.status = "failed"
            await db.commit()
            yield sse_event("error", {"message": str(exc)})
        finally:
            # 客户端断开（GeneratorExit/CancelledError）未走 except：标记 failed 防悬挂
            if record.status != "completed":
                record.status = "failed"
                await db.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/chapters/{chapter_id}/generate/rewrite",
    summary="重写（SSE 流式，多候选）",
)
async def generate_rewrite(
    chapter_id: str,
    payload: RewriteRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """重写选中段落：按段落文本检索相关卡片 → 组装 Prompt → 流式生成多候选（SSE）。"""
    chapter = await _get_chapter_or_404(chapter_id, db)
    try:
        resolved = await resolve_llm(
            db,
            project_id=chapter.project_id,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
        )
    except NoLLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    client = resolved.client

    cards, snippets_by_card = await _select_cards(
        db, chapter.project_id, payload.selected_text, payload.card_ids, resolved
    )
    # style_card_id 可能未包含在选中/推荐卡片中：单独加载并前置
    if payload.style_card_id and not any(c.id == payload.style_card_id for c in cards):
        style_card = await db.get(KnowledgeCard, payload.style_card_id)
        if style_card is not None and style_card.project_id == chapter.project_id:
            cards.insert(0, style_card)
    style = _style_card(cards, payload.style_card_id)

    # V1：解析模型配置（请求 > 项目默认 > 全局默认）与系统提示词（docs/TECHv1.md §7.1）
    config_dict = await resolve_model_config(
        db, chapter.project_id, payload.request_model_config
    )
    depth = config_dict.get("depth", "auto")
    temperature = config_dict.get("temperature", payload.temperature)
    max_tokens = config_dict.get("max_tokens", DEFAULT_MAX_TOKENS)

    context = await build_context_for_prompt(
        db,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        knowledge_cards=cards,
        style_card=style,
        user_input=payload.instruction,
    )
    try:
        system_prompt = await resolve_generation_system_prompt(
            db,
            chapter.project_id,
            payload.system_prompt_template_id,
            context,
            builtin=REWRITE_SYSTEM_PROMPT,
        )
    except GenerationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    messages = _build_rewrite_messages(
        payload, cards, snippets_by_card, style, system_prompt
    )

    record = _create_record(
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        generation_type="rewrite",
        input_text=payload.selected_text,
        provider_id=resolved.provider_id,
        model_id=resolved.model_id,
        params={
            "selected_text": payload.selected_text,
            "instruction": payload.instruction,
            "style_card_id": payload.style_card_id,
            "target_words": payload.target_words,
            "temperature": temperature,
            "depth": depth,
            "model_config": config_dict,
            "candidate_count": payload.candidate_count,
            "system_prompt_template_id": payload.system_prompt_template_id,
            "card_ids": [c.id for c in cards],
        },
    )
    db.add(record)
    await db.flush()
    for card in cards:
        db.add(GenerationCardLink(generation_id=record.id, card_id=card.id))
    await db.commit()
    await db.refresh(record)

    async def event_stream():
        splitter = CandidateSplitter()
        try:
            yield sse_event("start", {"generation_id": record.id, "type": "rewrite"})
            async for delta in client.chat_completion_stream(
                messages,
                model=resolved.model_id,
                depth=depth,
                user_params={"temperature": temperature, "max_tokens": max_tokens},
                context_length=sum(len(m["content"]) for m in messages),
                knowledge_card_count=len(cards),
            ):
                for index, text in splitter.feed(delta):
                    if index is None or not text:
                        continue
                    yield sse_event("delta", {"index": index, "text": text})
            candidates = splitter.finish()
            record.status = "completed"
            record.output_candidates = candidates
            await db.commit()
            yield sse_event("done", {"candidates": candidates})
        except Exception as exc:
            logger.exception("重写流式生成失败")
            record.status = "failed"
            await db.commit()
            yield sse_event("error", {"message": str(exc)})
        finally:
            if record.status != "completed":
                record.status = "failed"
                await db.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/projects/{project_id}/generate/inspire",
    response_model=InspireResponse,
    summary="灵感生成（简单实现，同步返回）",
)
async def generate_inspire(
    project_id: str,
    payload: InspireRequest,
    db: AsyncSession = Depends(get_db),
) -> InspireResponse:
    """围绕主题生成一段小说灵感（非流式调用，返回单条文本并保存记录）。"""
    await _get_project_or_404(project_id, db)
    try:
        resolved = await resolve_llm(
            db,
            project_id=project_id,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
        )
    except NoLLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    messages = [
        {"role": "system", "content": INSPIRE_SYSTEM_PROMPT},
        {"role": "user", "content": INSPIRE_USER_TEMPLATE.format(idea=payload.idea)},
    ]
    try:
        content = await resolved.client.chat_completion(
            messages,
            model=resolved.model_id,
            depth="auto",
            user_params={"temperature": payload.temperature, "max_tokens": 1024},
            context_length=sum(len(m["content"]) for m in messages),
            knowledge_card_count=0,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM 调用失败：{exc}",
        ) from exc

    record = GenerationRecord(
        project_id=project_id,
        chapter_id=None,
        generation_type="inspire",
        status="completed",
        input_text=payload.idea,
        params_json={"idea": payload.idea, "temperature": payload.temperature},
        output_candidates=[content],
        provider_id=resolved.provider_id,
        model_id=resolved.model_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return InspireResponse(id=record.id, content=content)


@router.get(
    "/projects/{project_id}/generations",
    response_model=list[GenerationRead],
    summary="生成记录列表（?type=&chapter_id=&q= 过滤）",
)
async def list_generations(
    project_id: str,
    generation_type: Optional[GenerationType] = Query(default=None, alias="type"),
    chapter_id: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[GenerationRecord]:
    """按创建时间倒序返回生成记录，支持按类型/章节/输入文本关键词过滤。"""
    await _get_project_or_404(project_id, db)
    stmt = select(GenerationRecord).where(GenerationRecord.project_id == project_id)
    if generation_type is not None:
        stmt = stmt.where(GenerationRecord.generation_type == generation_type)
    if chapter_id:
        stmt = stmt.where(GenerationRecord.chapter_id == chapter_id)
    if q:
        stmt = stmt.where(GenerationRecord.input_text.contains(q))
    result = await db.execute(stmt.order_by(GenerationRecord.created_at.desc()))
    return list(result.scalars().all())
