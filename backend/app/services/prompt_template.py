# backend/app/services/prompt_template.py
"""提示词模板服务（docs/TECHv1.md §4.3 / §5.7）。

提供模板 CRUD、查询与复制，供提示词模板 API 及系统提示词渲染
（llm/prompts.py 的 get_effective_system_prompt）使用。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PromptTemplate

VALID_SCOPES = ("global", "project")


class PromptTemplateNotFound(Exception):
    """模板不存在。"""


class PromptTemplateProtected(Exception):
    """系统内置模板不可删除。"""


class PromptTemplateValidationError(ValueError):
    """模板参数不合法（scope / project_id / name 等）。"""


def _validate_scope(scope: str, project_id: Optional[str]) -> None:
    """校验 scope 与 project_id 的搭配关系。"""
    if scope not in VALID_SCOPES:
        raise PromptTemplateValidationError(
            f"scope 必须是 {'/'.join(VALID_SCOPES)}，当前：{scope}"
        )
    if scope == "project" and not project_id:
        raise PromptTemplateValidationError("scope=project 时必须提供 project_id")
    if scope == "global" and project_id:
        raise PromptTemplateValidationError("scope=global 时不应提供 project_id")


async def _get_or_raise(db: AsyncSession, template_id: str) -> PromptTemplate:
    """按 id 查询模板，不存在则抛 PromptTemplateNotFound。"""
    template = await db.get(PromptTemplate, template_id)
    if template is None:
        raise PromptTemplateNotFound(f"提示词模板 {template_id} 不存在")
    return template


async def get_prompt_template_by_id(
    db: AsyncSession, template_id: str
) -> Optional[PromptTemplate]:
    """按 id 查询模板；不存在返回 None（供渲染解析使用）。"""
    return await db.get(PromptTemplate, template_id)


async def list_prompt_templates(
    db: AsyncSession,
    scope: Optional[str] = None,
    project_id: Optional[str] = None,
) -> list[PromptTemplate]:
    """列出模板，可按 scope / project_id 过滤，按创建时间排序。"""
    stmt = select(PromptTemplate)
    if scope:
        stmt = stmt.where(PromptTemplate.scope == scope)
    if project_id:
        stmt = stmt.where(PromptTemplate.project_id == project_id)
    stmt = stmt.order_by(PromptTemplate.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_prompt_template(
    db: AsyncSession,
    name: str,
    content: str,
    scope: str,
    project_id: Optional[str] = None,
    is_system: bool = False,
) -> PromptTemplate:
    """创建模板（scope 为 global / project）。"""
    if not name or not name.strip():
        raise PromptTemplateValidationError("模板名称不能为空")
    _validate_scope(scope, project_id)
    template = PromptTemplate(
        name=name,
        content=content,
        scope=scope,
        project_id=project_id,
        is_system=is_system,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def update_prompt_template(
    db: AsyncSession,
    template_id: str,
    name: Optional[str] = None,
    content: Optional[str] = None,
    scope: Optional[str] = None,
) -> PromptTemplate:
    """更新模板（仅 name / content / scope）。scope 改为 global 时清空 project_id。"""
    template = await _get_or_raise(db, template_id)
    if name is not None:
        if not name.strip():
            raise PromptTemplateValidationError("模板名称不能为空")
        template.name = name
    if content is not None:
        template.content = content
    if scope is not None:
        if scope not in VALID_SCOPES:
            raise PromptTemplateValidationError(
                f"scope 必须是 {'/'.join(VALID_SCOPES)}，当前：{scope}"
            )
        template.scope = scope
        if scope == "global":
            template.project_id = None
    await db.commit()
    await db.refresh(template)
    return template


async def delete_prompt_template(db: AsyncSession, template_id: str) -> None:
    """删除模板；系统内置模板（is_system=True）拒绝删除。"""
    template = await _get_or_raise(db, template_id)
    if template.is_system:
        raise PromptTemplateProtected("系统内置模板不可删除")
    await db.delete(template)
    await db.commit()


async def duplicate_prompt_template(
    db: AsyncSession,
    template_id: str,
    new_name: str,
    target_scope: str,
    target_project_id: Optional[str],
) -> PromptTemplate:
    """复制模板到目标作用域（复制后 is_system=False，可自由修改）。"""
    source = await _get_or_raise(db, template_id)
    if not new_name or not new_name.strip():
        raise PromptTemplateValidationError("新模板名称不能为空")
    _validate_scope(target_scope, target_project_id)
    template = PromptTemplate(
        name=new_name,
        content=source.content,
        scope=target_scope,
        project_id=target_project_id,
        is_system=False,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template
