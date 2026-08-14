# backend/app/api/v1/projects.py
"""项目 CRUD API（docs/TECH.md §5.1）。

- GET    /api/v1/projects             项目列表（按创建时间倒序）
- POST   /api/v1/projects             创建项目
- GET    /api/v1/projects/{id}        项目详情
- PATCH  /api/v1/projects/{id}        更新项目
- DELETE /api/v1/projects/{id}        删除项目（级联删除关联数据）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import Project
from ...schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


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
    project = Project(**payload.model_dump())
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
