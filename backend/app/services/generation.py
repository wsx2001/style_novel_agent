# backend/app/services/generation.py
"""生成参数解析服务（docs/TECHv1.md §5.5 / §7.1 / §7.2）。

为续写/重写（及后续扩展）提供两项解析：
- resolve_model_config：解析有效模型配置
  （请求 model_config > 项目默认 default_model_config > 全局默认 global_default_model_config）；
- resolve_generation_system_prompt：解析并渲染系统提示词
  （请求显式模板 > 项目默认模板 > 全局默认模板 > 内置常量兜底），
  渲染使用 llm/prompts.py 的 build_context_for_prompt / get_effective_system_prompt。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AppConfig, Project
from .llm.prompts import get_effective_system_prompt, render_system_prompt
from .prompt_template import get_prompt_template_by_id

# AppConfig 中全局默认模型配置的存储键（database.DEFAULT_APP_CONFIGS 种子值）
GLOBAL_DEFAULT_MODEL_CONFIG_KEY = "global_default_model_config"


class GenerationConfigError(ValueError):
    """生成参数不合法（请求显式指定的模板不存在 / 作用域不匹配）。"""


async def resolve_model_config(
    db: AsyncSession,
    project_id: str,
    request_config: Optional[dict] = None,
) -> dict:
    """解析有效模型配置：请求 model_config > 项目默认 > 全局默认（首个非空 dict 生效）。

    全部未配置时返回 {}，由调用方回退到 legacy 参数
    （请求体 temperature 字段 / DEFAULT_MAX_TOKENS）。
    """
    if isinstance(request_config, dict) and request_config:
        return request_config
    project = await db.get(Project, project_id)
    if (
        project is not None
        and isinstance(project.default_model_config, dict)
        and project.default_model_config
    ):
        return project.default_model_config
    value = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_MODEL_CONFIG_KEY)
    )
    if isinstance(value, dict) and value:
        return value
    return {}


async def resolve_generation_system_prompt(
    db: AsyncSession,
    project_id: str,
    template_id: Optional[str],
    context: dict[str, str],
    builtin: str,
) -> str:
    """解析并渲染系统提示词（docs/TECHv1.md §7.1）。

    优先级：请求显式模板 > 项目默认模板 > 全局默认模板 > 内置常量（保持旧行为）。
    - 请求显式指定的模板不存在，或项目作用域模板不属于该项目 → GenerationConfigError；
    - 项目/全局默认模板经 get_effective_system_prompt 解析（未配置时返回空串）；
    - 均未命中时返回内置常量。
    """
    if template_id:
        template = await get_prompt_template_by_id(db, template_id)
        if template is None:
            raise GenerationConfigError(f"提示词模板 {template_id} 不存在")
        if template.scope == "project" and template.project_id != project_id:
            raise GenerationConfigError(
                f"项目作用域模板 {template_id} 不属于项目 {project_id}"
            )
        return render_system_prompt(template.content, context)
    effective = await get_effective_system_prompt(db, project_id, None, context)
    return effective or builtin
