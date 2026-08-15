# backend/app/api/v1/conversations.py
"""对话管理 API（docs/TECHv1.md §5.6）。

- GET    /api/v1/projects/{project_id}/conversations        列出项目下所有对话
- POST   /api/v1/projects/{project_id}/conversations        创建对话（title/chapter_id/model_config/system_prompt_template_id）
- GET    /api/v1/conversations/{conversation_id}            对话详情（含消息列表）
- PATCH  /api/v1/conversations/{conversation_id}            更新对话（标题/模型配置/提示词模板/临时覆盖）
- DELETE /api/v1/conversations/{conversation_id}            删除对话（级联删除消息）
- POST   /api/v1/conversations/{conversation_id}/messages   发送消息（SSE 流式，单回复）
- GET    /api/v1/conversations/{conversation_id}/messages    消息历史（时间正序）

错误处理：项目/对话/消息不存在 → 404；章节归属 / 模板作用域 / 未配 API Key → 400。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import Project
from ...schemas.conversation import (
    ConversationCreate,
    ConversationDetailRead,
    ConversationRead,
    ConversationUpdate,
    MessageRead,
    MessageSendRequest,
)
from ...services import conversation as conversation_service
from ...services.conversation import (
    ConversationNotFound,
    ConversationValidationError,
    ProjectNotFound,
)
from .llm_deps import find_api_key_config, resolve_client

router = APIRouter(prefix="/api/v1", tags=["conversations"])


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    """按 id 查询项目，不存在则抛 404。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


@router.get(
    "/projects/{project_id}/conversations",
    response_model=list[ConversationRead],
    summary="列出项目下所有对话（按创建时间倒序）",
)
async def list_conversations(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> list:
    await _get_project_or_404(project_id, db)
    return await conversation_service.list_conversations(db, project_id)


@router.post(
    "/projects/{project_id}/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建对话",
)
async def create_conversation(
    project_id: str,
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建对话；请求体键 model_config 经别名映射到 conversation_config。"""
    await _get_project_or_404(project_id, db)
    try:
        conversation = await conversation_service.create_conversation(
            db, project_id, **payload.model_dump(by_alias=True)
        )
    except ProjectNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ConversationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return conversation


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailRead,
    summary="对话详情（含消息列表）",
)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await conversation_service.get_conversation(db, conversation_id)
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
    summary="更新对话（标题/模型配置/提示词模板/临时覆盖）",
)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
):
    """仅更新请求体显式传入的字段（exclude_unset）。"""
    updates = payload.model_dump(exclude_unset=True, by_alias=True)
    try:
        return await conversation_service.update_conversation(
            db, conversation_id, **updates
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ConversationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除对话（级联删除消息）",
)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await conversation_service.delete_conversation(db, conversation_id)
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/conversations/{conversation_id}/messages",
    summary="发送消息（SSE 流式，单回复）",
    responses={
        200: {
            "description": "SSE 事件流（start / delta / done / error）",
        }
    },
)
async def send_message(
    conversation_id: str,
    payload: MessageSendRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """发送用户消息并触发 AI 流式回复（docs/TECHv1.md §7.3）。

    进入流式前完成对话存在性与 API Key 校验，错误以 HTTP 状态返回；
    流式开始后的 LLM 失败以 SSE error 事件下发。
    """
    try:
        conversation = await conversation_service.get_conversation(db, conversation_id)
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    config = await find_api_key_config(db, conversation.project_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先在设置中配置 API Key",
        )
    _, client = resolve_client(config)

    async def event_stream():
        async for frame in conversation_service.send_message(
            db,
            conversation_id,
            payload.content,
            client=client,
            config=config,
        ):
            yield frame

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageRead],
    summary="消息历史（时间正序）",
)
async def list_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
) -> list:
    try:
        await conversation_service.get_conversation(db, conversation_id)
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return await conversation_service.get_messages(db, conversation_id)
