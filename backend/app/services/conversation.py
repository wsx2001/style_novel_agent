# backend/app/services/conversation.py
"""对话服务（docs/TECHv1.md §4.4 / §5.6 / §7.3）。

提供对话 CRUD、消息查询与 send_message 流式对话：
- 各函数使用 AsyncSession，事务在函数内 commit；
- send_message 按 §7.3 流程：渲染系统提示词（复用 prompt_template 服务）→
  组装 [system, ...history[-20:], user] → 调用 LLM 流式接口
  （深度配置集成于 services/llm/client.py）→ 持久化 user/assistant 消息 → 产出 SSE 帧。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import ApiKeyConfig, Chapter, Conversation, Message, Project
from .llm.client import LLMClient
from .llm.prompts import build_context_for_prompt, get_effective_system_prompt
from .llm.stream import sse_event
from .prompt_template import get_prompt_template_by_id

logger = logging.getLogger(__name__)

# 对话模式每次携带的最近消息条数（docs/TECHv1.md §7.3：最近 20 条）
HISTORY_LIMIT = 20


class ConversationNotFound(Exception):
    """对话不存在。"""


class ProjectNotFound(Exception):
    """项目不存在。"""


class ConversationValidationError(ValueError):
    """对话参数不合法（章节归属 / 模板存在性 / 模板作用域等）。"""


async def _get_conversation(db: AsyncSession, conversation_id: str) -> Conversation:
    """按 id 查询对话，不存在则抛 ConversationNotFound。"""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFound(f"对话 {conversation_id} 不存在")
    return conversation


async def get_conversation(db: AsyncSession, conversation_id: str) -> Conversation:
    """获取对话（含消息列表，供详情端点序列化）；不存在抛 ConversationNotFound。"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    conversation = result.scalars().first()
    if conversation is None:
        raise ConversationNotFound(f"对话 {conversation_id} 不存在")
    return conversation


async def list_conversations(db: AsyncSession, project_id: str) -> list[Conversation]:
    """列出项目下所有对话（按创建时间倒序）。"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.project_id == project_id)
        .order_by(Conversation.created_at.desc())
    )
    return list(result.scalars().all())


async def _validate_chapter(db: AsyncSession, project_id: str, chapter_id: str) -> None:
    """校验章节存在且属于该项目。"""
    chapter = await db.get(Chapter, chapter_id)
    if chapter is None or chapter.project_id != project_id:
        raise ConversationValidationError(f"章节 {chapter_id} 不存在或不属于该项目")


async def _validate_template(
    db: AsyncSession, template_id: str, project_id: str
) -> None:
    """校验提示词模板存在，且 project 作用域模板归属于该项目。"""
    template = await get_prompt_template_by_id(db, template_id)
    if template is None:
        raise ConversationValidationError(f"提示词模板 {template_id} 不存在")
    if template.scope == "project" and template.project_id != project_id:
        raise ConversationValidationError(f"提示词模板 {template_id} 不属于该项目")


async def create_conversation(
    db: AsyncSession,
    project_id: str,
    title: str = "新对话",
    chapter_id: Optional[str] = None,
    model_config: Optional[dict] = None,
    system_prompt_template_id: Optional[str] = None,
) -> Conversation:
    """创建对话；校验项目存在、章节归属、模板存在性。

    model_config 缺省时由模型列默认值填充（{"depth": "auto", "temperature": 0.7, "max_tokens": 2048}）。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise ProjectNotFound(f"项目 {project_id} 不存在")
    if chapter_id is not None:
        await _validate_chapter(db, project_id, chapter_id)
    if system_prompt_template_id is not None:
        await _validate_template(db, system_prompt_template_id, project_id)

    kwargs: dict[str, Any] = {
        "project_id": project_id,
        "title": title or "新对话",
        "chapter_id": chapter_id,
        "system_prompt_template_id": system_prompt_template_id,
    }
    if model_config is not None:
        kwargs["model_config"] = model_config
    conversation = Conversation(**kwargs)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def update_conversation(
    db: AsyncSession,
    conversation_id: str,
    title: Optional[str] = None,
    model_config: Optional[dict] = None,
    system_prompt_template_id: Optional[str] = None,
    system_prompt_override: Optional[str] = None,
) -> Conversation:
    """更新对话（None 参数表示不修改）；替换系统提示词模板时校验其存在性。"""
    conversation = await _get_conversation(db, conversation_id)
    if title is not None:
        conversation.title = title
    if model_config is not None:
        conversation.model_config = model_config
    if system_prompt_template_id is not None:
        await _validate_template(db, system_prompt_template_id, conversation.project_id)
        conversation.system_prompt_template_id = system_prompt_template_id
    if system_prompt_override is not None:
        conversation.system_prompt_override = system_prompt_override
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(db: AsyncSession, conversation_id: str) -> None:
    """删除对话（级联删除消息，ORM cascade + 外键 ondelete=CASCADE）。"""
    conversation = await _get_conversation(db, conversation_id)
    await db.delete(conversation)
    await db.commit()


