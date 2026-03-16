from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config.database import AsyncSessionLocal
from ...database.models import ChatRun, ChatRunQueuedTurn, ChatRunSnapshot, ConversationState, Message, User
from ...logging import log_event
from ...services.chat_streams import get_stream_status, request_cancel
from ...services.project_permissions import require_conversation_owner_async
from .event_store_service import append_event_sync

logger = logging.getLogger(__name__)


def _cancel_queued_turns(
    sync_db: Session,
    *,
    conversation_id: str,
    cancelled_at: datetime,
) -> None:
    queued_turns = (
        sync_db.query(ChatRunQueuedTurn)
        .filter(
            ChatRunQueuedTurn.conversation_id == conversation_id,
            ChatRunQueuedTurn.status == "queued",
        )
        .all()
    )
    if not queued_turns:
        return

    queued_run_ids = [str(turn.run_id) for turn in queued_turns if getattr(turn, "run_id", None)]
    queued_user_message_ids = [
        str(turn.user_message_id)
        for turn in queued_turns
        if getattr(turn, "user_message_id", None)
    ]

    for queued_turn in queued_turns:
        queued_turn.status = "cancelled"

    if queued_run_ids:
        queued_runs = (
            sync_db.query(ChatRun)
            .filter(ChatRun.id.in_(queued_run_ids))
            .all()
        )
        for queued_run in queued_runs:
            queued_run.status = "cancelled"
            queued_run.finished_at = cancelled_at

    if queued_user_message_ids:
        queued_user_messages = (
            sync_db.query(Message)
            .filter(Message.id.in_(queued_user_message_ids))
            .all()
        )
        for queued_user_message in queued_user_messages:
            queued_user_message.status = "cancelled"
            queued_user_message.completed_at = cancelled_at


def _complete_cancel_transition_sync(
    sync_db: Session,
    *,
    conversation_id: str,
    cancelled_run_id: str,
    cancel_source: str,
    cancelled_at: datetime,
) -> None:
    append_event_sync(
        sync_db,
        conversation_id=conversation_id,
        run_id=cancelled_run_id,
        event_type="run_state",
        actor="system",
        payload={"status": "cancelled", "source": cancel_source},
    )

    state = (
        sync_db.query(ConversationState)
        .filter(ConversationState.conversation_id == conversation_id)
        .first()
    )
    if state is not None and str(state.active_run_id or "") == cancelled_run_id:
        state.active_run_id = None
        state.awaiting_user_input = False

    (
        sync_db.query(ChatRunSnapshot)
        .filter(
            ChatRunSnapshot.conversation_id == conversation_id,
            ChatRunSnapshot.run_id == cancelled_run_id,
        )
        .delete(synchronize_session=False)
    )

    _cancel_queued_turns(
        sync_db,
        conversation_id=conversation_id,
        cancelled_at=cancelled_at,
    )


async def cancel_conversation_stream(
    *,
    user: User,
    conversation_id: str,
    run_id: Optional[str] = None,
    cancel_source: str,
    log_name: str,
) -> Dict[str, Any]:
    """Cancel the active conversation stream or persist a paused-run cancellation.

    LAT-003: The persisted cancel path now performs a full state transition
    in a single transaction — clearing active_run_id, awaiting_user_input,
    and the ChatRunSnapshot so the conversation is never left in a stuck
    state after cancellation.
    """

    async with AsyncSessionLocal() as authz_db:
        await require_conversation_owner_async(user, conversation_id, authz_db)

    stream_status = await get_stream_status(conversation_id)
    async with AsyncSessionLocal() as db:
        query = (
            select(ChatRun)
            .where(
                ChatRun.conversation_id == conversation_id,
                ChatRun.status.in_(("running", "paused")),
            )
            .order_by(ChatRun.started_at.desc(), ChatRun.created_at.desc())
        )
        if isinstance(run_id, str) and run_id.strip():
            query = query.where(ChatRun.id == run_id.strip())

        target_run = await db.scalar(query)
        if target_run is None:
            return {"status": "no_active_stream", "message": "No active stream found", "persisted": False}

        if stream_status == "running":
            await request_cancel(conversation_id)

        cancelled_at = datetime.now(timezone.utc)
        target_run.status = "cancelled"
        target_run.finished_at = cancelled_at
        cancelled_run_id = str(target_run.id)
        await db.run_sync(
            lambda sync_db: _complete_cancel_transition_sync(
                sync_db,
                conversation_id=conversation_id,
                cancelled_run_id=cancelled_run_id,
                cancel_source=cancel_source,
                cancelled_at=cancelled_at,
            )
        )
        await db.commit()

        log_event(
            logger,
            "INFO",
            log_name,
            "timing",
            conversation_id=conversation_id,
            user_id=str(user.id),
            run_id=cancelled_run_id,
            persisted=True,
        )
        return {"status": "cancelled", "persisted": True}
