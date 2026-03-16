from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ..config.database import AsyncSessionLocal
from ..database.models import ChatRun, Message
from ..logging import log_event
from .services.run_activity_service import (
    build_run_activity_items_from_stream_state,
    sync_run_activity_items,
)
from .services.run_snapshot_service import (
    upsert_run_snapshot,
)
from .streaming_support import FinalizationOptions, StreamState
from .usage_calculator import UsageCalculator

logger = logging.getLogger(__name__)


class StreamingPersistenceMixin:
    """Persistence helpers extracted from ChatStreamingManager to keep streaming.py focused."""

    async def _checkpoint_partial_state(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        state: StreamState,
        usage_calculator: UsageCalculator,
        provider_name: str,
        effective_model: str,
        start_time: datetime,
        assistant_message_id: Optional[str],
        checkpoint_stream_event_id: int,
    ) -> Optional[str]:
        await self._finalize_state(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            state=state,
            usage_calculator=usage_calculator,
            provider_name=provider_name,
            effective_model=effective_model,
            start_time=start_time,
            assistant_message_id=assistant_message_id,
            message_status="streaming",
            include_done_chunk=False,
            update_user_message_status=False,
            checkpoint_mode=True,
            checkpoint_stream_event_id=checkpoint_stream_event_id,
        )
        return assistant_message_id

    @staticmethod
    def _resolve_persisted_assistant_message_id_sync(
        *,
        db,
        assistant_message_id: Optional[str],
    ) -> Optional[str]:
        if not assistant_message_id:
            return None
        message = (
            db.query(Message)
            .filter(Message.id == assistant_message_id)
            .first()
        )
        if message is None:
            return None
        return str(message.id)

    @staticmethod
    def _persist_live_runtime_projection_sync(
        *,
        db,
        conversation_id: str,
        user_message_id: str,
        state: StreamState,
        assistant_message_id: Optional[str],
        stream_event_id: int,
    ) -> None:
        run = (
            db.query(ChatRun)
            .filter(
                ChatRun.conversation_id == conversation_id,
                ChatRun.user_message_id == user_message_id,
            )
            .order_by(ChatRun.created_at.desc())
            .first()
        )
        if run is None:
            return

        persisted_assistant_message_id = (
            StreamingPersistenceMixin._resolve_persisted_assistant_message_id_sync(
                db=db,
                assistant_message_id=assistant_message_id,
            )
        )
        pending_requests = (
            state.pending_input_payload.get("pendingRequests")
            if isinstance(state.pending_input_payload, dict)
            else None
        )
        is_paused = isinstance(pending_requests, list) and len(pending_requests) > 0
        sync_run_activity_items(
            db=db,
            conversation_id=conversation_id,
            run_id=run.id,
            assistant_message_id=persisted_assistant_message_id,
            activity_items=build_run_activity_items_from_stream_state(run_id=run.id, state=state),
        )
        upsert_run_snapshot(
            db=db,
            conversation_id=conversation_id,
            run_id=run.id,
            run_message_id=user_message_id,
            assistant_message_id=persisted_assistant_message_id,
            status="paused" if is_paused else "running",
            seq=stream_event_id,
            status_label="Waiting for your input" if is_paused else state.current_step,
            draft_text=state.full_response,
            usage={},
        )

    async def _persist_live_runtime_projection(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        state: StreamState,
        assistant_message_id: Optional[str],
        stream_event_id: int,
    ) -> None:
        try:
            async with AsyncSessionLocal() as write_db:
                await write_db.run_sync(
                    lambda sync_db: self._persist_live_runtime_projection_sync(
                        db=sync_db,
                        conversation_id=conversation_id,
                        user_message_id=user_message_id,
                        state=state,
                        assistant_message_id=assistant_message_id,
                        stream_event_id=stream_event_id,
                    )
                )
                await write_db.commit()
        except Exception:
            log_event(
                logger,
                "WARNING",
                "chat.stream.runtime_projection_live_update_failed",
                "retry",
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                exc_info=True,
            )

    async def _finalize_if_stream_output(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        state: StreamState,
        usage_calculator: UsageCalculator,
        provider_name: str,
        effective_model: str,
        start_time: datetime,
        assistant_message_id: Optional[str],
        message_status: str,
        include_done_chunk: bool = True,
        update_user_message_status: bool = True,
        warning_event_name: str = "chat.stream.persist_failed_state",
        fallback_user_message_status: Optional[str] = None,
        assistant_created_at: Optional[datetime] = None,
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        if not state.has_stream_output():
            if fallback_user_message_status:
                await self._mark_message_status(user_message_id, fallback_user_message_status)
            return assistant_message_id, []
        try:
            persisted_message_id, done_events = await self._finalize_state(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                state=state,
                usage_calculator=usage_calculator,
                provider_name=provider_name,
                effective_model=effective_model,
                start_time=start_time,
                assistant_message_id=assistant_message_id,
                message_status=message_status,
                include_done_chunk=include_done_chunk,
                update_user_message_status=update_user_message_status,
                assistant_created_at=assistant_created_at,
            )
            if fallback_user_message_status and not done_events:
                await self._mark_message_status(user_message_id, fallback_user_message_status)
            return persisted_message_id, done_events
        except Exception:
            log_event(
                logger,
                "WARNING",
                warning_event_name,
                "retry",
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                exc_info=True,
            )
            if fallback_user_message_status:
                await self._mark_message_status(user_message_id, fallback_user_message_status)
            return assistant_message_id, []

    async def _finalize_state(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        state: StreamState,
        usage_calculator: UsageCalculator,
        provider_name: str,
        effective_model: str,
        start_time: datetime,
        assistant_message_id: Optional[str],
        message_status: str = "completed",
        include_done_chunk: bool = True,
        update_user_message_status: bool = True,
        checkpoint_mode: bool = False,
        checkpoint_stream_event_id: Optional[int] = None,
        done_pending_requests: Optional[List[Dict[str, Any]]] = None,
        assistant_created_at: Optional[datetime] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        return await self._finalize_with_session(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            state=state,
            usage_calculator=usage_calculator,
            provider_name=provider_name,
            effective_model=effective_model,
            start_time=start_time,
            cancelled=message_status in {"cancelled"},
            opts=FinalizationOptions(
                assistant_message_id=assistant_message_id,
                update_existing=bool(assistant_message_id),
                message_status=message_status,
                include_done_chunk=include_done_chunk,
                update_user_message_status=update_user_message_status,
                checkpoint_mode=checkpoint_mode,
                checkpoint_stream_event_id=checkpoint_stream_event_id,
                done_pending_requests=done_pending_requests,
                assistant_created_at=assistant_created_at,
            ),
        )

    async def _finalize_with_session(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        state: StreamState,
        usage_calculator: UsageCalculator,
        provider_name: str,
        effective_model: str,
        start_time: datetime,
        cancelled: bool,
        opts: Optional[FinalizationOptions] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Finalize stream output using a short-lived write session."""
        async with AsyncSessionLocal() as write_db:
            return await write_db.run_sync(
                lambda sync_db: self._finalizer.finalize_response(
                    db=sync_db,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    state=state,
                    usage_calculator=usage_calculator,
                    provider_name=provider_name,
                    effective_model=effective_model,
                    start_time=start_time,
                    cancelled=cancelled,
                    opts=opts,
                )
            )

    async def _mark_message_status(self, message_id: str, status: str) -> None:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"running", "paused", "completed", "failed", "cancelled"}:
            return
        try:
            async with AsyncSessionLocal() as write_db:
                run = await write_db.scalar(
                    select(ChatRun)
                    .where(ChatRun.user_message_id == message_id)
                    .order_by(ChatRun.created_at.desc())
                )
                if run is not None:
                    run.status = normalized_status
                    if normalized_status in {"completed", "failed", "cancelled"}:
                        run.finished_at = datetime.now(timezone.utc)
                await write_db.commit()
        except Exception:
            pass
