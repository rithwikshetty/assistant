"""Chat runtime routes (runs, transcript timeline, runtime snapshot, and tool/result updates)."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ...auth.dependencies import get_current_user
from ...database import get_async_db
from ...database.models import (
    ChatRun,
    ChatRunQueuedTurn,
    ConversationState,
    Message,
    Project,
    User,
)
from ...logging import bind_log_context, log_event
from ...services.chat_streams import (
    get_stream_meta,
)

from ..schemas import (
    CancelRunResponse,
    ConversationRuntimeResponse,
    CreateRunRequest,
    CreateRunResponse,
    MessageSuggestionsResponse,
    MessageCreate,
    SubmitRunUserInputRequest,
    SubmitRunUserInputResponse,
    TimelineItemResponse,
    TimelinePageResponse,
)
from ..services.run_snapshot_service import build_conversation_runtime_response
from ..services.cancel_stream_service import cancel_conversation_stream
from ..services.run_runtime_service import (
    clamp_page_limit,
    mark_interactive_submission_resuming,
    record_message_tool_call_submission,
    record_run_user_input_submission,
    restore_interactive_submission_pending,
    require_accessible_conversation_async,
    require_accessible_conversation_sync,
    require_accessible_run_async,
)
from ..services.timeline_service import fetch_events_page, project_timeline_item
from ..services.run_queue_service import enqueue_run_command
from ..services.submit_runtime_service import submit_existing_conversation
from ..services.suggestion_service import generate_suggestions

import logging

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_non_empty_string(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    text = str(raw).strip()
    return text or None


async def _has_exact_running_stream(
    *,
    conversation_id: str,
    run_id: str,
    user_message_id: str,
) -> bool:
    meta = await get_stream_meta(conversation_id)
    if not isinstance(meta, dict):
        return False
    status = _normalize_non_empty_string(meta.get("status"))
    if status != "running":
        return False
    active_run_id = _normalize_non_empty_string(meta.get("run_id"))
    active_user_message_id = _normalize_non_empty_string(meta.get("user_message_id"))
    return (
        active_run_id == _normalize_non_empty_string(run_id)
        and active_user_message_id == _normalize_non_empty_string(user_message_id)
    )


async def _mark_interactive_submission_resuming_best_effort(
    *,
    db: AsyncSession,
    conversation_id: str,
    run_id: str,
    assistant_message_id: Optional[str],
) -> None:
    normalized_assistant_message_id = _normalize_non_empty_string(assistant_message_id)
    if not normalized_assistant_message_id:
        return
    try:
        await db.run_sync(
            lambda sync_db: mark_interactive_submission_resuming(
                sync_db,
                conversation_id=conversation_id,
                run_id=run_id,
                assistant_message_id=normalized_assistant_message_id,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        log_event(
            logger,
            "WARNING",
            "chat.runtime.resume_projection_mark_failed",
            "retry",
            conversation_id=conversation_id,
            run_id=run_id,
            assistant_message_id=normalized_assistant_message_id,
            exc_info=True,
        )


async def _resume_interactive_run_or_revert(
    *,
    db: AsyncSession,
    conversation_id: str,
    current_user_id: str,
    recorded: Dict[str, str],
) -> None:
    run_id = _normalize_non_empty_string(recorded.get("run_id"))
    user_message_id = _normalize_non_empty_string(recorded.get("user_message_id"))
    assistant_message_id = _normalize_non_empty_string(recorded.get("assistant_message_id"))
    tool_call_id = _normalize_non_empty_string(recorded.get("tool_call_id"))
    if not run_id or not user_message_id:
        raise HTTPException(status_code=500, detail="Missing run context for resume")

    needs_enqueue = not await _has_exact_running_stream(
        conversation_id=conversation_id,
        run_id=run_id,
        user_message_id=user_message_id,
    )

    if needs_enqueue:
        try:
            await enqueue_run_command(
                conversation_id=conversation_id,
                run_id=run_id,
                user_id=current_user_id,
                user_message_id=user_message_id,
                resume_assistant_message_id=assistant_message_id,
            )
        except Exception as exc:
            if tool_call_id:
                try:
                    await db.run_sync(
                        lambda sync_db: restore_interactive_submission_pending(
                            sync_db,
                            run_id=run_id,
                            conversation_id=conversation_id,
                            tool_call_id=tool_call_id,
                            assistant_message_id=assistant_message_id,
                        )
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    log_event(
                        logger,
                        "ERROR",
                        "chat.runtime.resume_revert_failed",
                        "error",
                        conversation_id=conversation_id,
                        run_id=run_id,
                        assistant_message_id=assistant_message_id,
                        tool_call_id=tool_call_id,
                        exc_info=True,
                    )
            log_event(
                logger,
                "WARNING",
                "chat.runtime.resume_enqueue_failed",
                "retry",
                conversation_id=conversation_id,
                run_id=run_id,
                assistant_message_id=assistant_message_id,
                tool_call_id=tool_call_id,
                user_id=current_user_id,
                error_type=type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="Failed to resume run. Please try again.",
            ) from exc

    await _mark_interactive_submission_resuming_best_effort(
        db=db,
        conversation_id=conversation_id,
        run_id=run_id,
        assistant_message_id=assistant_message_id,
    )


@router.post("/{conversation_id}/runs", response_model=CreateRunResponse)
async def create_run(
    conversation_id: str,
    payload: CreateRunRequest,
    raw_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    submit_started = perf_counter()
    submit_trace_id = (
        payload.request_id.strip()
        if isinstance(payload.request_id, str) and payload.request_id.strip()
        else f"run_{uuid4().hex[:12]}"
    )

    bind_log_context(
        trace_id=submit_trace_id,
        user_id=str(getattr(current_user, "id", "")),
        conversation_id=conversation_id,
    )
    log_event(
        logger,
        "INFO",
        "chat.submit.received",
        "timing",
        conversation_id=conversation_id,
    )

    result = await submit_existing_conversation(
        conversation_id,
        MessageCreate(
            content=text,
            request_id=payload.request_id,
            attachments=payload.attachment_ids,
        ),
        current_user=current_user,
        db=db,
        submit_started=submit_started,
        submit_trace_id=submit_trace_id,
        user_timezone=raw_request.headers.get("X-User-Timezone"),
        user_locale=raw_request.headers.get("X-User-Locale"),
    )

    user_message_id = result.get("user_message_id")
    if not isinstance(user_message_id, str) or not user_message_id:
        raise HTTPException(status_code=500, detail="Run did not produce a user message id")

    response_status = str(result.get("status") or "running")

    run_id = result.get("run_id")

    if not isinstance(run_id, str) or not run_id.strip():
        raise HTTPException(status_code=500, detail="Run did not produce a run id")
    if not isinstance(user_message_id, str) or not user_message_id.strip():
        raise HTTPException(status_code=500, detail="Run did not produce a user message id")

    return CreateRunResponse(
        run_id=run_id,
        user_message_id=user_message_id,
        status=response_status,
        queue_position=max(0, int(result.get("queue_position") or 0)),
    )

@router.get("/{conversation_id}/timeline", response_model=TimelinePageResponse)
async def get_conversation_timeline(
    conversation_id: str,
    limit: int = 100,
    cursor: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    limit = clamp_page_limit(limit)

    def _db_work(sync_db: Session) -> TimelinePageResponse:
        require_accessible_conversation_sync(
            sync_db,
            current_user=current_user,
            conversation_id=conversation_id,
        )

        rows, has_more, next_cursor = fetch_events_page(
            sync_db,
            conversation_id=conversation_id,
            limit=limit,
            before_cursor=cursor,
        )
        projected_items = [
            project_timeline_item(row)
            for row in rows
        ]
        items = [
            TimelineItemResponse(**item)
            for item in projected_items
            if isinstance(item, dict)
        ]
        return TimelinePageResponse(items=items, has_more=has_more, next_cursor=next_cursor)

    return await db.run_sync(_db_work)


@router.get("/{conversation_id}/runtime", response_model=ConversationRuntimeResponse)
async def get_conversation_runtime(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await require_accessible_conversation_async(
        db,
        current_user=current_user,
        conversation_id=conversation_id,
    )

    payload = await db.run_sync(
        lambda sync_db: build_conversation_runtime_response(
            db=sync_db,
            conversation_id=conversation_id,
        )
    )
    return ConversationRuntimeResponse(**payload)


@router.post(
    "/{conversation_id}/messages/{message_id}/suggestions",
    response_model=MessageSuggestionsResponse,
)
async def get_message_suggestions(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    def _db_work(sync_db: Session) -> Dict[str, Any]:
        conversation = require_accessible_conversation_sync(
            sync_db,
            current_user=current_user,
            conversation_id=conversation_id,
        )

        anchor_message = (
            sync_db.query(Message)
            .filter(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Message.role == "assistant",
            )
            .first()
        )
        if anchor_message is None:
            raise HTTPException(status_code=404, detail="Message not found")

        rows = (
            sync_db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.role.in_(("user", "assistant")),
                or_(
                    Message.created_at < anchor_message.created_at,
                    and_(
                        Message.created_at == anchor_message.created_at,
                        Message.id <= anchor_message.id,
                    ),
                ),
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(300)
            .all()
        )

        history: List[Dict[str, Any]] = []
        for row in rows:
            text = row.text
            if not isinstance(text, str) or not text.strip():
                continue
            role = "assistant" if row.role == "assistant" else "user"
            history.append({"role": role, "content": text.strip()})

        project_context: Optional[str] = None
        if conversation.project_id:
            project = (
                sync_db.query(Project)
                .filter(Project.id == conversation.project_id)
                .first()
            )
            if project is not None and isinstance(project.name, str) and project.name.strip():
                project_context = project.name.strip()

        return {
            "history": history,
            "project_context": project_context,
            "project_id": str(conversation.project_id) if conversation.project_id else None,
        }

    projection = await db.run_sync(_db_work)
    suggestions = await generate_suggestions(
        conversation_history=projection.get("history", []),
        project_context=projection.get("project_context"),
        analytics_context={
            "user_id": str(current_user.id),
            "conversation_id": conversation_id,
            "project_id": projection.get("project_id"),
        },
    )
    return MessageSuggestionsResponse(message_id=message_id, suggestions=suggestions)


@router.post("/runs/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    run, conversation = await require_accessible_run_async(
        db,
        current_user=current_user,
        run_id=run_id,
    )

    run_status = str(getattr(run, "status", "") or "").lower()
    if run_status == "queued":
        def _cancel_queued(sync_db: Session) -> None:
            existing = sync_db.query(ChatRun).filter(ChatRun.id == run_id).first()
            if existing is None:
                return
            existing.status = "cancelled"
            existing.finished_at = datetime.now(timezone.utc)
            queued_message = (
                sync_db.query(Message)
                .filter(Message.run_id == run_id, Message.role == "user")
                .first()
            )
            if queued_message is not None:
                queued_message.status = "cancelled"
                queued_message.completed_at = datetime.now(timezone.utc)
            queued_turn = sync_db.query(ChatRunQueuedTurn).filter(ChatRunQueuedTurn.run_id == run_id).first()
            if queued_turn is not None:
                queued_turn.status = "cancelled"
            state = (
                sync_db.query(ConversationState)
                .filter(ConversationState.conversation_id == existing.conversation_id)
                .first()
            )
            if state is not None and str(state.active_run_id or "") == run_id:
                state.active_run_id = None
            sync_db.commit()

        await db.run_sync(_cancel_queued)
        return CancelRunResponse(run_id=run_id, status="cancelled")

    if run_status not in {"running", "paused"}:
        return CancelRunResponse(run_id=run_id, status=run_status or "completed")

    cancel_result = await cancel_conversation_stream(
        user=current_user,
        conversation_id=conversation.id,
        run_id=run_id,
        cancel_source="api.cancel",
        log_name="chat.stream.cancel_requested",
    )
    if not bool(cancel_result.get("persisted")):
        return CancelRunResponse(run_id=run_id, status="cancelled")

    return CancelRunResponse(run_id=run_id, status="cancelled")

@router.post("/runs/{run_id}/user-input", response_model=SubmitRunUserInputResponse)
async def submit_run_user_input(
    run_id: str,
    payload: SubmitRunUserInputRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    _run, conversation = await require_accessible_run_async(
        db,
        current_user=current_user,
        run_id=run_id,
    )
    recorded = await db.run_sync(
        lambda sync_db: record_run_user_input_submission(
            sync_db,
            run_id=run_id,
            conversation_id=conversation.id,
            requested_tool_call_id=payload.tool_call_id,
            submission_result=payload.result.model_dump(exclude_none=True),
        )
    )
    await _resume_interactive_run_or_revert(
        db=db,
        conversation_id=conversation.id,
        current_user_id=str(current_user.id),
        recorded=recorded,
    )

    return SubmitRunUserInputResponse(run_id=run_id, status="running")

