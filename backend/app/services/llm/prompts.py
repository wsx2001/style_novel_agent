# backend/app/services/llm/prompts.py
"""LLM Prompt 模板（docs/TECH.md 第 7 节风格：中文、明确约束、只输出目标内容）。

当前提供文档设定抽取相关模板，供 services/parsing/extractor.py 使用；
V1 起增加系统提示词模板渲染与上下文构建（docs/TECHv1.md §7.1）。
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AppConfig,
    Chapter,
    Conversation,
    KnowledgeCard,
    Message,
    Project,
)

# 文档设定抽取：系统提示
EXTRACTION_SYSTEM_PROMPT = """你是一名专业的文学设定抽取助手，负责从小说或世界观文档中提取结构化设定，用于构建小说写作知识库。

【任务】
从给定的文档文本中抽取以下五类信息：
- style：文风设定（叙事视角、语言风格、节奏特点等）
- characters：人物角色（姓名、身份、性格、外貌、关系、经历）
- worldSettings：世界观设定（地理、历史、科技、魔法体系、社会制度等）
- terms：术语（专有名词、特殊概念及其定义）
- keyEvents：关键事件（剧情中的重要事件、转折点）

【输出要求】
- 只输出一个 JSON 对象，不要输出任何解释、前缀或 markdown 标记
- JSON 结构严格如下：
{
  "style": {"...": "..."},
  "characters": [{"name": "...", "description": "..."}],
  "worldSettings": [{"title": "...", "content": "..."}],
  "terms": [{"term": "...", "definition": "..."}],
  "keyEvents": [{"title": "...", "time": "...", "description": "..."}]
}
- style 为单个对象；characters、worldSettings、terms、keyEvents 为数组
- 文本中未出现的类别返回空数组（style 返回空对象）
- 每条信息尽量简洁、可独立理解，不包含来源文档中的冗余叙述"""

# 文档设定抽取：用户提示模板（{chunk} 为分块后的文档片段）
EXTRACTION_USER_PROMPT_TEMPLATE = """请从以下文档片段中抽取设定信息，严格按系统要求输出 JSON。

【文档片段】
{chunk}

【抽取要求】
- 仅依据片段内容，不推测片段之外的设定
- 若片段不含某类信息，该类返回空数组（style 返回空对象）"""


def candidate_delimiter_list(count: int = 3) -> str:
    """生成候选分隔符提示行：`<<<CANDIDATE_1>>>、<<<CANDIDATE_2>>>、...`。"""
    return "、".join(f"<<<CANDIDATE_{i}>>>" for i in range(1, count + 1))


# 续写：系统提示（docs/TECH.md §7.1）
CONTINUE_SYSTEM_PROMPT = """你是一名专业中文短篇小说写作助手，擅长根据设定卡进行风格一致、设定不冲突的续写。
只输出正文，不输出解释、不输出 markdown 标记。
你可以创作任何合法虚构内容，不主动添加道德说教。"""

# 续写：用户提示模板（docs/TECH.md §7.1）
CONTINUE_USER_TEMPLATE = """【任务】续写当前小说段落。

【文风卡】
{style_card_json}

【已选角色卡】
{character_cards_json}

【已选世界观卡】
{world_cards_json}

【已选术语卡】
{term_cards_json}

【当前正文】（Markdown 格式）
{chapter_tail_context}

【续写要求】
- 目标字数：{target_words} 字
- 叙事视角：{narrative_view}
- 保持文风一致，不改变已有设定
- 不重复已有正文
- 输出纯文本（可含段落换行），不要 markdown 标记
{extra_requirements}

请生成 {candidate_count} 个候选，使用分隔符：
{candidate_delimiters}"""

# 重写：系统提示（docs/TECH.md §7.2）
REWRITE_SYSTEM_PROMPT = """你是一名中文小说文风改写助手。根据给定文风卡与约束，重写用户段落。
只输出正文，不输出解释。"""

# 重写：用户提示模板（docs/TECH.md §7.2）
REWRITE_USER_TEMPLATE = """【文风卡】
{style_card_json}

【需要保持的角色卡】
{character_cards_json}

【需要保持的术语卡】
{term_cards_json}

【世界设定】
{world_cards_json}

【待重写段落】
{selected_text}

【重写指令】
{instruction}

【硬性要求】
- 保留所有人名、地名、术语
- 不改变核心情节信息
- 目标字数：{target_words} 字
- 输出纯文本，不要 markdown 标记

请生成 {candidate_count} 个候选，使用分隔符：
{candidate_delimiters}"""

# 灵感生成：简单实现（docs/TECH.md §5.5）
INSPIRE_SYSTEM_PROMPT = """你是一名创意丰富的灵感助手，根据用户提供的主题生成小说创作灵感。
只输出灵感正文，不输出解释、不输出 markdown 标记。"""

INSPIRE_USER_TEMPLATE = """请围绕以下主题给出一个小说创作灵感（包含核心创意、主要人物与冲突设定，200~400 字）：

