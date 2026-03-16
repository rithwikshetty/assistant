"""Conversation title generation and update routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_async_db
from ...database.models import User, Conversation
from ...auth.dependencies import get_current_user
from ...services.project_permissions import require_conversation_owner_async
from ...utils.coerce import normalize_uuid_string

from ..schemas import TitleUpdateRequest, TitleResponse
from ..services.conversation_service import (
    ensure_conversation_title_async,
    publish_conversation_title_updated,
)

router = APIRouter()


def _normalize_conversation_id_or_404(conversation_id: str) -> str:
    normalized_conversation_id = normalize_uuid_string(conversation_id)
    if normalized_conversation_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return normalized_conversation_id


@router.post("/{conversation_id}/title", response_model=TitleResponse)
async def generate_conversation_title(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Generate a new title for the conversation based on its content"""
    normalized_conversation_id = _normalize_conversation_id_or_404(conversation_id)
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == normalized_conversation_id,
            Conversation.user_id == current_user.id,
        )
    )

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
    )
    if getattr(conversation, "archived", False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    title, _ = await ensure_conversation_title_async(conversation, db)

    return TitleResponse(
        title=title,
        conversation_id=conversation.id,
        updated_at=conversation.updated_at.isoformat() + 'Z',
        generated_at=datetime.now(timezone.utc).isoformat() + 'Z'
    )


@router.put("/{conversation_id}/title", response_model=TitleResponse)
async def update_conversation_title(
    conversation_id: str,
    title_request: TitleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Update the title of a conversation with custom text"""
    # Check ownership permission
    conversation = await require_conversation_owner_async(current_user, conversation_id, db)

    if getattr(conversation, "archived", False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Validate and sanitize title
    new_title = title_request.title.strip()
    if not new_title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title cannot be empty"
        )

    if len(new_title) > 100:  # Reasonable title length limit
        new_title = new_title[:100]

    # Update conversation title only (do not bump last_message_at)
    conversation.title = new_title
    await db.commit()
    await db.refresh(conversation)
    await publish_conversation_title_updated(conversation, source="manual")

    return TitleResponse(
        title=new_title,
        conversation_id=conversation.id,
        updated_at=conversation.updated_at.isoformat() + 'Z',
        generated_at=datetime.now(timezone.utc).isoformat() + 'Z'
    )