async def get_messages(db: AsyncSession, conversation_id: str) -> list[Message]:
    """获取对话消息历史（按创建时间正序）。"""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def send_message(
    db: AsyncSession,
    conversation_id: str,
    user_input: str,
    *,
    client: LLMClient,
    config: ApiKeyConfig,
) -> AsyncIterator[str]:
    """流式对话：渲染系统提示词 → 组装消息 → 调用 LLM → 持久化 → 产出 SSE 帧。

    帧格式（docs/TECHv1.md §7.3）：
        event: start  data: {"conversation_id", "user_message_id"}
        event: delta  data: {"content": "..."}      # 逐段正文增量
        event: done   data: {"message_id": "..."}   # assistant 消息 id（流式完成后保存完整内容）
        event: error  data: {"message": "..."}      # LLM 失败（不落 assistant 消息）

    流程：加载对话与最近 20 条历史 → build_context_for_prompt 渲染系统提示词
    （占位符替换见 llm/prompts.py）→ 组装 [system, ...history[-20:], user] →
    client.chat_completion_stream（思维深度映射见 llm/client.py，depth 取自
    conversation.model_config）→ 先持久化 user 消息，流式结束后持久化 assistant 消息。
    对话不存在抛 ConversationNotFound（调用方应在进入流式前先校验）。
    """
    conversation = await _get_conversation(db, conversation_id)
    history = await get_messages(db, conversation_id)
    history = history[-HISTORY_LIMIT:]

    # 渲染有效系统提示词（会话覆盖 > 会话模板 > 项目默认 > 全局默认）
    context = await build_context_for_prompt(
        db,
        conversation.project_id,
        conversation.chapter_id,
        conversation,
        user_input=user_input,
        knowledge_cards=[],
        style_card=None,
    )
    system_prompt = await get_effective_system_prompt(
        db, conversation.project_id, conversation, context
    )

    # 模型配置：depth / temperature / max_tokens 取自会话 model_config
    model_config = conversation.model_config or {}
    depth = model_config.get("depth", "auto")
    temperature = model_config.get("temperature", 0.7)
    max_tokens = model_config.get("max_tokens", 2048)

    # 组装消息：[system, ...history[-20:], user]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": m.role, "content": m.content} for m in history)
    messages.append({"role": "user", "content": user_input})

    # 先持久化 user 消息：即使后续 LLM 失败也不丢失用户输入
    user_msg = Message(conversation_id=conversation_id, role="user", content=user_input)
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)
    yield sse_event(
        "start", {"conversation_id": conversation_id, "user_message_id": user_msg.id}
    )

    # 流式调用 LLM（不生成多候选，单回复）
    parts: list[str] = []
    try:
        async for delta in client.chat_completion_stream(
            messages,
            model=config.model,
            depth=depth,
            user_params={"temperature": temperature, "max_tokens": max_tokens},
            context_length=sum(len(m["content"]) for m in messages),
            knowledge_card_count=0,
        ):
            if not delta:
                continue
            parts.append(delta)
            yield sse_event("delta", {"content": delta})
    except Exception as exc:
        logger.exception("对话流式生成失败（conversation=%s）", conversation_id)
        yield sse_event("error", {"message": str(exc)})
        return

    # 流式完成后保存完整 assistant 回复
    assistant_msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content="".join(parts),
        message_metadata={"model": config.model, "depth": depth},
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)
    yield sse_event("done", {"message_id": assistant_msg.id})
