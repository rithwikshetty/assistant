"""Persistence primitives for assistant turn finalization."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from ...database.models import (
    ChatRun,
    ConversationState,
    Message,
    PendingUserInput,
    ToolCall,
)
from ...logging import log_event
from ..interactive_tools import (
    INTERACTION_TYPE_USER_INPUT,
    canonicalize_interactive_request_payload,
    is_interactive_tool_name,
    is_pending_interactive_result,
)
from .payload_cleaner import strip_nul_bytes

logger = logging.getLogger(__name__)


class AssistantTurnPersistenceService:
    """Owns DB writes for assistant messages, tool calls, pending inputs, and outbox rows."""

    @staticmethod
    def ensure_state_row(*, db: Session, conversation_id: str) -> ConversationState:
        from .run_snapshot_service import ensure_conversation_state

        return ensure_conversation_state(db=db, conversation_id=conversation_id)

    def upsert_assistant_message(
        self,
        *,
        db: Session,
        conversation_id: str,
        run_id: Optional[str],
        assistant_message_id: str,
        update_existing: bool,
        payload: Dict[str, Any],
        status: str,
        completed: bool,
        created_at: Optional[datetime] = None,
    ) -> Message:
        existing = None
        if update_existing and assistant_message_id:
            existing = (
                db.query(Message)
                .filter(
                    Message.id == assistant_message_id,
                    Message.conversation_id == conversation_id,
                    Message.role == "assistant",
                )
                .first()
            )
        if existing is None:
            existing = Message(
                id=assistant_message_id,
                conversation_id=conversation_id,
                run_id=run_id,
                role="assistant",
            )
            if isinstance(created_at, datetime):
                existing.created_at = created_at
            db.add(existing)

        existing.run_id = run_id
        existing.status = status
        existing.text = str(payload.get("text") or "")
        existing.model_provider = payload.get("model_provider") if isinstance(payload.get("model_provider"), str) else None
        existing.model_name = payload.get("model_name") if isinstance(payload.get("model_name"), str) else None
        raw_finish_reason = payload.get("finish_reason")
        existing.finish_reason = raw_finish_reason if isinstance(raw_finish_reason, str) else None
        raw_latency = payload.get("response_latency_ms")
        if isinstance(raw_latency, (int, float)):
            existing.response_latency_ms = int(raw_latency)
        elif isinstance(raw_latency, str) and raw_latency.strip().isdigit():
            existing.response_latency_ms = int(raw_latency.strip())
        raw_cost = payload.get("cost_usd")
        if raw_cost is not None:
            try:
                existing.cost_usd = Decimal(str(raw_cost))
            except Exception:
                existing.cost_usd = None
        if completed:
            existing.completed_at = datetime.now(timezone.utc)
        db.flush()
        return existing

    @staticmethod
    def persist_tool_calls(
        *,
        db: Session,
        message: Message,
        run_id: Optional[str],
        tool_markers: List[Dict[str, Any]],
    ) -> None:
        db.query(ToolCall).filter(ToolCall.message_id == message.id).delete(synchronize_session=False)
        now = datetime.now(timezone.utc)
        deduped_markers: List[Dict[str, Any]] = []
        deduped_index_by_call_id: Dict[str, int] = {}
        duplicate_count = 0

        for marker in tool_markers or []:
            if not isinstance(marker, dict):
                continue
            call_id = str(marker.get("call_id") or "").strip() or f"call_{uuid4().hex[:12]}"
            if call_id in deduped_index_by_call_id:
                duplicate_count += 1
                existing = deduped_markers[deduped_index_by_call_id[call_id]]
                incoming_name = str(marker.get("name") or "").strip()
                if incoming_name:
                    existing["name"] = incoming_name
                for key in ("arguments", "query", "result", "error"):
                    if key in marker and marker.get(key) is not None:
                        existing[key] = marker.get(key)
                continue

            merged = dict(marker)
            merged["call_id"] = call_id
            deduped_index_by_call_id[call_id] = len(deduped_markers)
            deduped_markers.append(merged)

        if duplicate_count:
            log_event(
                logger,
                "WARNING",
                "chat.stream.tool_calls.deduped",
                "retry",
                message_id=message.id,
                run_id=run_id,
                duplicate_count=duplicate_count,
            )

        for marker in deduped_markers:
            tool_name = str(marker.get("name") or "").strip() or "unknown"
            call_id = str(marker.get("call_id") or "").strip() or f"call_{uuid4().hex[:12]}"
            arguments = marker.get("arguments") if isinstance(marker.get("arguments"), dict) else {}
            result_payload = marker.get("result")
            error_payload = marker.get("error")
            status = "completed"
            if error_payload is not None:
                status = "failed"
            elif isinstance(result_payload, dict):
                normalized_result_status = str(result_payload.get("status") or "").strip().lower()
                if normalized_result_status in {"pending", "running"}:
                    status = "running"
                elif normalized_result_status in {"cancelled"}:
                    status = "cancelled"
            db.add(
                ToolCall(
                    message_id=message.id,
                    run_id=run_id,
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    arguments_jsonb=strip_nul_bytes(arguments),
                    query_text=marker.get("query") if isinstance(marker.get("query"), str) else None,
                    status=status,
                    result_jsonb=strip_nul_bytes(result_payload if isinstance(result_payload, dict) else {}),
                    error_jsonb=strip_nul_bytes(error_payload if isinstance(error_payload, dict) else {}),
                    started_at=now,
                    finished_at=now,
                )
            )
        db.flush()

    @staticmethod
    def persist_pending_user_inputs(
        *,
        db: Session,
        message: Message,
        run_id: Optional[str],
        tool_markers: List[Dict[str, Any]],
        run_status: str,
    ) -> None:
        if run_id is None:
            return
        if run_status in {"completed", "failed", "cancelled"}:
            (
                db.query(PendingUserInput)
                .filter(
                    PendingUserInput.run_id == run_id,
                    PendingUserInput.status == "pending",
                )
                .update(
                    {
                        "status": "cancelled",
                        "resolved_at": datetime.now(timezone.utc),
                    },
                    synchronize_session=False,
                )
            )

        for marker in tool_markers or []:
            if not isinstance(marker, dict):
                continue
            tool_name = str(marker.get("name") or "").strip()
            if not is_interactive_tool_name(tool_name):
                continue
            result_payload = marker.get("result")
            if not isinstance(result_payload, dict):
                continue
            result_status = str(result_payload.get("status") or "").strip().lower()
            call_id = str(marker.get("call_id") or "").strip()
            row = (
                db.query(PendingUserInput)
                .filter(
                    PendingUserInput.run_id == run_id,
                    PendingUserInput.tool_call_id == call_id,
                )
                .first()
            )
            if is_pending_interactive_result(result_payload, tool_name=tool_name):
                if row is None:
                    row = PendingUserInput(
                        run_id=run_id,
                        message_id=message.id,
                        tool_call_id=call_id or None,
                    )
                    db.add(row)
                request_payload = (
                    canonicalize_interactive_request_payload(
                        tool_name,
                        result_payload.get("request"),
                    )
                )
                result_to_store = dict(result_payload)
                if "request" not in result_to_store:
                    result_to_store["request"] = request_payload
                if "interaction_type" not in result_to_store:
                    result_to_store["interaction_type"] = INTERACTION_TYPE_USER_INPUT
                row.message_id = message.id
                row.request_jsonb = strip_nul_bytes(
                    {
                        "tool_name": tool_name,
                        "request": request_payload,
                        "result": result_to_store,
                    }
                )
                row.status = "pending"
                row.resolved_at = None
            elif result_status in {"completed", "cancelled", "failed", "error"} and row is not None and row.status == "pending":
                row.status = "resolved"
                row.resolved_at = datetime.now(timezone.utc)
        db.flush()

    @staticmethod
    def enqueue_outbox_event(
        *,
        db: Session,
        message: Message,
        run: Optional[ChatRun],
        usage_payload: Dict[str, Any],
        conversation_usage_payload: Dict[str, Any],
    ) -> None:
        return None
