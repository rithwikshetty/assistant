"""Message-store append helpers kept for runtime call-site stability."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ...database.models import Conversation, ConversationState, Message, MessagePart


def _truncate_preview(text: Optional[str], limit: int = 255) -> Optional[str]:
    if not isinstance(text, str):
        return None
    normalized = " ".join(text.strip().split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _ensure_state_row(sync_db: Session, conversation_id: str) -> ConversationState:
    from .run_snapshot_service import ensure_conversation_state

    return ensure_conversation_state(db=sync_db, conversation_id=conversation_id)


def _map_event_to_message(
    *,
    conversation_id: str,
    run_id: Optional[str],
    event_type: str,
    actor: str,
    payload: Dict[str, Any],
    created_at: Optional[datetime],
) -> tuple[Message, Optional[Dict[str, Any]]]:
    normalized_event = str(event_type or "").strip().lower()
    normalized_actor = str(actor or "").strip().lower()

    role = "system"
    status = "completed"
    text = payload.get("text") if isinstance(payload.get("text"), str) else ""
    metadata_part: Optional[Dict[str, Any]] = None

    if normalized_event == "user_message":
        role = "user"
        status = "completed"
        metadata_part = {
            "event_type": normalized_event,
            "attachments": payload.get("attachments") if isinstance(payload.get("attachments"), list) else [],
            "request_id": payload.get("request_id"),
        }
    elif normalized_event in {"assistant_message_partial", "assistant_message_final"}:
        role = "assistant"
        raw_status = payload.get("status")
        normalized_status = str(raw_status or "").strip().lower()
        if normalized_status in {"running", "streaming", "pending"}:
            status = "streaming"
        elif normalized_status in {"paused", "awaiting_input"}:
            status = "awaiting_input"
        elif normalized_status in {"failed", "cancelled", "completed"}:
            status = normalized_status
        else:
            status = "completed" if normalized_event.endswith("_final") else "streaming"
    elif normalized_event in {"tool_call", "tool_result", "user_input_request", "user_input_response", "run_state"}:
        role = "assistant" if normalized_actor in {"assistant", "tool"} else "system"
        text = text or ""
        metadata_part = {"event_type": normalized_event, **payload}
        if normalized_event == "run_state":
            state_value = str(payload.get("status") or "").strip().lower()
            if state_value in {"running", "streaming"}:
                status = "streaming"
            elif state_value in {"paused", "awaiting_input"}:
                status = "awaiting_input"
            elif state_value in {"failed", "cancelled", "completed"}:
                status = state_value
    else:
        role = "system" if normalized_actor == "system" else "assistant"
        metadata_part = {"event_type": normalized_event or "unknown", **payload}

    message = Message(
        conversation_id=conversation_id,
        run_id=run_id,
        role=role,
        status=status,
        text=text,
    )
    if isinstance(created_at, datetime):
        message.created_at = created_at
    return message, metadata_part


def _apply_projection(
    *,
    conversation: Conversation,
    state: ConversationState,
    message: Message,
    metadata_part: Optional[Dict[str, Any]],
) -> None:
    now = datetime.now(timezone.utc)
    state.updated_at = now

    if message.role == "user":
        state.last_user_message_id = message.id
        preview = _truncate_preview(message.text)
        if preview:
            state.last_user_preview = preview
    if message.role == "assistant":
        state.last_assistant_message_id = message.id

    if message.role in {"user", "assistant"} and message.status in {"completed", "failed", "cancelled", "awaiting_input", "streaming"}:
        event_time = message.created_at or now
        conversation.last_message_at = event_time

    event_type = str((metadata_part or {}).get("event_type") or "").strip().lower()
    if event_type == "user_input_request":
        state.awaiting_user_input = True
    elif event_type == "user_input_response":
        state.awaiting_user_input = False
    elif event_type == "run_state":
        run_status = str((metadata_part or {}).get("status") or "").strip().lower()
        if run_status in {"completed", "failed", "cancelled"}:
            state.awaiting_user_input = False


def append_event_sync(
    sync_db: Session,
    *,
    conversation_id: str,
    event_type: str,
    actor: str,
    payload: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    phase: Optional[str] = None,
    created_at: Optional[datetime] = None,
    conversation: Optional[Conversation] = None,
) -> Message:
    if conversation is None:
        conversation = (
            sync_db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .with_for_update()
            .first()
        )
    elif str(getattr(conversation, "id", "")) != str(conversation_id):
        raise ValueError("Provided conversation does not match conversation_id")

    if conversation is None:
        raise ValueError("Conversation not found")

    state = _ensure_state_row(sync_db, conversation_id)
    event_payload = dict(payload or {})
    message, metadata_part = _map_event_to_message(
        conversation_id=conversation_id,
        run_id=run_id,
        event_type=event_type,
        actor=actor,
        payload=event_payload,
        created_at=created_at,
    )
    sync_db.add(message)
    sync_db.flush()

    if metadata_part is not None:
        part_payload = dict(metadata_part)
        if phase:
            part_payload["phase"] = phase
        sync_db.add(
            MessagePart(
                message_id=message.id,
                ordinal=0,
                part_type="metadata",
                phase="worklog" if str(phase or "").strip().lower() == "worklog" else "final",
                payload_jsonb=part_payload,
            )
        )
        sync_db.flush()

    _apply_projection(
        conversation=conversation,
        state=state,
        message=message,
        metadata_part=metadata_part,
    )
    return message


def append_events_sync(
    sync_db: Session,
    *,
    conversation_id: str,
    events: Iterable[Dict[str, Any]],
) -> List[Message]:
    appended: List[Message] = []
    for event in events:
        appended.append(
            append_event_sync(
                sync_db,
                conversation_id=conversation_id,
                event_type=str(event.get("event_type") or "unknown"),
                actor=str(event.get("actor") or "system"),
                payload=event.get("payload") if isinstance(event.get("payload"), dict) else {},
                run_id=event.get("run_id") if isinstance(event.get("run_id"), str) else None,
                phase=event.get("phase") if isinstance(event.get("phase"), str) else None,
                created_at=event.get("created_at") if isinstance(event.get("created_at"), datetime) else None,
            )
        )
    return appended


async def append_event_async(
    db: AsyncSession,
    *,
    conversation_id: str,
    event_type: str,
    actor: str,
    payload: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    phase: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> Message:
    return await db.run_sync(
        lambda sync_db: append_event_sync(
            sync_db,
            conversation_id=conversation_id,
            event_type=event_type,
            actor=actor,
            payload=payload,
            run_id=run_id,
            phase=phase,
            created_at=created_at,
        )
    )