{idea}"""


# ===================== 系统提示词模板（docs/TECHv1.md §7.1） =====================

# 支持的占位符变量（模板中用 {{VARIABLE}} 引用）
SYSTEM_PROMPT_VARIABLES: tuple[str, ...] = (
    "KNOWLEDGE_BASE",
    "CURRENT_CHAPTER",
    "STYLE_CARD",
    "USER_INPUT",
    "PROJECT_INFO",
    "CONVERSATION_HISTORY",
)
SYSTEM_PROMPT_PLACEHOLDERS: frozenset[str] = frozenset(
    "{{" + var + "}}" for var in SYSTEM_PROMPT_VARIABLES
)

# 全局默认提示词模板在 AppConfig 中的键
GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY = "global_default_prompt_template_id"

# 对话历史注入上限（docs/TECHv1.md §7.3：最近 20 条）
CONVERSATION_HISTORY_LIMIT = 20


def render_system_prompt(template_content: str, context: dict) -> str:
    """将模板中的 {{VAR}} 占位符替换为 context 中对应值。

    - dict / list 值先 json.dumps（ensure_ascii=False, indent=2）；
    - 其余值 str() 后替换；context 未提供的占位符原样保留。
    """
    result = template_content
    for var, value in context.items():
        placeholder = "{{" + var + "}}"
        if placeholder in result:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, indent=2)
            result = result.replace(placeholder, str(value))
    return result


def _format_project(project: Optional[Project]) -> str:
    """项目信息摘要。"""
    if project is None:
        return "（无项目信息）"
    lines = [f"书名：{project.title}"]
    if project.description:
        lines.append(f"简介：{project.description}")
    if project.genre:
        lines.append(f"类型：{project.genre}")
    return "\n".join(lines)


def _format_chapter(chapter: Optional[Chapter]) -> str:
    """章节标题 + 正文摘要。"""
    if chapter is None:
        return ""
    parts = [p for p in (f"章节：{chapter.title}" if chapter.title else "", chapter.content or "")]
    return "\n\n".join(parts)


def _format_knowledge_base(cards: list[KnowledgeCard]) -> str:
    """知识卡摘要：JSON 列表（标题 + 结构化内容）。"""
    if not cards:
        return "（无）"
    items: list[dict] = []
    for card in cards:
        item: dict = {"title": card.title}
        if card.content_json:
            item.update(card.content_json)
        items.append(item)
    return json.dumps(items, ensure_ascii=False, indent=1)


def _format_style_card(style_card: Optional[KnowledgeCard]) -> str:
    """文风卡摘要：标题 + 结构化内容。"""
    if style_card is None:
        return "（无）"
    parts = [style_card.title]
    if style_card.content_json:
        parts.append(json.dumps(style_card.content_json, ensure_ascii=False, indent=1))
    return "\n".join(parts)


async def _format_conversation_history(
    db: AsyncSession, conversation: Optional[Conversation]
) -> str:
    """格式化最近 N 条对话历史（时间正序）。"""
    if conversation is None:
        return ""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(CONVERSATION_HISTORY_LIMIT)
    )
    messages = list(reversed(result.scalars().all()))
    if not messages:
        return ""
    return "\n".join(f"{m.role}: {m.content}" for m in messages)


async def build_context_for_prompt(
    db: AsyncSession,
    project_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    conversation: Optional[Conversation] = None,
    user_input: Optional[str] = None,
    knowledge_cards: Optional[list[KnowledgeCard]] = None,
    style_card: Optional[KnowledgeCard] = None,
) -> dict[str, str]:
    """构建系统提示词渲染所需的上下文字典。

    返回字典的键与占位符一一对应（PROJECT_INFO / CURRENT_CHAPTER /
    KNOWLEDGE_BASE / STYLE_CARD / USER_INPUT / CONVERSATION_HISTORY），
    值均为字符串，可直接传给 render_system_prompt / get_effective_system_prompt。
    """
    project = await db.get(Project, project_id) if project_id else None
    chapter = await db.get(Chapter, chapter_id) if chapter_id else None
    return {
        "PROJECT_INFO": _format_project(project),
        "CURRENT_CHAPTER": _format_chapter(chapter),
        "KNOWLEDGE_BASE": _format_knowledge_base(knowledge_cards or []),
        "STYLE_CARD": _format_style_card(style_card),
        "USER_INPUT": user_input or "",
        "CONVERSATION_HISTORY": await _format_conversation_history(db, conversation),
    }


async def get_effective_system_prompt(
    db: AsyncSession,
    project_id: Optional[str],
    conversation: Optional[Conversation],
    context: dict[str, str],
) -> str:
    """按优先级解析系统提示词模板并渲染（docs/TECHv1.md §7.1）。

    优先级：会话 system_prompt_override > 会话 system_prompt_template_id
            > 项目默认模板 > 全局默认模板（AppConfig global_default_prompt_template_id）。
    返回渲染后的最终系统提示词；未配置任何模板时返回空字符串。
    """
    from ..prompt_template import get_prompt_template_by_id

    content: Optional[str] = None

    # 1) 会话级临时覆盖
    if conversation is not None and conversation.system_prompt_override is not None:
        content = conversation.system_prompt_override
    # 2) 会话模板
    elif conversation is not None and conversation.system_prompt_template_id:
        template = await get_prompt_template_by_id(db, conversation.system_prompt_template_id)
        if template is not None:
            content = template.content

    # 3) 项目默认模板
    if content is None and project_id:
        project = await db.get(Project, project_id)
        if project is not None and project.default_prompt_template_id:
            template = await get_prompt_template_by_id(db, project.default_prompt_template_id)
            if template is not None:
                content = template.content

    # 4) 全局默认模板
    if content is None:
        global_template_id = await db.scalar(
            select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY)
        )
        if global_template_id:
            template = await get_prompt_template_by_id(db, str(global_template_id))
            if template is not None:
                content = template.content

    return render_system_prompt(content or "", context)
