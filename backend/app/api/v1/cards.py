# backend/app/api/v1/cards.py
"""知识卡 API（docs/TECH.md §5.3）。

- GET    /api/v1/projects/{project_id}/cards   卡片列表（?card_type= 过滤，?q= 标题搜索）
- POST   /api/v1/projects/{project_id}/cards   手动新建知识卡
- GET    /api/v1/cards/{card_id}               卡片详情
- PATCH  /api/v1/cards/{card_id}               更新知识卡
- DELETE /api/v1/cards/{card_id}               删除知识卡
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import KnowledgeCard, Project
from ...schemas.card import CardCreate, CardRead, CardUpdate
from ...schemas.document import CardType

router = APIRouter(prefix="/api/v1", tags=["cards"])


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    """按 id 查询项目，不存在则抛 404。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


async def _get_card_or_404(card_id: str, db: AsyncSession) -> KnowledgeCard:
    """按 id 查询知识卡，不存在则抛 404。"""
    card = await db.get(KnowledgeCard, card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"知识卡 {card_id} 不存在",
        )
    return card


@router.get(
    "/projects/{project_id}/cards",
    response_model=list[CardRead],
    summary="卡片列表（?card_type= 过滤，?q= 标题搜索）",
)
async def list_cards(
    project_id: str,
    card_type: Optional[CardType] = Query(default=None),
    q: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeCard]:
    """按创建时间倒序返回项目卡片，支持按类型过滤与标题关键词搜索。"""
    await _get_project_or_404(project_id, db)
    stmt = select(KnowledgeCard).where(KnowledgeCard.project_id == project_id)
    if card_type is not None:
        stmt = stmt.where(KnowledgeCard.card_type == card_type)
    if q:
        stmt = stmt.where(KnowledgeCard.title.contains(q))
    result = await db.execute(stmt.order_by(KnowledgeCard.created_at.desc()))
    return list(result.scalars().all())


@router.post(
    "/projects/{project_id}/cards",
    response_model=CardRead,
    status_code=status.HTTP_201_CREATED,
    summary="手动新建知识卡",
)
async def create_card(
    project_id: str,
    payload: CardCreate,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeCard:
    """手动创建知识卡（不关联片段，不写入向量库）。"""
    await _get_project_or_404(project_id, db)
    card = KnowledgeCard(project_id=project_id, **payload.model_dump())
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


@router.get("/cards/{card_id}", response_model=CardRead, summary="知识卡详情")
async def get_card(
    card_id: str, db: AsyncSession = Depends(get_db)
) -> KnowledgeCard:
    return await _get_card_or_404(card_id, db)


@router.patch("/cards/{card_id}", response_model=CardRead, summary="更新知识卡")
async def update_card(
    card_id: str,
    payload: CardUpdate,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeCard:
    card = await _get_card_or_404(card_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(card, field, value)
    await db.commit()
    await db.refresh(card)
    return card


@router.delete(
    "/cards/{card_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除知识卡",
)
async def delete_card(card_id: str, db: AsyncSession = Depends(get_db)) -> None:
    card = await _get_card_or_404(card_id, db)
    await db.delete(card)
    await db.commit()
