"""Helpers for message paging and timeline projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ...database.models import Message, MessagePart
from .run_activity_service import list_run_activity_items_for_runs
from ...utils.datetime_helpers import format_utc_z

_TRANSIENT_ASSISTANT_STATUSES = {
    "streaming",
    "pending",
    "paused",
    "awaiting_input",
    "running",
}


@dataclass
class _TimelineRow:
    message: Message
    parts: List[MessagePart]
    activity_items: List[Dict[str, Any]]

    @property
    def seq(self) -> int:
        created = getattr(self.message, "created_at", None)
        if isinstance(created, datetime):
            dt = created
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            micros = int(dt.timestamp() * 1_000_000)
        else:
            micros = 0
        return micros


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    return format_utc_z(value) or ""


def _decode_cursor(cursor: Optional[str]) -> tuple[Optional[datetime], Optional[str]]:
    if not isinstance(cursor, str):
        return None, None
    raw = cursor.strip()
    if not raw or "|" not in raw:
        return None, None
    ts_raw, msg_id = raw.split("|", 1)
    ts_raw = ts_raw.strip()
    msg_id = msg_id.strip()
    if not ts_raw or not msg_id:
        return None, None
    try:
        parsed = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, msg_id


def _encode_cursor(row: _TimelineRow) -> Optional[str]:
    created_at = getattr(row.message, "created_at", None)
    if not isinstance(created_at, datetime):
        return None
    dt = created_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{dt.isoformat().replace('+00:00', 'Z')}|{row.message.id}"


def _parts_for_messages(db: Session, message_ids: List[str]) -> Dict[str, List[MessagePart]]:
    if not message_ids:
        return {}
    rows = (
        db.query(MessagePart)
        .filter(MessagePart.message_id.in_(message_ids))
        .order_by(MessagePart.message_id.asc(), MessagePart.ordinal.asc(), MessagePart.id.asc())
        .all()
    )
    grouped: Dict[str, List[MessagePart]] = {}
    for row in rows:
        grouped.setdefault(str(row.message_id), []).append(row)
    return grouped


def _activities_for_runs(db: Session, run_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    return list_run_activity_items_for_runs(db=db, run_ids=run_ids)


def _is_transcript_message(message: Message) -> bool:
    role = str(getattr(message, "role", "") or "").strip().lower()
    status = str(getattr(message, "status", "") or "").strip().lower()
    if role == "user":
        return status != "cancelled"
    if role != "assistant":
        return True
    return status not in _TRANSIENT_ASSISTANT_STATUSES


def fetch_events_page(
    db: Session,
    *,
    conversation_id: str,
    limit: int,
    before_cursor: Optional[str],
) -> Tuple[List[_TimelineRow], bool, Optional[str]]:
    limit = max(1, min(int(limit or 1), 300))
    before_ts, before_id = _decode_cursor(before_cursor)

    q = db.query(Message).filter(Message.conversation_id == conversation_id)
    q = q.filter(
        or_(
            Message.role != "assistant",
            Message.status.is_(None),
            ~Message.status.in_(tuple(_TRANSIENT_ASSISTANT_STATUSES)),
        )
    )
    if before_ts is not None and before_id:
        q = q.filter(
            or_(
                Message.created_at < before_ts,
                and_(Message.created_at == before_ts, Message.id < before_id),
            )
        )

    raw_rows = (
        q.order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit + 1)
        .all()
    )
    has_more = len(raw_rows) > limit
    window = raw_rows[:limit]
    ordered_messages = list(reversed(window))

    parts_by_message = _parts_for_messages(db, [str(row.id) for row in ordered_messages])
    activities_by_run = _activities_for_runs(
        db,
        [
            str(row.run_id)
            for row in ordered_messages
            if isinstance(getattr(row, "run_id", None), str) and str(row.run_id).strip()
        ],
    )
    ordered_rows = [
        _TimelineRow(
            message=row,
            parts=parts_by_message.get(str(row.id), []),
            activity_items=activities_by_run.get(str(row.run_id), []) if row.role == "assistant" and row.run_id else [],
        )
        for row in ordered_messages
    ]

    next_cursor = _encode_cursor(ordered_rows[0]) if has_more and ordered_rows else None
    return ordered_rows, has_more, next_cursor


def _message_payload(row: _TimelineRow) -> Dict[str, Any]:
    message = row.message
    payload: Dict[str, Any] = {
        "text": message.text if isinstance(message.text, str) else "",
        "status": message.status,
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

    # Attach user-message metadata from metadata parts.
    if message.role == "user":
        for part in row.parts:
            if str(part.part_type or "").strip().lower() != "metadata":
                continue
            source = part.payload_jsonb if isinstance(part.payload_jsonb, dict) else {}
            attachments = source.get("attachments")
            if isinstance(attachments, list):
                payload["attachments"] = attachments
            if isinstance(source.get("request_id"), str):
                payload["request_id"] = source["request_id"]
    return payload


def _event_type_for_message(message: Message) -> str:
    role = str(message.role or "").strip().lower()
    status = str(message.status or "").strip().lower()
    if role == "user":
        return "user_message"
    if role == "assistant":
        if status in {"streaming", "pending", "paused", "awaiting_input", "running"}:
            return "assistant_message_partial"
        return "assistant_message_final"
    return "system_message"


def project_timeline_item(row: _TimelineRow) -> Optional[Dict[str, Any]]:
    message = row.message
    if not _is_transcript_message(message):
        return None
    payload = _message_payload(row)
    role_raw = str(message.role or "").strip().lower()
    role: Optional[str] = role_raw if role_raw in {"user", "assistant"} else None

    return {
        "id": message.id,
        "seq": row.seq,
        "run_id": message.run_id,
        "type": _event_type_for_message(message),
        "actor": role or "system",
        "created_at": _iso(message.created_at),
        "role": role,
        "text": payload.get("text") if isinstance(payload.get("text"), str) else None,
        "activity_items": list(row.activity_items or []),
        "payload": payload,
    }


def serialize_event(row: _TimelineRow) -> Dict[str, Any]:
    message = row.message
    payload = _message_payload(row)
    event_type = _event_type_for_message(message)
    phase = "worklog" if event_type == "assistant_message_partial" else "final"
    return {
        "id": message.id,
        "seq": row.seq,
        "conversation_id": message.conversation_id,
        "run_id": message.run_id,
        "event_type": event_type,
        "actor": str(message.role or "system"),
        "phase": phase,
        "payload": payload,
        "created_at": _iso(message.created_at),
    }
