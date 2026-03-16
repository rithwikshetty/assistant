"""Persist-and-enqueue submit flow for existing conversations."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ...database.models import (
    CONSTRAINT_CHAT_RUNS_CONVERSATION_REQUEST,
    CONSTRAINT_CHAT_RUNS_CONVERSATION_USER_MESSAGE,
    ChatRun,
    ChatRunQueuedTurn,
    Conversation,
    ConversationState,
    User,
)
from ...logging import log_event
from ...services.chat_streams import StreamContext
from ...services.files import file_service
from ...services.project_permissions import require_conversation_owner
from ...utils.integrity import extract_constraint_name, is_constraint_violation
from ..schemas import MessageCreate
from .conversation_creation_service import (
    build_attachment_metadata_list,
    normalize_creation_request_id,
)
from .conversation_service import check_requires_feedback
from .event_store_service import append_event_sync
from .message_preparation_service import build_attachment_metadata_from_ids
from .run_queue_service import enqueue_run_command

import logging

logger = logging.getLogger(__name__)

_IDEMPOTENCY_CONSTRAINT_NAMES = {
    CONSTRAINT_CHAT_RUNS_CONVERSATION_REQUEST,
    CONSTRAINT_CHAT_RUNS_CONVERSATION_USER_MESSAGE,
}


def normalize_message_content(content: str) -> str:
    normalized = content.strip() if isinstance(content, str) else ""
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content is required",
        )
    return normalized


def _is_idempotency_conflict(exc: IntegrityError) -> bool:
    return is_constraint_violation(exc, _IDEMPOTENCY_CONSTRAINT_NAMES)


def _prepare_attachments(
    *,
    sync_db: Session,
    conversation_id: str,
    user_id: str,
    attachment_ids: Optional[List[str]],
) -> List[Dict[str, Any]]:
    normalized_ids = [attachment_id for attachment_id in dict.fromkeys(attachment_ids or []) if attachment_id]
    if not normalized_ids:
        return []

    attachments_meta: List[Dict[str, Any]] = []
    try:
        promoted_files = file_service.promote_staged_files_to_conversation(
            staged_ids=normalized_ids,
            user_id=user_id,
            conversation_id=conversation_id,
            db=sync_db,
        )
        if promoted_files:
            attachments_meta = build_attachment_metadata_list(promoted_files)
    except Exception:
        log_event(
            logger,
            "DEBUG",
            "chat.submit.staged_file_promotion_skipped",
            "retry",
            conversation_id=conversation_id,
            user_id=user_id,
            exc_info=True,
        )

    if attachments_meta:
        return attachments_meta

    try:
        return build_attachment_metadata_from_ids(
            normalized_ids,
            user_id,
            conversation_id,
            sync_db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _find_existing_run_for_request(
    sync_db: Session,
    *,
    conversation_id: str,
    request_id: Optional[str],
) -> Optional[ChatRun]:
    if not request_id:
        return None
    return (
        sync_db.query(ChatRun)
        .filter(
            ChatRun.conversation_id == conversation_id,
            ChatRun.request_id == request_id,
        )
        .order_by(ChatRun.created_at.desc())
        .first()
    )


def _build_existing_run_reuse_response(existing_run: ChatRun) -> Dict[str, Any]:
    existing_status = str(existing_run.status or "queued")
    return {
        "run_id": existing_run.id,
        "user_message_id": existing_run.user_message_id,
        "status": existing_status if existing_status in {"queued", "running"} else "queued",
        "queue_position": 0,
        "reuse_only": True,
    }


def _serialize_prefetched_user(
    *,
    current_user: User,
    effective_timezone: Optional[str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(getattr(current_user, "id", "") or ""),
        "name": getattr(current_user, "name", None),
        "user_tier": getattr(current_user, "user_tier", None),
        "model_override": getattr(current_user, "model_override", None),
    }
    if isinstance(effective_timezone, str) and effective_timezone.strip():
        payload["timezone"] = effective_timezone.strip()
    return payload


def _build_stream_context(
    *,
    user_content: str,
    attachments_meta: List[Dict[str, Any]],
    is_admin: bool,
    is_new_conversation: bool,
    current_user: User,
    effective_timezone: Optional[str],
    project_ctx: Optional[Dict[str, Any]],
    submit_started: float,
    submit_trace_id: str,
) -> StreamContext:
    prefetched_context: Dict[str, Any] = {
        "user": _serialize_prefetched_user(
            current_user=current_user,
            effective_timezone=effective_timezone,
        ),
        "timing": {
            "submit_received_monotonic": submit_started,
            "trace_id": submit_trace_id,
        },
    }
    if isinstance(project_ctx, dict) and project_ctx:
        prefetched_context["conversation_context"] = dict(project_ctx)

    return StreamContext(
        user_content=user_content,
        attachments_meta=attachments_meta,
        is_admin=is_admin,
        is_new_conversation=is_new_conversation,
        prefetched_context=prefetched_context,
    )


def _ensure_state_row(sync_db: Session, conversation_id: str) -> ConversationState:
    """Get or create the ConversationState row with a FOR UPDATE lock.

    LAT-002: Lock the parent conversation row first so initial state-row
    creation is serialized too.  Locking ConversationState alone only
    protects existing rows; it does nothing when two first-submit requests
    both see the row as missing.
    """
    conversation = (
        sync_db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .with_for_update()
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    state = (
        sync_db.query(ConversationState)
        .filter(ConversationState.conversation_id == conversation_id)
        .with_for_update()
        .first()
    )
    if state is not None:
        return state
    state = ConversationState(conversation_id=conversation_id)
    sync_db.add(state)
    sync_db.flush()
    return state


async def submit_existing_conversation(
    conversation_id: str,
    message: MessageCreate,
    *,
    current_user: User,
    db: AsyncSession,
    submit_started: float,
    submit_trace_id: str,
    user_timezone: Optional[str] = None,
    user_locale: Optional[str] = None,
) -> Dict[str, Any]:
    effective_timezone = user_timezone
    del user_locale

    current_user_id = getattr(current_user, "id", None)
    if not current_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User session invalid")
    current_user_id_str = str(current_user_id)
    normalized_content = normalize_message_content(message.content)
    normalized_request_id = normalize_creation_request_id(getattr(message, "request_id", None))
    attachment_ids = list(dict.fromkeys(message.attachments or []))
    is_admin = str(getattr(current_user, "role", "")).lower() == "admin"

    def _db_work(sync_db: Session) -> Dict[str, Any]:
        conversation = require_conversation_owner(current_user, conversation_id, sync_db)
        if getattr(conversation, "archived", False):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

        if not is_admin and check_requires_feedback(conversation, sync_db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Feedback required. Please provide feedback on a recent message to continue chatting.",
            )

        existing_run = _find_existing_run_for_request(
            sync_db,
            conversation_id=conversation_id,
            request_id=normalized_request_id,
        )
        if existing_run is not None:
            return _build_existing_run_reuse_response(existing_run)

        state = _ensure_state_row(sync_db, conversation_id)
        attachments_meta = _prepare_attachments(
            sync_db=sync_db,
            conversation_id=conversation_id,
            user_id=current_user_id_str,
            attachment_ids=attachment_ids,
        )

        created_at = datetime.now(timezone.utc)
        user_message = append_event_sync(
            sync_db,
            conversation_id=conversation_id,
            event_type="user_message",
            actor="user",
            payload={
                "text": normalized_content,
                "attachments": attachments_meta,
                "request_id": normalized_request_id,
            },
            created_at=created_at,
            conversation=conversation,
        )

        active_run_id = str(state.active_run_id) if state.active_run_id else None
        response_status = "running" if not active_run_id else "queued"
        run = ChatRun(
            id=str(uuid4()),
            conversation_id=conversation_id,
            user_message_id=user_message.id,
            request_id=normalized_request_id,
            status=response_status,
            queued_at=created_at,
            started_at=created_at if response_status == "running" else None,
        )
        sync_db.add(run)
        sync_db.flush()

        user_message.run_id = run.id
        queue_position = 0

        if active_run_id:
            queue_position = (
                sync_db.query(ChatRunQueuedTurn)
                .filter(
                    ChatRunQueuedTurn.conversation_id == conversation_id,
                    ChatRunQueuedTurn.status == "queued",
                )
                .count()
            ) + 1
            sync_db.add(
                ChatRunQueuedTurn(
                    conversation_id=conversation_id,
                    run_id=run.id,
                    user_message_id=user_message.id,
                    blocked_by_run_id=active_run_id,
                    status="queued",
                )
            )
        else:
            state.active_run_id = run.id
            state.awaiting_user_input = False

        try:
            sync_db.commit()
        except IntegrityError as exc:
            sync_db.rollback()
            if _is_idempotency_conflict(exc):
                recovered = _find_existing_run_for_request(
                    sync_db,
                    conversation_id=conversation_id,
                    request_id=normalized_request_id,
                )
                if recovered is not None:
                    return _build_existing_run_reuse_response(recovered)
            log_event(
                logger,
                "ERROR",
                "chat.submit.persistence_integrity_failed",
                "error",
                trace_id=submit_trace_id,
                conversation_id=conversation_id,
                user_id=current_user_id_str,
                request_id=normalized_request_id,
                constraint_name=extract_constraint_name(exc, _IDEMPOTENCY_CONSTRAINT_NAMES) or "",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to persist message",
            ) from exc

        stream_context = _build_stream_context(
            user_content=normalized_content,
            attachments_meta=attachments_meta,
            is_admin=is_admin,
            is_new_conversation=False,
            current_user=current_user,
            effective_timezone=effective_timezone,
            project_ctx=None,
            submit_started=submit_started,
            submit_trace_id=submit_trace_id,
        )

        return {
            "run_id": run.id,
            "user_message_id": user_message.id,
            "status": response_status,
            "queue_position": queue_position,
            "stream_context": {
                "user_content": stream_context.user_content,
                "attachments_meta": stream_context.attachments_meta,
                "is_admin": stream_context.is_admin,
                "is_new_conversation": stream_context.is_new_conversation,
                "prefetched_context": stream_context.prefetched_context,
            },
        }

    result = await db.run_sync(_db_work)
    if bool(result.pop("reuse_only", False)):
        return result

    await enqueue_run_command(
        conversation_id=conversation_id,
        run_id=result["run_id"],
        user_id=current_user_id_str,
        user_message_id=result["user_message_id"],
        stream_context=result.get("stream_context") if isinstance(result.get("stream_context"), dict) else None,
    )

    log_event(
        logger,
        "INFO",
        "chat.submit.enqueued",
        "timing",
        trace_id=submit_trace_id,
        conversation_id=conversation_id,
        user_id=current_user_id_str,
        run_id=result["run_id"],
        status=result["status"],
        queue_position=result["queue_position"],
        elapsed_ms=round((perf_counter() - submit_started) * 1000.0, 1),
    )
    return result
