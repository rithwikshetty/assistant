"""Helpers for promoting queued follow-ups at safe server-owned checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database.models import ChatRunQueuedTurn, Message
from ...logging import log_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueuedTurnHandoff:
    run_id: str
    user_message_id: str
    created_at: Optional[datetime]


async def peek_queued_turn_handoff(
    *,
    db: AsyncSession,
    conversation_id: str,
    blocked_by_run_id: str,
) -> Optional[QueuedTurnHandoff]:
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_blocked_by_run_id = str(blocked_by_run_id or "").strip()
    if not normalized_conversation_id or not normalized_blocked_by_run_id:
        return None

    row = await db.execute(
        select(ChatRunQueuedTurn, Message.created_at)
        .join(Message, Message.id == ChatRunQueuedTurn.user_message_id)
        .where(
            ChatRunQueuedTurn.conversation_id == normalized_conversation_id,
            ChatRunQueuedTurn.blocked_by_run_id == normalized_blocked_by_run_id,
            ChatRunQueuedTurn.status == "queued",
        )
        .order_by(ChatRunQueuedTurn.created_at.asc(), ChatRunQueuedTurn.id.asc())
        .limit(1)
    )
    match = row.first()
    if match is None:
        return None

    queued_turn, message_created_at = match
    run_id = str(getattr(queued_turn, "run_id", "") or "").strip()
    user_message_id = str(getattr(queued_turn, "user_message_id", "") or "").strip()
    if not run_id or not user_message_id:
        return None

    log_event(
        logger,
        "INFO",
        "chat.queue.handoff_ready",
        "timing",
        conversation_id=normalized_conversation_id,
        blocked_by_run_id=normalized_blocked_by_run_id,
        queued_run_id=run_id,
        queued_user_message_id=user_message_id,
    )
    return QueuedTurnHandoff(
        run_id=run_id,
        user_message_id=user_message_id,
        created_at=message_created_at if isinstance(message_created_at, datetime) else None,
    )
