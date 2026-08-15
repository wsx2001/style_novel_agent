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
from ...models import AppConfig, Project
from ...schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from ...services.generation import GLOBAL_DEFAULT_MODEL_CONFIG_KEY
from ...services.llm.prompts import GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY

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
    """创建项目；V1 起将全局默认模型配置复制到项目默认，全局默认模板 ID 复制到项目默认模板。

    未配置全局默认时使用标准默认模型配置；默认提示词模板可空（生成时回退到全局）。
    """
    global_model_config = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_MODEL_CONFIG_KEY)
    )
    global_template_id = await db.scalar(
        select(AppConfig.value).where(AppConfig.key == GLOBAL_DEFAULT_PROMPT_TEMPLATE_KEY)
    )
    default_model_config = (
        dict(global_model_config)
        if isinstance(global_model_config, dict) and global_model_config
        else dict(DEFAULT_PROJECT_MODEL_CONFIG)
    )
    default_prompt_template_id = str(global_template_id) if global_template_id else None
    project = Project(
        **payload.model_dump(),
        default_model_config=default_model_config,
        default_prompt_template_id=default_prompt_template_id,
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
    for field, value in payload.model_dump(exclude_unset=True).items():
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
