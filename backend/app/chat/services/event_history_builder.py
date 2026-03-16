"""Build provider input history from canonical conversation messages."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from ...database.models import Message, MessagePart


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_attachment_ids(raw_attachments: Any) -> List[str]:
    if not isinstance(raw_attachments, list):
        return []
    result: List[str] = []
    for item in raw_attachments:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
            continue
        if isinstance(item, dict):
            candidate = item.get("id")
            if isinstance(candidate, str) and candidate.strip():
                result.append(candidate.strip())
    return result


def _message_to_history_message(message: Message, parts: List[MessagePart]) -> Optional[Dict[str, Any]]:
    role = str(getattr(message, "role", "") or "").strip().lower()
    text = message.text if isinstance(message.text, str) else ""

    if role == "user":
        if not isinstance(text, str):
            return None
        attachments: Optional[List[Any]] = None
        for part in parts:
            if str(getattr(part, "part_type", "") or "").strip().lower() != "metadata":
                continue
            payload = _as_dict(getattr(part, "payload_jsonb", {}))
            candidate_attachments = payload.get("attachments")
            if isinstance(candidate_attachments, list):
                attachments = candidate_attachments
                break
        metadata: Dict[str, Any] = {}
        if attachments:
            metadata["attachments"] = attachments
        return {
            "role": "user",
            "content": text,
            "metadata": metadata,
        }

    if role == "assistant":
        return {
            "role": "assistant",
            "content": text,
            "metadata": {
                "status": message.status,
            },
        }

    return None


def _run_id_of(item: Any) -> Optional[str]:
    run_id = getattr(item, "run_id", None)
    if isinstance(run_id, str) and run_id:
        return run_id
    return None


def _is_assistant_partial(item: Any) -> bool:
    event_type = str(getattr(item, "event_type", "") or "").strip().lower()
    if event_type:
        return event_type == "assistant_message_partial"
    if str(getattr(item, "role", "") or "").strip().lower() != "assistant":
        return False
    status = str(getattr(item, "status", "") or "").strip().lower()
    return status in {"streaming", "pending", "paused", "awaiting_input", "running"}


def _is_assistant_final(item: Any) -> bool:
    event_type = str(getattr(item, "event_type", "") or "").strip().lower()
    if event_type:
        return event_type == "assistant_message_final"
    if str(getattr(item, "role", "") or "").strip().lower() != "assistant":
        return False
    status = str(getattr(item, "status", "") or "").strip().lower()
    return status in {"completed", "failed", "cancelled"}


def _suppress_superseded_assistant_partials(messages: List[Any]) -> List[Any]:
    """Drop stale assistant partial snapshots.

    Keep assistant partial messages only when they are the latest partial for a run
    and that run does not already have a later assistant final message.
    """

    final_index_by_run: Dict[str, int] = {}
    latest_partial_index_by_run: Dict[str, int] = {}

    for index, message in enumerate(messages):
        run_id = _run_id_of(message)
        if run_id is None:
            continue

        if _is_assistant_final(message):
            previous = final_index_by_run.get(run_id)
            if previous is None or index > previous:
                final_index_by_run[run_id] = index
        elif _is_assistant_partial(message):
            previous = latest_partial_index_by_run.get(run_id)
            if previous is None or index > previous:
                latest_partial_index_by_run[run_id] = index

    filtered: List[Any] = []
    for index, message in enumerate(messages):
        if not _is_assistant_partial(message):
            filtered.append(message)
            continue

        run_id = _run_id_of(message)
        if run_id is None:
            filtered.append(message)
            continue

        latest_final_index = final_index_by_run.get(run_id)
        latest_partial_index = latest_partial_index_by_run.get(run_id)
        if latest_final_index is not None and latest_final_index > index:
            continue
        if latest_partial_index is not None and latest_partial_index > index:
            continue
        filtered.append(message)

    return filtered


def build_conversation_history_from_messages(
    sync_db: Session,
    *,
    conversation_id: str,
    allowed_file_ids: Set[str],
    anchor_user_message_id: Optional[str] = None,
    max_messages: int = 240,
) -> List[Dict[str, Any]]:
    """Build compact raw history list for provider input from messages."""

    rows: List[Message] = (
        sync_db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(max_messages)
        .all()
    )
    messages = list(reversed(rows))
    messages = _suppress_superseded_assistant_partials(messages)
    parts_rows: List[MessagePart] = []
    if messages:
        parts_rows = (
            sync_db.query(MessagePart)
            .filter(MessagePart.message_id.in_([message.id for message in messages]))
            .filter(MessagePart.part_type == "metadata")
            .order_by(MessagePart.message_id.asc(), MessagePart.ordinal.asc(), MessagePart.id.asc())
            .all()
        )

    parts_by_message: Dict[str, List[MessagePart]] = {}
    for row in parts_rows:
        parts_by_message.setdefault(str(row.message_id), []).append(row)

    history: List[Dict[str, Any]] = []

    for message in messages:
        if (
            anchor_user_message_id
            and str(getattr(message, "role", "") or "").strip().lower() == "user"
            and message.id == anchor_user_message_id
        ):
            break

        history_item = _message_to_history_message(
            message,
            parts_by_message.get(str(message.id), []),
        )
        if history_item is None:
            continue

        if history_item.get("role") == "user":
            attachments = _as_dict(history_item.get("metadata")).get("attachments")
            for attachment_id in _extract_attachment_ids(attachments):
                allowed_file_ids.add(attachment_id)

        history.append(history_item)

    return history
