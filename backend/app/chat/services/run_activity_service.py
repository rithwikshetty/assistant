"""Durable run-activity projection helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from ...database.models import ChatRunActivity
from ..interactive_tools import canonicalize_interactive_request_payload
from ..streaming_support import StreamState


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_run_activity_items_from_stream_state(
    *,
    run_id: str,
    state: StreamState,
) -> List[Dict[str, Any]]:
    activity_items: List[Dict[str, Any]] = []
    created_at = _now_iso()

    for index, marker in enumerate(state.tool_markers):
        if not isinstance(marker, dict):
            continue
        call_id = str(marker.get("call_id") or f"tool_{index + 1}").strip()
        if not call_id:
            continue
        if isinstance(marker.get("error"), dict):
            status = "failed"
        elif "result" in marker:
            status = "completed"
        else:
            status = "running"
        sequence = int(marker.get("seq") or (index + 1))
        payload: Dict[str, Any] = {
            "tool_call_id": call_id,
            "tool_name": marker.get("name"),
            "position": int(marker.get("pos") or 0),
        }
        if isinstance(marker.get("arguments"), dict):
            payload["arguments"] = marker["arguments"]
        if isinstance(marker.get("query"), str) and marker["query"].strip():
            payload["query"] = marker["query"].strip()
        if isinstance(marker.get("result"), dict):
            payload["result"] = marker["result"]
            if isinstance(marker["result"].get("request"), dict):
                payload["request"] = canonicalize_interactive_request_payload(
                    marker.get("name"),
                    marker["result"]["request"],
                )
        if isinstance(marker.get("error"), dict):
            payload["error"] = marker["error"]
        activity_items.append(
            {
                "id": call_id,
                "run_id": run_id,
                "item_key": call_id,
                "kind": "tool",
                "status": status,
                "title": marker.get("name"),
                "summary": payload.get("query"),
                "sequence": sequence,
                "payload": payload,
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

    for index, marker in enumerate(state.reasoning_summaries):
        if not isinstance(marker, dict):
            continue
        marker_id = str(marker.get("id") or f"reasoning_{index + 1}").strip()
        if not marker_id:
            continue
        activity_items.append(
            {
                "id": marker_id,
                "run_id": run_id,
                "item_key": marker_id,
                "kind": "reasoning",
                "status": "completed",
                "title": marker.get("title") or "Thinking",
                "summary": None,
                "sequence": int(marker.get("sequence") or (len(activity_items) + 1)),
                "payload": {
                    "id": marker_id,
                    "raw_text": marker.get("raw_text") if isinstance(marker.get("raw_text"), str) else "",
                    "position": int(marker.get("position") or 0),
                },
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

    for index, marker in enumerate(state.compaction_markers):
        if not isinstance(marker, dict):
            continue
        marker_id = str(marker.get("item_id") or f"compaction_{index + 1}").strip()
        if not marker_id:
            continue
        activity_items.append(
            {
                "id": marker_id,
                "run_id": run_id,
                "item_key": marker_id,
                "kind": "compaction",
                "status": "completed",
                "title": marker.get("label") or "Automatically compacting context",
                "summary": None,
                "sequence": int(marker.get("seq") or (len(activity_items) + 1)),
                "payload": {
                    "item_id": marker.get("item_id"),
                    "label": marker.get("label"),
                    "source": marker.get("source"),
                    "position": int(marker.get("pos") or 0),
                },
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

    activity_items.sort(key=lambda item: (int(item.get("sequence") or 0), str(item.get("item_key") or "")))
    return activity_items


def serialize_run_activity(row: ChatRunActivity) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "item_key": str(row.item_key),
        "kind": str(row.kind),
        "status": str(row.status),
        "title": row.title,
        "summary": row.summary,
        "sequence": int(row.sequence or 0),
        "payload": dict(row.payload_jsonb or {}),
        "created_at": row.created_at.isoformat() if row.created_at is not None else _now_iso(),
        "updated_at": row.updated_at.isoformat() if row.updated_at is not None else _now_iso(),
    }


def list_run_activity_items(
    *,
    db: Session,
    run_id: str,
) -> List[Dict[str, Any]]:
    rows = (
        db.query(ChatRunActivity)
        .filter(ChatRunActivity.run_id == run_id)
        .order_by(
            ChatRunActivity.sequence.asc(),
            ChatRunActivity.created_at.asc(),
            ChatRunActivity.id.asc(),
        )
        .all()
    )
    return [serialize_run_activity(row) for row in rows]


def list_run_activity_items_for_runs(
    *,
    db: Session,
    run_ids: Iterable[str],
) -> Dict[str, List[Dict[str, Any]]]:
    normalized_run_ids = [str(run_id).strip() for run_id in run_ids if isinstance(run_id, str) and run_id.strip()]
    if not normalized_run_ids:
        return {}

    rows = (
        db.query(ChatRunActivity)
        .filter(ChatRunActivity.run_id.in_(normalized_run_ids))
        .order_by(
            ChatRunActivity.run_id.asc(),
            ChatRunActivity.sequence.asc(),
            ChatRunActivity.created_at.asc(),
            ChatRunActivity.id.asc(),
        )
        .all()
    )

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.run_id), []).append(serialize_run_activity(row))
    return grouped


def sync_run_activity_items(
    *,
    db: Session,
    conversation_id: str,
    run_id: str,
    assistant_message_id: Optional[str],
    activity_items: Optional[Iterable[Dict[str, Any]]],
) -> None:
    incoming_items = [
        item
        for item in (activity_items or [])
        if isinstance(item, dict) and str(item.get("item_key") or "").strip()
    ]
    incoming_items.sort(key=lambda item: (int(item.get("sequence") or 0), str(item.get("item_key") or "")))

    existing_rows = (
        db.query(ChatRunActivity)
        .filter(ChatRunActivity.run_id == run_id)
        .all()
    )
    existing_by_key = {
        str(row.item_key): row
        for row in existing_rows
        if isinstance(getattr(row, "item_key", None), str) and str(row.item_key).strip()
    }
    seen_keys: set[str] = set()

    for fallback_sequence, item in enumerate(incoming_items, start=1):
        item_key = str(item.get("item_key") or "").strip()
        if not item_key or item_key in seen_keys:
            continue
        seen_keys.add(item_key)
        row = existing_by_key.pop(item_key, None)
        if row is None:
            row = ChatRunActivity(
                conversation_id=conversation_id,
                run_id=run_id,
                item_key=item_key,
            )
            db.add(row)

        row.conversation_id = conversation_id
        row.run_id = run_id
        row.message_id = assistant_message_id if assistant_message_id is not None else row.message_id
        row.kind = str(item.get("kind") or "tool")
        row.status = str(item.get("status") or "running")
        row.title = item.get("title") if isinstance(item.get("title"), str) else None
        row.summary = item.get("summary") if isinstance(item.get("summary"), str) else None
        row.sequence = max(0, int(item.get("sequence") or fallback_sequence))
        row.payload_jsonb = item.get("payload") if isinstance(item.get("payload"), dict) else {}

    for stale_row in existing_by_key.values():
        db.delete(stale_row)

    db.flush()
