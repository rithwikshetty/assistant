"""Active run snapshot helpers for recovery state and queued-turn metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ...database.models import ChatRunQueuedTurn, ChatRunSnapshot, ConversationState, Message, PendingUserInput
from ..interactive_tools import canonicalize_interactive_request_payload
from .run_activity_service import list_run_activity_items

_TRANSIENT_ASSISTANT_STATUSES = {
    "streaming",
    "pending",
    "paused",
    "awaiting_input",
    "running",
}


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _timeline_seq(value: Any) -> int:
    if not isinstance(value, datetime):
        return 0
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def _normalize_pending_requests(raw: Any) -> List[Dict[str, Any]]:
    """Canonicalize interactive pending-request payloads regardless of source."""
    if not isinstance(raw, list):
        return []
    pending_requests: List[Dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        call_id = entry.get("call_id")
        tool_name = entry.get("tool_name")
        if not isinstance(call_id, str) or not call_id.strip():
            continue
        if not isinstance(tool_name, str) or not tool_name.strip():
            continue
        request_payload = canonicalize_interactive_request_payload(
            tool_name,
            entry.get("request"),
        )
        pending_requests.append(
            {
                "call_id": call_id.strip(),
                "tool_name": tool_name.strip(),
                "request": request_payload,
                "result": entry.get("result") if isinstance(entry.get("result"), dict) else {},
            }
        )
    return pending_requests


def _serialize_runtime_live_message(
    *,
    message: Message,
    activity_items: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    role = str(getattr(message, "role", "") or "").strip().lower()
    if role != "assistant":
        return None

    raw_status = str(getattr(message, "status", "") or "").strip().lower()
    if raw_status not in _TRANSIENT_ASSISTANT_STATUSES:
        return None

    payload: Dict[str, Any] = {
        "text": message.text if isinstance(message.text, str) else "",
        "status": raw_status or "streaming",
        "model_provider": message.model_provider,
        "model_name": message.model_name,
        "finish_reason": message.finish_reason,
    }
    if isinstance(message.response_latency_ms, int):
        payload["response_latency_ms"] = message.response_latency_ms
    if message.cost_usd is not None:
        try:
            payload["cost_usd"] = float(message.cost_usd)
        except Exception:
            pass

    return {
        "id": str(message.id),
        "seq": _timeline_seq(getattr(message, "created_at", None)),
        "run_id": str(message.run_id) if getattr(message, "run_id", None) else None,
        "type": "assistant_message_partial",
        "actor": "assistant",
        "created_at": _iso(getattr(message, "created_at", None)),
        "role": "assistant",
        "text": payload["text"],
        "activity_items": list(activity_items),
        "payload": payload,
    }


def _resolve_runtime_live_message(
    *,
    db: Session,
    snapshot: ChatRunSnapshot,
    activity_items: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    live_message: Optional[Message] = None

    assistant_message_id = str(snapshot.assistant_message_id) if snapshot.assistant_message_id else None
    if assistant_message_id:
        live_message = (
            db.query(Message)
            .filter(Message.id == assistant_message_id)
            .first()
        )

    if live_message is None and snapshot.run_id:
        live_message = (
            db.query(Message)
            .filter(
                Message.run_id == snapshot.run_id,
                Message.role == "assistant",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .first()
        )

    if live_message is None:
        return None

    return _serialize_runtime_live_message(
        message=live_message,
        activity_items=activity_items,
    )


def _serialize_pending_input_row(row: PendingUserInput) -> Optional[Dict[str, Any]]:
    stored_payload = row.request_jsonb if isinstance(row.request_jsonb, dict) else {}
    tool_name = stored_payload.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return None
    call_id = str(row.tool_call_id or "").strip()
    if not call_id:
        return None
    request_payload = canonicalize_interactive_request_payload(
        tool_name,
        stored_payload.get("request"),
    )
    result_payload = stored_payload.get("result") if isinstance(stored_payload.get("result"), dict) else {}
    if "request" not in result_payload:
        result_payload = {
            **result_payload,
            "request": request_payload,
        }
    return {
        "call_id": call_id,
        "tool_name": tool_name.strip(),
        "request": request_payload,
        "result": result_payload,
    }


def list_pending_requests(
    *,
    db: Session,
    run_id: Optional[str],
) -> List[Dict[str, Any]]:
    if not isinstance(run_id, str) or not run_id.strip():
        return []
    rows = (
        db.query(PendingUserInput)
        .filter(
            PendingUserInput.run_id == run_id,
            PendingUserInput.status == "pending",
        )
        .order_by(PendingUserInput.created_at.asc(), PendingUserInput.id.asc())
        .all()
    )
    serialized: List[Dict[str, Any]] = []
    for row in rows:
        item = _serialize_pending_input_row(row)
        if item is not None:
            serialized.append(item)
    return serialized


def ensure_conversation_state(*, db: Session, conversation_id: str) -> ConversationState:
    state = (
        db.query(ConversationState)
        .filter(ConversationState.conversation_id == conversation_id)
        .first()
    )
    if state is not None:
        return state
    state = ConversationState(conversation_id=conversation_id)
    db.add(state)
    db.flush()
    return state


def upsert_run_snapshot(
    *,
    db: Session,
    conversation_id: str,
    run_id: str,
    run_message_id: Optional[str],
    assistant_message_id: Optional[str],
    status: str,
    seq: int,
    status_label: Optional[str],
    draft_text: str,
    usage: Optional[Dict[str, Any]] = None,
) -> ChatRunSnapshot:
    snapshot = (
        db.query(ChatRunSnapshot)
        .filter(ChatRunSnapshot.conversation_id == conversation_id)
        .first()
    )
    if snapshot is None:
        snapshot = ChatRunSnapshot(conversation_id=conversation_id, run_id=run_id)
        db.add(snapshot)

    snapshot.run_id = run_id
    snapshot.run_message_id = run_message_id
    snapshot.assistant_message_id = assistant_message_id
    snapshot.status = "paused" if status == "paused" else "running"
    snapshot.seq = max(0, int(seq or 0))
    snapshot.status_label = status_label.strip() if isinstance(status_label, str) and status_label.strip() else None
    snapshot.draft_text = draft_text if isinstance(draft_text, str) else ""
    snapshot.usage_jsonb = usage if isinstance(usage, dict) else {}
    db.flush()
    return snapshot


def prepare_run_snapshot_for_resume(
    *,
    db: Session,
    conversation_id: str,
    run_id: str,
    run_message_id: Optional[str],
    assistant_message_id: str,
    status_label: Optional[str],
) -> bool:
    snapshot = (
        db.query(ChatRunSnapshot)
        .filter(
            ChatRunSnapshot.conversation_id == conversation_id,
            ChatRunSnapshot.assistant_message_id == assistant_message_id,
        )
        .first()
    )
    if snapshot is None:
        return False

    snapshot.run_id = run_id
    snapshot.run_message_id = run_message_id
    snapshot.assistant_message_id = assistant_message_id
    snapshot.status = "running"
    snapshot.seq = 0
    snapshot.status_label = status_label.strip() if isinstance(status_label, str) and status_label.strip() else None
    db.flush()
    return True


def clear_run_snapshot(*, db: Session, conversation_id: str) -> None:
    (
        db.query(ChatRunSnapshot)
        .filter(ChatRunSnapshot.conversation_id == conversation_id)
        .delete(synchronize_session=False)
    )
    db.flush()


def list_queued_turns(
    *,
    db: Session,
    conversation_id: str,
) -> List[Dict[str, Any]]:
    rows = (
        db.query(ChatRunQueuedTurn)
        .filter(
            ChatRunQueuedTurn.conversation_id == conversation_id,
            ChatRunQueuedTurn.status == "queued",
        )
        .order_by(ChatRunQueuedTurn.created_at.asc(), ChatRunQueuedTurn.id.asc())
        .all()
    )
    serialized: List[Dict[str, Any]] = []
    for position, row in enumerate(rows, start=1):
        serialized.append(
            {
                "queue_position": position,
                "run_id": str(row.run_id),
                "user_message_id": str(row.user_message_id),
                "blocked_by_run_id": str(row.blocked_by_run_id) if row.blocked_by_run_id else None,
                "created_at": row.created_at.isoformat() if row.created_at is not None else None,
            }
        )
    return serialized


def build_conversation_runtime_response(
    *,
    db: Session,
    conversation_id: str,
) -> Dict[str, Any]:
    snapshot = (
        db.query(ChatRunSnapshot)
        .filter(ChatRunSnapshot.conversation_id == conversation_id)
        .first()
    )
    queued_turns = list_queued_turns(db=db, conversation_id=conversation_id)

    if snapshot is None:
        return {
            "conversation_id": conversation_id,
            "active": False,
            "status": "queued" if queued_turns else "idle",
            "run_id": None,
            "run_message_id": None,
            "assistant_message_id": None,
            "status_label": None,
            "draft_text": "",
            "last_seq": 0,
            "resume_since_stream_event_id": 0,
            "activity_cursor": 0,
            "pending_requests": [],
            "activity_items": [],
            "queued_turns": queued_turns,
            "usage": {},
            "live_message": None,
        }

    activity_items = list_run_activity_items(db=db, run_id=str(snapshot.run_id))
    last_seq = int(snapshot.seq or 0)
    pending_requests = list_pending_requests(db=db, run_id=str(snapshot.run_id))
    live_message = _resolve_runtime_live_message(
        db=db,
        snapshot=snapshot,
        activity_items=activity_items,
    )

    return {
        "conversation_id": conversation_id,
        "active": True,
        "status": snapshot.status,
        "run_id": str(snapshot.run_id),
        "run_message_id": str(snapshot.run_message_id) if snapshot.run_message_id else None,
        "assistant_message_id": str(snapshot.assistant_message_id) if snapshot.assistant_message_id else None,
        "status_label": snapshot.status_label,
        "draft_text": snapshot.draft_text or "",
        "last_seq": last_seq,
        "resume_since_stream_event_id": last_seq,
        "activity_cursor": last_seq,
        "pending_requests": pending_requests,
        "activity_items": activity_items,
        "queued_turns": queued_turns,
        "usage": snapshot.usage_jsonb if isinstance(snapshot.usage_jsonb, dict) else {},
        "live_message": live_message,
    }
