# backend/app/services/llm/prompts.py
"""LLM Prompt 模板（docs/TECH.md 第 7 节风格：中文、明确约束、只输出目标内容）。

当前提供文档设定抽取相关模板，供 services/parsing/extractor.py 使用。
"""
from __future__ import annotations

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
