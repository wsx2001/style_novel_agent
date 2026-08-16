# backend/app/api/v1/projects.py
"""项目 CRUD API（docs/TECH.md §5.1；V1 创建时继承全局默认，docs/TECHv1.md §5.8）。

- GET    /api/v1/projects             项目列表（按创建时间倒序）
- POST   /api/v1/projects             创建项目（继承全局默认模型配置与提示词模板）
- GET    /api/v1/projects/{id}        项目详情
- PATCH  /api/v1/projects/{id}        更新项目
- DELETE /api/v1/projects/{id}        删除项目（级联删除关联数据）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import AppConfig, ModelProvider, Project
from ...schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from ...services.generation import GLOBAL_DEFAULT_MODEL_CONFIG_KEY
from ...services.llm.prompts import GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY
from ...services.llm.resolve import GLOBAL_DEFAULT_MODEL_KEY
from ...services.model_provider import GLOBAL_DEFAULT_PROVIDER_KEY
from ...services.prompt_template import get_prompt_template_by_id

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

# 项目默认模型配置（全局未配置时的兜底值，与模型列默认一致）
DEFAULT_PROJECT_MODEL_CONFIG = {
    "depth": "auto",
    "temperature": 0.7,
    "max_tokens": 2048,
}


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    """按 id 查询项目，不存在则抛 404。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


@router.get("", response_model=list[ProjectRead], summary="项目列表（按创建时间倒序）")
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[Project]:
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED, summary="创建项目")
async def create_project(
    payload: ProjectCreate, db: AsyncSession = Depends(get_db)
) -> Project:
    """创建项目；继承全局默认模型配置 / 提示词模板 / 提供商与模型。

    V1 将全局默认模型配置复制到项目默认，全局默认模板 ID 复制到项目默认模板。
    V1.1 起创建时可显式传 default_provider_id / default_model_id 覆盖继承
    （docs/TECHv1.1.md §5.2）：未传（或传空）时从全局默认复制；全局也未配置
    时为 None（生成时经 services/llm/resolve 回退全局或提示配置）。
    """
    data = payload.model_dump()
    global_model_config = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_MODEL_CONFIG_KEY)
    )
    global_template_id = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY)
    )
    global_provider_id = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_PROVIDER_KEY)
    )
    global_model_id = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_MODEL_KEY)
    )
    default_model_config = (
        dict(global_model_config)
        if isinstance(global_model_config, dict) and global_model_config
        else dict(DEFAULT_PROJECT_MODEL_CONFIG)
    )
    default_prompt_template_id = str(global_template_id) if global_template_id else None

    # 请求显式指定时优先使用，否则回退全局默认（docs/TECHv1.1.md §5.2）
    default_provider_id = data.pop("default_provider_id", None)
    default_model_id = data.pop("default_model_id", None)
    if not default_provider_id:
        default_provider_id = str(global_provider_id) if global_provider_id else None
    if not default_model_id:
        default_model_id = str(global_model_id) if global_model_id else None
    if default_provider_id:
        provider = await db.get(ModelProvider, default_provider_id)
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"模型提供商 {default_provider_id} 不存在",
            )
    project = Project(
        **data,
        default_model_config=default_model_config,
        default_prompt_template_id=default_prompt_template_id,
        default_provider_id=default_provider_id,
        default_model_id=default_model_id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead, summary="项目详情")
async def get_project(
    project_id: str, db: AsyncSession = Depends(get_db)
) -> Project:
    return await _get_project_or_404(project_id, db)


@router.patch("/{project_id}", response_model=ProjectRead, summary="更新项目")
async def update_project(
    project_id: str, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)
) -> Project:
    project = await _get_project_or_404(project_id, db)
    # exclude_unset：仅更新请求体显式传入的字段，未传字段保持不变
    updates = payload.model_dump(exclude_unset=True)
    if "default_prompt_template_id" in updates:
        template_id = updates["default_prompt_template_id"]
        if template_id:
            template = await get_prompt_template_by_id(db, template_id)
            if template is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"提示词模板 {template_id} 不存在",
                )
            if template.scope == "project" and template.project_id != project_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="该模板是其他项目的项目模板，不能设为当前项目的默认模板",
                )
        # 显式传 null / 空串 → 清空默认模板（生成时回退全局）
        updates["default_prompt_template_id"] = template_id or None
    if "default_provider_id" in updates:
        provider_id = updates["default_provider_id"]
        if provider_id:
            provider = await db.get(ModelProvider, provider_id)
            if provider is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"模型提供商 {provider_id} 不存在",
                )
        # 显式传 null / 空串 → 清空项目默认提供商（生成时回退全局）
        updates["default_provider_id"] = provider_id or None
    for field, value in updates.items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除项目（级联删除关联数据）")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)) -> None:
    project = await _get_project_or_404(project_id, db)
    # ORM 级联（relationship cascade="all, delete-orphan"）+ DB 外键 ondelete=CASCADE
    await db.delete(project)
    await db.commit()
