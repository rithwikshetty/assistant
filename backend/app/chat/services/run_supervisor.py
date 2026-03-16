"""Local background supervisor for queued chat runs."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select

from ...config.database import AsyncSessionLocal
from ...config.settings import settings
from ...database.models import ChatRun, ChatRunQueuedTurn, ConversationState
from ...logging import log_event
from ...services.chat_streams import StreamContext
from .run_queue_service import (
    acknowledge_run_command,
    build_consumer_name,
    claim_global_run_capacity,
    ensure_run_queue_group,
    read_next_run_command,
    release_global_run_capacity,
)
from .stream_runner import launch_chat_stream_and_wait

logger = logging.getLogger(__name__)


class RunSupervisor:
    def __init__(self) -> None:
        self._stop_event = asyncio.Event()
        self._reader_tasks: list[asyncio.Task[None]] = []
        self._executor_limit = max(1, int(getattr(settings, "run_supervisor_local_concurrency", 8) or 8))
        self._global_limit = max(
            self._executor_limit,
            int(getattr(settings, "run_supervisor_global_concurrency", 100) or 100),
        )
        self._reader_count = max(
            1,
            min(self._executor_limit, int(getattr(settings, "run_supervisor_reader_count", 4) or 4)),
        )
        self._executor = asyncio.Semaphore(self._executor_limit)
        self._consumer_name = build_consumer_name()

    async def start(self) -> None:
        await ensure_run_queue_group()
        self._stop_event.clear()
        self._reader_tasks = [
            asyncio.create_task(self._reader_loop(index))
            for index in range(self._reader_count)
        ]
        log_event(
            logger,
            "INFO",
            "chat.run_supervisor.started",
            "final",
            reader_count=self._reader_count,
            executor_limit=self._executor_limit,
            global_limit=self._global_limit,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        for task in self._reader_tasks:
            task.cancel()
        if self._reader_tasks:
            await asyncio.gather(*self._reader_tasks, return_exceptions=True)
        self._reader_tasks = []
        log_event(logger, "INFO", "chat.run_supervisor.stopped", "final")

    async def _reader_loop(self, reader_index: int) -> None:
        block_ms = max(250, int(getattr(settings, "run_supervisor_block_ms", 1500) or 1500))
        try:
            while not self._stop_event.is_set():
                next_item = await read_next_run_command(
                    consumer_name=f"{self._consumer_name}-{reader_index}",
                    block_ms=block_ms,
                )
                if next_item is None:
                    continue
                entry_id, payload = next_item
                await self._schedule_entry(entry_id=entry_id, payload=payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            log_event(
                logger,
                "ERROR",
                "chat.run_supervisor.reader_failed",
                "error",
                reader_index=reader_index,
                exc_info=True,
            )

    async def _schedule_entry(self, *, entry_id: str, payload: Dict[str, Any]) -> None:
        conversation_id = str(payload.get("conversation_id") or "").strip()
        run_id = str(payload.get("run_id") or "").strip()
        user_id = str(payload.get("user_id") or "").strip()
        user_message_id = str(payload.get("user_message_id") or "").strip()
        resume_assistant_message_id = str(payload.get("resume_assistant_message_id") or "").strip() or None
        stream_context = self._deserialize_stream_context(payload.get("stream_context"))
        if not conversation_id or not run_id or not user_id or not user_message_id:
            await acknowledge_run_command(entry_id)
            return

        while not self._stop_event.is_set():
            dispatch_state = await self._run_dispatch_state(
                conversation_id=conversation_id,
                run_id=run_id,
            )
            if dispatch_state == "drop":
                await acknowledge_run_command(entry_id)
                return
            if dispatch_state != "ready":
                await asyncio.sleep(0.25)
                continue

            await self._executor.acquire()
            claimed = False
            try:
                claimed = await claim_global_run_capacity(self._global_limit)
                if not claimed:
                    await asyncio.sleep(0.25)
                    continue

                asyncio.create_task(
                    self._execute_entry(
                        entry_id=entry_id,
                        conversation_id=conversation_id,
                        run_id=run_id,
                        user_id=user_id,
                        user_message_id=user_message_id,
                        resume_assistant_message_id=resume_assistant_message_id,
                        stream_context=stream_context,
                    )
                )
                return
            finally:
                if not claimed:
                    self._executor.release()

    async def _run_dispatch_state(self, *, conversation_id: str, run_id: str) -> str:
        async with AsyncSessionLocal() as db:
            run = await db.scalar(select(ChatRun).where(ChatRun.id == run_id))
            if run is None:
                return "drop"
            if str(run.status or "").strip().lower() in {"cancelled", "failed", "completed", "interrupted"}:
                return "drop"

            conversation_state = await db.scalar(
                select(ConversationState).where(ConversationState.conversation_id == conversation_id)
            )
            if conversation_state is not None and conversation_state.active_run_id:
                active_run_id = str(conversation_state.active_run_id)
                if active_run_id and active_run_id != run_id:
                    return "blocked"

            queued_turn = await db.scalar(select(ChatRunQueuedTurn).where(ChatRunQueuedTurn.run_id == run_id))
            if queued_turn is not None and queued_turn.blocked_by_run_id:
                blocked_id = str(queued_turn.blocked_by_run_id)
                if blocked_id:
                    blocked_run = await db.scalar(select(ChatRun).where(ChatRun.id == blocked_id))
                    if blocked_run is not None and str(blocked_run.status or "").strip().lower() in {"queued", "running", "paused"}:
                        return "blocked"
            return "ready"

    async def _execute_entry(
        self,
        *,
        entry_id: str,
        conversation_id: str,
        run_id: str,
        user_id: str,
        user_message_id: str,
        resume_assistant_message_id: Optional[str],
        stream_context: Optional[StreamContext],
    ) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await db.run_sync(
                    lambda sync_db: self._mark_run_started(
                        sync_db,
                        conversation_id=conversation_id,
                        run_id=run_id,
                    )
                )
                await db.commit()

            # LAT-001: Queue acknowledgement is deferred to the
            # on_registered callback so it only fires after Redis stream
            # registration AND initial DB snapshot persistence succeed.
            # If the process dies before that point the queue entry stays
            # pending and can be reclaimed by another worker.
            await launch_chat_stream_and_wait(
                conversation_id=conversation_id,
                user_id=user_id,
                user_message_id=user_message_id,
                run_id=run_id,
                context=stream_context,
                resume_assistant_message_id=resume_assistant_message_id,
                on_registered=lambda: acknowledge_run_command(entry_id),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log_event(
                logger,
                "ERROR",
                "chat.run_supervisor.execution_failed",
                "error",
                conversation_id=conversation_id,
                run_id=run_id,
                user_id=user_id,
                exc_info=True,
            )
            async with AsyncSessionLocal() as db:
                await db.run_sync(
                    lambda sync_db: self._mark_run_failed(
                        sync_db,
                        conversation_id=conversation_id,
                        run_id=run_id,
                    )
                )
                await db.commit()
            with suppress(Exception):
                await acknowledge_run_command(entry_id)
        finally:
            self._executor.release()
            with suppress(Exception):
                await release_global_run_capacity()

    @staticmethod
    def _deserialize_stream_context(raw: Any) -> Optional[StreamContext]:
        if not isinstance(raw, dict):
            return None
        user_content = raw.get("user_content")
        attachments_meta = raw.get("attachments_meta")
        prefetched_context = raw.get("prefetched_context")
        if not isinstance(user_content, str):
            return None
        if not isinstance(attachments_meta, list):
            attachments_meta = []
        normalized_attachments = [item for item in attachments_meta if isinstance(item, dict)]
        return StreamContext(
            user_content=user_content,
            attachments_meta=normalized_attachments,
            is_admin=bool(raw.get("is_admin")),
            is_new_conversation=bool(raw.get("is_new_conversation")),
            prefetched_context=prefetched_context if isinstance(prefetched_context, dict) else None,
        )

    @staticmethod
    def _mark_run_started(sync_db, *, conversation_id: str, run_id: str) -> None:
        from .run_snapshot_service import ensure_conversation_state

        run = sync_db.query(ChatRun).filter(ChatRun.id == run_id).first()
        if run is None:
            return
        now = datetime.now(timezone.utc)
        run.status = "running"
        run.started_at = now
        run.updated_at = now

        queued_turn = sync_db.query(ChatRunQueuedTurn).filter(ChatRunQueuedTurn.run_id == run_id).first()
        if queued_turn is not None:
            sync_db.delete(queued_turn)

        conversation_state = ensure_conversation_state(db=sync_db, conversation_id=conversation_id)
        conversation_state.active_run_id = run_id
        conversation_state.awaiting_user_input = False

    @staticmethod
    def _mark_run_failed(sync_db, *, conversation_id: str, run_id: str) -> None:
        run = sync_db.query(ChatRun).filter(ChatRun.id == run_id).first()
        if run is not None and str(run.status or "").strip().lower() in {"queued", "running"}:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
        conversation_state = (
            sync_db.query(ConversationState)
            .filter(ConversationState.conversation_id == conversation_id)
            .first()
        )
        if conversation_state is not None and str(conversation_state.active_run_id or "") == run_id:
            conversation_state.active_run_id = None


_RUN_SUPERVISOR: Optional[RunSupervisor] = None


async def start_run_supervisor() -> None:
    global _RUN_SUPERVISOR
    if _RUN_SUPERVISOR is not None:
        return
    supervisor = RunSupervisor()
    await supervisor.start()
    _RUN_SUPERVISOR = supervisor


async def stop_run_supervisor() -> None:
    global _RUN_SUPERVISOR
    if _RUN_SUPERVISOR is None:
        return
    supervisor = _RUN_SUPERVISOR
    _RUN_SUPERVISOR = None
    await supervisor.stop()
