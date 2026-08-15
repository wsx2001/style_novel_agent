# backend/app/api/v1/prompt_templates.py
"""提示词模板管理 API（docs/TECHv1.md §5.7）。

- GET    /prompt-templates?scope=&project_id=       模板列表（全局/项目，按作用域过滤）
- POST   /prompt-templates                           创建模板（name/content/scope/project_id?）
- GET    /prompt-templates/{template_id}             模板详情
- PATCH  /prompt-templates/{template_id}             更新模板（name/content/scope）
- DELETE /prompt-templates/{template_id}             删除模板（系统内置模板 → 403）
- POST   /prompt-templates/{template_id}/duplicate   复制模板（生成新模板）

错误处理：模板/项目不存在 → 404；系统模板删除 → 403；
scope 与 project_id 搭配不合法 / 空名称 → 400。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import Project, PromptTemplate
from ...schemas.prompt_template import (
    PromptTemplateCreate,
    PromptTemplateDuplicate,
    PromptTemplateRead,
    PromptTemplateUpdate,
)
from ...services import prompt_template as prompt_template_service
from ...services.prompt_template import (
    PromptTemplateNotFound,
    PromptTemplateProtected,
    PromptTemplateValidationError,
)

router = APIRouter(prefix="/api/v1", tags=["prompt_templates"])

VALID_SCOPES = ("global", "project")


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    """按 id 查询项目，不存在则抛 404（创建项目模板时校验归属）。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


async def _get_template_or_404(template_id: str, db: AsyncSession) -> PromptTemplate:
    """按 id 查询模板，不存在则抛 404。"""
    template = await db.get(PromptTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"提示词模板 {template_id} 不存在",
        )
    return template


def _validate_scope_query(scope: Optional[str]) -> None:
    """校验列表查询参数 scope 的取值。"""
    if scope is not None and scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"scope 必须是 {'/'.join(VALID_SCOPES)}，当前：{scope}",
        )


@router.get(
    "/prompt-templates",
    response_model=list[PromptTemplateRead],
    summary="模板列表（?scope=&project_id= 过滤）",
)
async def list_prompt_templates(
    scope: Optional[str] = Query(default=None),
    project_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list:
    """列出可用模板：scope=global 返回全局模板，scope=project 需 project_id 匹配。"""
    _validate_scope_query(scope)
    return await prompt_template_service.list_prompt_templates(db, scope, project_id)


@router.post(
    "/prompt-templates",
    response_model=PromptTemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建模板",
)
async def create_prompt_template(
    payload: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建模板；scope=project 时校验 project_id 存在。"""
    if payload.scope == "project" and payload.project_id:
        await _get_project_or_404(payload.project_id, db)
    try:
        return await prompt_template_service.create_prompt_template(
            db,
            name=payload.name,
            content=payload.content,
            scope=payload.scope,
            project_id=payload.project_id,
        )
    except PromptTemplateValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get(
    "/prompt-templates/{template_id}",
    response_model=PromptTemplateRead,
    summary="模板详情",
)
async def get_prompt_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await _get_template_or_404(template_id, db)


@router.patch(
    "/prompt-templates/{template_id}",
    response_model=PromptTemplateRead,
    summary="更新模板（name/content/scope）",
)
async def update_prompt_template(
    template_id: str,
    payload: PromptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    """仅更新显式传入的字段；scope 改为 project 时要求模板已绑定 project_id。"""
    template = await _get_template_or_404(template_id, db)
    updates = payload.model_dump(exclude_unset=True)
    # 服务层不支持经 PATCH 修改 project_id：global → project 需模板已绑定项目
    if updates.get("scope") == "project" and template.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project 作用域模板必须绑定 project_id（可通过 /duplicate 复制到项目）",
        )
    try:
        return await prompt_template_service.update_prompt_template(
            db, template_id, **updates
        )
    except PromptTemplateValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete(
    "/prompt-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除模板（系统内置模板 → 403）",
)
async def delete_prompt_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await prompt_template_service.delete_prompt_template(db, template_id)
    except PromptTemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except PromptTemplateProtected as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc


@router.post(
    "/prompt-templates/{template_id}/duplicate",
    response_model=PromptTemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="复制模板（生成新模板）",
)
async def duplicate_prompt_template(
    template_id: str,
    payload: PromptTemplateDuplicate,
    db: AsyncSession = Depends(get_db),
):
    """复制模板到目标作用域（复制后 is_system=False，可自由修改）。"""
    await _get_template_or_404(template_id, db)
    if payload.scope == "project" and payload.project_id:
        await _get_project_or_404(payload.project_id, db)
    try:
        return await prompt_template_service.duplicate_prompt_template(
            db,
            template_id,
            new_name=payload.new_name,
            target_scope=payload.scope,
            target_project_id=payload.project_id,
        )
    except PromptTemplateValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
