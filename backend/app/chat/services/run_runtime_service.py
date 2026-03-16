"""Runtime helpers shared by run-oriented chat routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ...database.models import (
    ChatRun,
    ChatRunSnapshot,
    Conversation,
    ConversationState,
    Message,
    PendingUserInput,
    ToolCall,
    User,
)
from ...services.project_permissions import can_access_conversation, can_access_conversation_async
from ...utils.coerce import normalize_non_empty_string as _normalize_non_empty_string, normalize_uuid_string
from ..interactive_tools import (
    INTERACTION_TYPE_USER_INPUT,
    INTERACTIVE_TOOL_NAMES,
    canonicalize_interactive_request_payload,
)
from .run_activity_service import list_run_activity_items, sync_run_activity_items


def clamp_page_limit(limit: int, *, minimum: int = 1, maximum: int = 300) -> int:
    if limit < minimum:
        return minimum
    if limit > maximum:
        return maximum
    return limit


def _normalize_conversation_id_or_404(conversation_id: str) -> str:
    normalized_conversation_id = normalize_uuid_string(conversation_id)
    if normalized_conversation_id is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return normalized_conversation_id


def _normalize_run_id_or_404(run_id: str) -> str:
    normalized_run_id = normalize_uuid_string(run_id)
    if normalized_run_id is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return normalized_run_id


def require_accessible_conversation_sync(
    sync_db: Session,
    *,
    current_user: User,
    conversation_id: str,
) -> Conversation:
    normalized_conversation_id = _normalize_conversation_id_or_404(conversation_id)
    conversation = (
        sync_db.query(Conversation)
        .filter(Conversation.id == normalized_conversation_id)
        .first()
    )
    if conversation is None or bool(getattr(conversation, "archived", False)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not can_access_conversation(current_user, conversation, sync_db):
        raise HTTPException(status_code=403, detail="You do not have access to this conversation")
    return conversation


async def require_accessible_conversation_async(
    db: AsyncSession,
    *,
    current_user: User,
    conversation_id: str,
) -> Conversation:
    normalized_conversation_id = _normalize_conversation_id_or_404(conversation_id)
    conversation = await db.scalar(select(Conversation).where(Conversation.id == normalized_conversation_id))
    if conversation is None or bool(getattr(conversation, "archived", False)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    allowed = await can_access_conversation_async(current_user, conversation, db)
    if not allowed:
        raise HTTPException(status_code=403, detail="You do not have access to this conversation")
    return conversation


async def require_accessible_run_async(
    db: AsyncSession,
    *,
    current_user: User,
    run_id: str,
) -> tuple[ChatRun, Conversation]:
    normalized_run_id = _normalize_run_id_or_404(run_id)
    run = await db.scalar(select(ChatRun).where(ChatRun.id == normalized_run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    conversation = await require_accessible_conversation_async(
        db,
        current_user=current_user,
        conversation_id=run.conversation_id,
    )
    return run, conversation

def normalize_user_input_submission(submission: Dict[str, Any], pending_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(submission, dict):
        raise HTTPException(status_code=422, detail="User input result must be a JSON object")

    request_payload: Dict[str, Any] = {}
    if isinstance(pending_payload, dict):
        if isinstance(pending_payload.get("request"), dict):
            request_payload = canonicalize_interactive_request_payload(
                "request_user_input",
                pending_payload.get("request", {}),
            )
        else:
            request_payload = canonicalize_interactive_request_payload(
                "request_user_input",
                pending_payload,
            )

    expected_question_ids: set[str] = set()
    questions = request_payload.get("questions") if isinstance(request_payload, dict) else None
    if isinstance(questions, list):
        for item in questions:
            if isinstance(item, dict):
                qid = item.get("id")
                if isinstance(qid, str) and qid.strip():
                    expected_question_ids.add(qid.strip())

    raw_answers = submission.get("answers")
    answers: List[Dict[str, Any]] = []
    if raw_answers is not None:
        if not isinstance(raw_answers, list):
            raise HTTPException(status_code=422, detail="answers must be an array")
        for answer in raw_answers:
            if not isinstance(answer, dict):
                raise HTTPException(status_code=422, detail="Each answer must be an object")
            question_id = answer.get("question_id")
            option_label = answer.get("option_label")
            if not isinstance(question_id, str) or not question_id.strip():
                raise HTTPException(status_code=422, detail="answers[].question_id is required")
            normalized_question_id = question_id.strip()
            if expected_question_ids and normalized_question_id not in expected_question_ids:
                raise HTTPException(status_code=422, detail=f"Unknown question_id: {normalized_question_id}")
            if not isinstance(option_label, str) or not option_label.strip():
                raise HTTPException(status_code=422, detail="answers[].option_label is required")
            answers.append(
                {
                    "question_id": normalized_question_id,
                    "option_label": option_label.strip(),
                }
            )

    custom_response_raw = submission.get("custom_response")
    custom_response = custom_response_raw.strip() if isinstance(custom_response_raw, str) else ""
    if not answers and not custom_response:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one selected option or a custom response to continue.",
        )

    return {
        "status": "completed",
        "interaction_type": INTERACTION_TYPE_USER_INPUT,
        "request": request_payload if isinstance(request_payload, dict) else None,
        "answers": answers,
        "custom_response": custom_response,
    }


def normalize_interactive_submission(
    *,
    tool_name: str,
    submission: Dict[str, Any],
    pending_result: Dict[str, Any],
) -> Dict[str, Any]:
    if tool_name == "request_user_input":
        return normalize_user_input_submission(submission, pending_result)

    if not isinstance(submission, dict):
        raise HTTPException(status_code=422, detail="Tool result must be a JSON object")
    normalized = dict(submission)
    status = _normalize_non_empty_string(normalized.get("status"))
    normalized_status = (status or "completed").lower()
    if normalized_status in {"pending", "running"}:
        raise HTTPException(status_code=422, detail="Interactive tool submission cannot remain pending")
    normalized["status"] = normalized_status
    normalized.setdefault("interaction_type", INTERACTION_TYPE_USER_INPUT)
    return normalized

def _resolve_pending_payload_details(
    *,
    pending_input: PendingUserInput,
) -> Dict[str, Any]:
    stored_payload = pending_input.request_jsonb if isinstance(pending_input.request_jsonb, dict) else {}

    tool_name = _normalize_non_empty_string(stored_payload.get("tool_name"))
    request_payload = stored_payload.get("request") if isinstance(stored_payload.get("request"), dict) else None
    result_payload = stored_payload.get("result") if isinstance(stored_payload.get("result"), dict) else None

    if request_payload is None and result_payload is None:
        request_payload = stored_payload

    request_payload = canonicalize_interactive_request_payload(tool_name, request_payload)
    if not isinstance(result_payload, dict):
        result_payload = {
            "status": "pending",
            "interaction_type": INTERACTION_TYPE_USER_INPUT,
            "request": request_payload,
        }
    if "request" not in result_payload:
        result_payload["request"] = request_payload
    if "interaction_type" not in result_payload:
        result_payload["interaction_type"] = INTERACTION_TYPE_USER_INPUT

    return {
        "tool_name": tool_name,
        "request": request_payload,
        "result": result_payload,
    }


def _resolve_tool_name_for_submission(
    sync_db: Session,
    *,
    run_id: str,
    tool_call_id: str,
    payload_details: Dict[str, Any],
) -> Optional[str]:
    payload_tool_name = _normalize_non_empty_string(payload_details.get("tool_name"))
    if payload_tool_name:
        return payload_tool_name

    tool_row = (
        sync_db.query(ToolCall)
        .filter(
            ToolCall.run_id == run_id,
            ToolCall.tool_call_id == tool_call_id,
        )
        .order_by(ToolCall.started_at.desc(), ToolCall.id.desc())
        .first()
    )
    if tool_row is not None:
        row_tool_name = _normalize_non_empty_string(tool_row.tool_name)
        if row_tool_name:
            return row_tool_name

    return None


def _apply_interactive_submission_projection(
    sync_db: Session,
    *,
    conversation_id: str,
    run_id: str,
    assistant_message_id: Optional[str],
    tool_call_id: str,
    tool_name: str,
    request_payload: Optional[Dict[str, Any]],
    result_payload: Optional[Dict[str, Any]],
) -> None:
    activity_items = list_run_activity_items(
        db=sync_db,
        run_id=run_id,
    )

    normalized_status = str((result_payload or {}).get("status") or "completed").strip().lower()
    if normalized_status in {"pending", "running"}:
        item_status = "running"
    elif normalized_status in {"cancelled"}:
        item_status = "cancelled"
    elif normalized_status in {"error", "failed"}:
        item_status = "failed"
    else:
        item_status = "completed"

    updated = False
    for item in activity_items:
        if not isinstance(item, dict):
            continue
        item_key = str(item.get("item_key") or "")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        payload_call_id = str(payload.get("tool_call_id") or "")
        if tool_call_id not in {item_key, payload_call_id}:
            continue
        item["status"] = item_status
        item["title"] = tool_name
        payload["tool_call_id"] = tool_call_id
        payload["tool_name"] = tool_name
        if isinstance(request_payload, dict):
            payload["request"] = request_payload
        if isinstance(result_payload, dict):
            payload["result"] = result_payload
        item["payload"] = payload
        updated = True
        break

    if not updated:
        now_iso = datetime.now(timezone.utc).isoformat()
        activity_items.append(
            {
                "id": tool_call_id,
                "run_id": run_id,
                "item_key": tool_call_id,
                "kind": "tool",
                "status": item_status,
                "title": tool_name,
                "summary": None,
                "sequence": len(activity_items) + 1,
                "payload": {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    **({"request": request_payload} if isinstance(request_payload, dict) else {}),
                    **({"result": result_payload} if isinstance(result_payload, dict) else {}),
                },
                "created_at": now_iso,
                "updated_at": now_iso,
            }
        )

    sync_run_activity_items(
        db=sync_db,
        conversation_id=conversation_id,
        run_id=run_id,
        assistant_message_id=assistant_message_id,
        activity_items=activity_items,
    )


def mark_interactive_submission_resuming(
    sync_db: Session,
    *,
    conversation_id: str,
    run_id: str,
    assistant_message_id: Optional[str],
) -> None:
    snapshot = (
        sync_db.query(ChatRunSnapshot)
        .filter(
            ChatRunSnapshot.conversation_id == conversation_id,
            ChatRunSnapshot.run_id == run_id,
        )
        .first()
    )
    if snapshot is None:
        return
    snapshot.assistant_message_id = assistant_message_id
    snapshot.status = "running"
    snapshot.seq = 0
    snapshot.status_label = "Resuming"


def restore_interactive_submission_pending(
    sync_db: Session,
    *,
    run_id: str,
    conversation_id: str,
    tool_call_id: str,
    assistant_message_id: Optional[str],
) -> None:
    existing_run = (
        sync_db.query(ChatRun)
        .filter(
            ChatRun.id == run_id,
            ChatRun.conversation_id == conversation_id,
        )
        .first()
    )
    if existing_run is None:
        return

    pending_input = (
        sync_db.query(PendingUserInput)
        .filter(
            PendingUserInput.run_id == run_id,
            PendingUserInput.tool_call_id == tool_call_id,
        )
        .order_by(PendingUserInput.created_at.desc(), PendingUserInput.id.desc())
        .first()
    )
    if pending_input is None:
        return

    tool_call = (
        sync_db.query(ToolCall)
        .filter(
            ToolCall.run_id == run_id,
            ToolCall.tool_call_id == tool_call_id,
        )
        .order_by(ToolCall.started_at.desc(), ToolCall.id.desc())
        .first()
    )

    payload_details = _resolve_pending_payload_details(pending_input=pending_input)
    payload_tool_name = _normalize_non_empty_string(payload_details.get("tool_name"))
    tool_name = payload_tool_name or (tool_call and _normalize_non_empty_string(tool_call.tool_name))
    if not tool_name or tool_name not in INTERACTIVE_TOOL_NAMES:
        return
    request_payload = payload_details.get("request") if isinstance(payload_details.get("request"), dict) else {}
    pending_result: Dict[str, Any] = {
        "status": "pending",
        "interaction_type": INTERACTION_TYPE_USER_INPUT,
    }
    if tool_name == "request_user_input":
        pending_result["request"] = request_payload

    pending_input.request_jsonb = {
        "tool_name": tool_name,
        "request": request_payload,
        "result": pending_result,
    }
    pending_input.status = "pending"
    pending_input.resolved_at = None

    if tool_call is not None:
        tool_call.status = "running"
        tool_call.tool_name = tool_name
        tool_call.result_jsonb = {}
        tool_call.error_jsonb = {}
        tool_call.finished_at = None

    _apply_interactive_submission_projection(
        sync_db,
        conversation_id=conversation_id,
        run_id=run_id,
        assistant_message_id=assistant_message_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        request_payload=request_payload,
        result_payload=pending_result,
    )

    existing_run.status = "paused"
    existing_run.finished_at = None

    state = (
        sync_db.query(ConversationState)
        .filter(ConversationState.conversation_id == conversation_id)
        .first()
    )
    if state is not None:
        state.awaiting_user_input = True
        state.active_run_id = existing_run.id
        if assistant_message_id:
            state.last_assistant_message_id = assistant_message_id
        state.updated_at = datetime.now(timezone.utc)


def record_run_interactive_submission(
    sync_db: Session,
    *,
    run_id: str,
    conversation_id: str,
    requested_tool_call_id: Optional[str],
    submission_result: Dict[str, Any],
    expected_tool_name: Optional[str] = None,
    assistant_message_id: Optional[str] = None,
) -> Dict[str, str]:
    existing_run = (
        sync_db.query(ChatRun)
        .filter(
            ChatRun.id == run_id,
            ChatRun.conversation_id == conversation_id,
        )
        .first()
    )
    if existing_run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    normalized_requested_tool_call_id = _normalize_non_empty_string(requested_tool_call_id)
    normalized_expected_tool_name = _normalize_non_empty_string(expected_tool_name)
    pending_query = (
        sync_db.query(PendingUserInput)
        .filter(
            PendingUserInput.run_id == existing_run.id,
            PendingUserInput.status == "pending",
        )
    )
    if normalized_requested_tool_call_id:
        pending_query = pending_query.filter(PendingUserInput.tool_call_id == normalized_requested_tool_call_id)
    if assistant_message_id:
        pending_query = pending_query.filter(PendingUserInput.message_id == assistant_message_id)

    pending_input = (
        pending_query.order_by(PendingUserInput.created_at.desc(), PendingUserInput.id.desc())
        .first()
    )
    if pending_input is None:
        raise HTTPException(status_code=409, detail="No pending interactive input for this run")

    payload_details = _resolve_pending_payload_details(pending_input=pending_input)
    normalized_tool_call_id = (
        normalized_requested_tool_call_id
        or _normalize_non_empty_string(pending_input.tool_call_id)
    )
    if not normalized_tool_call_id:
        raise HTTPException(status_code=422, detail="tool_call_id is required")

    resolved_assistant_message_id = (
        _normalize_non_empty_string(assistant_message_id)
        or _normalize_non_empty_string(getattr(pending_input, "message_id", None))
    )
    if not resolved_assistant_message_id:
        raise HTTPException(status_code=409, detail="No assistant message anchor available to resume")
    tool_name = _resolve_tool_name_for_submission(
        sync_db,
        run_id=existing_run.id,
        tool_call_id=normalized_tool_call_id,
        payload_details=payload_details,
    )
    if not tool_name:
        raise HTTPException(status_code=409, detail="Unable to resolve interactive tool for submission")
    if normalized_expected_tool_name and tool_name != normalized_expected_tool_name:
        raise HTTPException(status_code=409, detail=f"Pending tool is {tool_name}, expected {normalized_expected_tool_name}")
    if tool_name not in INTERACTIVE_TOOL_NAMES:
        raise HTTPException(status_code=409, detail=f"Tool {tool_name} is not interactive")

    pending_result = payload_details.get("result") if isinstance(payload_details.get("result"), dict) else {}
    request_payload = payload_details.get("request") if isinstance(payload_details.get("request"), dict) else {}
    if tool_name == "request_user_input" and "request" not in pending_result:
        pending_result = dict(pending_result)
        pending_result["request"] = request_payload

    normalized_result = normalize_interactive_submission(
        tool_name=tool_name,
        submission=submission_result,
        pending_result=pending_result,
    )

    now = datetime.now(timezone.utc)
    pending_input.request_jsonb = {
        "tool_name": tool_name,
        "request": request_payload,
        "result": normalized_result,
    }
    pending_input.status = "resolved"
    pending_input.resolved_at = now

    tool_call = (
        sync_db.query(ToolCall)
        .filter(
            ToolCall.run_id == existing_run.id,
            ToolCall.tool_call_id == normalized_tool_call_id,
        )
        .order_by(ToolCall.started_at.desc(), ToolCall.id.desc())
        .first()
    )
    if tool_call is not None:
        normalized_result_status = _normalize_non_empty_string(normalized_result.get("status"))
        if normalized_result_status == "cancelled":
            tool_call.status = "cancelled"
        elif normalized_result_status in {"error", "failed"}:
            tool_call.status = "failed"
        else:
            tool_call.status = "completed"
        tool_call.tool_name = tool_name
        tool_call.result_jsonb = normalized_result
        tool_call.error_jsonb = {}
        tool_call.finished_at = now

    _apply_interactive_submission_projection(
        sync_db,
        conversation_id=conversation_id,
        run_id=existing_run.id,
        assistant_message_id=resolved_assistant_message_id,
        tool_call_id=normalized_tool_call_id,
        tool_name=tool_name,
        request_payload=request_payload,
        result_payload=normalized_result,
    )

    state = (
        sync_db.query(ConversationState)
        .filter(ConversationState.conversation_id == conversation_id)
        .first()
    )
    if state is not None:
        state.awaiting_user_input = False
        if resolved_assistant_message_id:
            state.last_assistant_message_id = resolved_assistant_message_id
        state.updated_at = now

    sync_db.commit()
    return {
        "run_id": existing_run.id,
        "user_message_id": existing_run.user_message_id,
        "assistant_message_id": resolved_assistant_message_id or "",
        "tool_name": tool_name,
        "tool_call_id": normalized_tool_call_id,
    }


def record_run_user_input_submission(
    sync_db: Session,
    *,
    run_id: str,
    conversation_id: str,
    requested_tool_call_id: Optional[str],
    submission_result: Dict[str, Any],
) -> Dict[str, str]:
    return record_run_interactive_submission(
        sync_db,
        run_id=run_id,
        conversation_id=conversation_id,
        requested_tool_call_id=requested_tool_call_id,
        submission_result=submission_result,
        expected_tool_name="request_user_input",
    )


def record_message_tool_call_submission(
    sync_db: Session,
    *,
    conversation_id: str,
    message_id: str,
    tool_call_id: str,
    submission_result: Dict[str, Any],
) -> Dict[str, Any]:
    assistant_message = (
        sync_db.query(Message)
        .filter(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.role == "assistant",
        )
        .first()
    )
    if assistant_message is None:
        raise HTTPException(status_code=404, detail="Assistant message not found")

    normalized_tool_call_id = _normalize_non_empty_string(tool_call_id)
    if not normalized_tool_call_id:
        raise HTTPException(status_code=400, detail="tool_call_id is required")

    run_id = _normalize_non_empty_string(assistant_message.run_id)
    has_pending_interactive = False
    if run_id:
        pending_input = (
            sync_db.query(PendingUserInput)
            .filter(
                PendingUserInput.run_id == run_id,
                PendingUserInput.status == "pending",
                PendingUserInput.tool_call_id == normalized_tool_call_id,
            )
            .order_by(PendingUserInput.created_at.desc(), PendingUserInput.id.desc())
            .first()
        )
        has_pending_interactive = pending_input is not None

    if has_pending_interactive and run_id:
        resumed = record_run_interactive_submission(
            sync_db,
            run_id=run_id,
            conversation_id=conversation_id,
            requested_tool_call_id=normalized_tool_call_id,
            submission_result=submission_result,
            assistant_message_id=assistant_message.id,
        )
        resumed["resumed"] = True
        return resumed

    updated = False
    tool_name: Optional[str] = None
    now = datetime.now(timezone.utc)

    tool_row = (
        sync_db.query(ToolCall)
        .filter(
            ToolCall.message_id == assistant_message.id,
            ToolCall.tool_call_id == normalized_tool_call_id,
        )
        .first()
    )
    if tool_row is not None:
        tool_row.status = "completed"
        tool_row.result_jsonb = submission_result
        tool_row.error_jsonb = {}
        tool_row.finished_at = now
        if isinstance(tool_row.tool_name, str) and tool_row.tool_name.strip() and not tool_name:
            tool_name = tool_row.tool_name.strip()
        updated = True

    if not updated:
        raise HTTPException(status_code=404, detail="Tool call not found in assistant message")

    if run_id:
        _apply_interactive_submission_projection(
            sync_db,
            conversation_id=conversation_id,
            run_id=run_id,
            assistant_message_id=assistant_message.id,
            tool_call_id=normalized_tool_call_id,
            tool_name=tool_name or "unknown",
            request_payload=None,
            result_payload=submission_result,
        )
    sync_db.commit()
    return {
        "run_id": run_id,
        "user_message_id": None,
        "assistant_message_id": assistant_message.id,
        "tool_name": tool_name or "unknown",
        "resumed": False,
    }
