"""Run-engine orchestration for chat stream execution."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from time import perf_counter
from typing import Any, Dict, Optional

from ...config.settings import settings
from ...config.database import AsyncSessionLocal
from ...database.models import ChatRun
from ...logging import bind_log_context, log_event
from ...services.chat_streams import get_local_stream, schedule_cleanup
from ..services.event_store_service import append_event_sync
from ..streaming import ChatStreamingManager
from .runtime_inputs import PreparedRunInputs, RunInputPreparer, RunPreparationError
from .state_machine import RunState, RunStateMachine

logger = logging.getLogger(__name__)

_CANCEL_CHECK_EVERY_EVENTS = 3
_STREAM_CANCEL_POLL_SECONDS = 1.0


def infer_done_status(event_data: Dict[str, Any]) -> Optional[str]:
    """Infer normalized terminal status from a done event payload."""
    if not isinstance(event_data, dict) or event_data.get("type") != "done":
        return None
    done_data = event_data.get("data")
    if not isinstance(done_data, dict):
        return "completed"

    raw_status = done_data.get("status")
    if isinstance(raw_status, str):
        normalized = raw_status.strip().lower()
        if normalized in {"completed", "paused", "cancelled", "failed"}:
            return normalized

    if done_data.get("cancelled") is True:
        return "cancelled"
    return "completed"


class ChatRunEngine:
    """State-machine-driven run orchestration for a single chat request."""

    def __init__(
        self,
        *,
        conversation_id: str,
        user_id: str,
        user_message_id: str,
        resume_assistant_message_id: Optional[str] = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.user_message_id = user_message_id
        self.resume_assistant_message_id = resume_assistant_message_id

        self._state = RunStateMachine(state=RunState.RUNNING)
        self._input_preparer = RunInputPreparer()
        self._stream = None
        self._stream_event_id = 0
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._submit_received_mono: Optional[float] = None
        self._worker_started_mono: Optional[float] = None
        self._prep_done_mono: Optional[float] = None
        self._trace_id = "unknown"

    async def run(self) -> None:
        """Execute one run from stream registration through terminal state."""
        stream = get_local_stream(self.conversation_id)
        if not stream:
            log_event(
                logger,
                "ERROR",
                "chat.stream.missing_registration",
                "error",
                conversation_id=self.conversation_id,
            )
            return

        self._stream = stream
        self._submit_received_mono, self._trace_id = self._extract_submit_timing()

        bind_log_context(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            trace_id=self._trace_id,
        )

        self._worker_started_mono = perf_counter()
        log_event(
            logger,
            "INFO",
            "chat.stream.worker_start",
            "timing",
            elapsed_ms=self._since_submit_ms(self._worker_started_mono),
        )

        try:
            prepared_inputs = await self._input_preparer.prepare(
                conversation_id=self.conversation_id,
                user_message_id=self.user_message_id,
                stream_context=self._stream.context,
                resume_assistant_message_id=self.resume_assistant_message_id,
            )
            self._prep_done_mono = perf_counter()
            self._log_prepared()

            await self._stream.update_step("Generating response")

            if await self._stream.check_cancel():
                await self._set_status(RunState.CANCELLED)
                await self._stream.publish({"id": 1, "type": "done", "data": {"status": "cancelled"}})
                await schedule_cleanup(self.conversation_id)
                return

            await self._run_stream_loop(prepared_inputs)
        except RunPreparationError as prep_error:
            await self._set_status(RunState.FAILED)
            await self._stream.publish(
                {
                    "id": 1,
                    "type": "error",
                    "data": {"message": prep_error.message, "code": prep_error.code},
                }
            )
            await schedule_cleanup(self.conversation_id)
        except asyncio.CancelledError:
            log_event(
                logger,
                "INFO",
                "chat.stream.task_cancelled",
                "timing",
            )
            if self._stream.status == "running":
                await self._set_status(RunState.FAILED)
                await self._stream.publish(
                    {
                        "id": self._stream_event_id + 1,
                        "type": "error",
                        "data": {"message": "Server shutting down — please retry", "code": "SHUTDOWN"},
                    }
                )
            await schedule_cleanup(self.conversation_id)
        except Exception as exc:
            log_event(
                logger,
                "ERROR",
                "chat.stream.failed",
                "error",
                error_type=type(exc).__name__,
                exc_info=True,
            )
            if self._stream.status == "running":
                await self._set_status(RunState.FAILED)
                await self._stream.publish(
                    {
                        "id": self._stream_event_id + 1,
                        "type": "error",
                        "data": {"message": str(exc)[:500], "code": type(exc).__name__},
                    }
                )
            await schedule_cleanup(self.conversation_id)
            log_event(
                logger,
                "INFO",
                "chat.stream.failed_timing",
                "timing",
                elapsed_ms=self._since_submit_ms(perf_counter()),
                error_type=type(exc).__name__,
            )
        finally:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _run_stream_loop(self, prepared_inputs: PreparedRunInputs) -> None:
        stream_manager = ChatStreamingManager()
        cancelled_by_user = False
        terminal_status: Optional[str] = None
        stream_gen = stream_manager.stream_response(
            conversation_id=self.conversation_id,
            current_user_id=self.user_id,
            run_id=self._stream.run_id if self._stream is not None else None,
            conversation_history=[],  # streaming.py rebuilds from raw_messages
            raw_messages=prepared_inputs.raw_messages,
            user_prompt=prepared_inputs.user_prompt,
            allowed_file_ids=prepared_inputs.allowed_file_ids,
            user_message_id=self.user_message_id,
            current_message_attachments=prepared_inputs.attachments_meta,
            is_admin=prepared_inputs.is_admin,
            prefetched_context=(self._stream.context.prefetched_context if self._stream.context else None),
            resume_assistant_message_id=self.resume_assistant_message_id,
            seed_response_text=prepared_inputs.seed_response_text,
            seed_tool_markers=prepared_inputs.seed_tool_markers,
            seed_reasoning_summaries=prepared_inputs.seed_reasoning_summaries,
            seed_compaction_markers=prepared_inputs.seed_compaction_markers,
        )

        self._heartbeat_task = asyncio.create_task(self._stream_heartbeat())
        cancel_check_counter = 0
        first_event_logged = False
        first_content_logged = False
        pending_event_task: Optional[asyncio.Task] = None

        try:
            try:
                while True:
                    if pending_event_task is None:
                        pending_event_task = asyncio.create_task(stream_gen.__anext__())

                    done, _ = await asyncio.wait(
                        {pending_event_task},
                        timeout=_STREAM_CANCEL_POLL_SECONDS,
                    )

                    if not done:
                        if await self._stream.check_cancel():
                            log_event(
                                logger,
                                "INFO",
                                "chat.stream.cancelled_by_user",
                                "timing",
                            )
                            cancelled_by_user = True
                            pending_event_task.cancel()
                            with suppress(asyncio.CancelledError, StopAsyncIteration):
                                await pending_event_task
                            pending_event_task = None
                            break
                        continue

                    task = pending_event_task
                    pending_event_task = None

                    try:
                        event_data = task.result()
                    except StopAsyncIteration:
                        break

                    if not isinstance(event_data, dict):
                        continue

                    if not first_event_logged:
                        first_event_logged = True
                        first_event_type = str(event_data.get("type") or "")
                        now_mono = perf_counter()
                        log_event(
                            logger,
                            "INFO",
                            "chat.stream.first_event",
                            "timing",
                            event_type=first_event_type,
                            since_submit_ms=self._since_submit_ms(now_mono),
                            since_worker_ms=self._since_worker_ms(now_mono),
                            since_prep_ms=self._since_prep_ms(now_mono),
                        )

                    self._stream_event_id += 1
                    event_data["id"] = self._stream_event_id

                    # Publish to Redis Stream for cross-worker browser delivery.
                    await self._stream.publish(event_data)

                    event_type = event_data.get("type", "")
                    if event_type == "content.delta":
                        event_payload = event_data.get("data", {})
                        status_label = (
                            event_payload.get("statusLabel")
                            if isinstance(event_payload, dict)
                            else None
                        )
                        if not first_content_logged:
                            first_content_logged = True
                            now_mono = perf_counter()
                            log_event(
                                logger,
                                "INFO",
                                "chat.stream.first_content",
                                "timing",
                                since_submit_ms=self._since_submit_ms(now_mono),
                                since_worker_ms=self._since_worker_ms(now_mono),
                                since_prep_ms=self._since_prep_ms(now_mono),
                            )
                        if isinstance(status_label, str) and status_label.strip():
                            await self._stream.update_step(status_label)
                    elif event_type in {"run.status", "tool.started", "tool.progress", "input.requested"}:
                        event_payload = event_data.get("data", {})
                        status_label = (
                            event_payload.get("statusLabel")
                            if isinstance(event_payload, dict)
                            else None
                        )
                        if isinstance(status_label, str) and status_label.strip():
                            await self._stream.update_step(status_label)

                    if event_type in {"error", "run.failed"}:
                        terminal_status = "failed"
                        break

                    if event_type == "done":
                        terminal_status = infer_done_status(event_data) or "completed"
                        break

                    cancel_check_counter += 1
                    if cancel_check_counter >= _CANCEL_CHECK_EVERY_EVENTS:
                        cancel_check_counter = 0
                        if await self._stream.check_cancel():
                            log_event(
                                logger,
                                "INFO",
                                "chat.stream.cancelled_by_user",
                                "timing",
                            )
                            cancelled_by_user = True
                            break
            finally:
                if pending_event_task is not None:
                    pending_event_task.cancel()
                    with suppress(asyncio.CancelledError, StopAsyncIteration):
                        await pending_event_task
        except Exception as stream_error:
            log_event(
                logger,
                "ERROR",
                "chat.stream.error",
                "error",
                error_type=type(stream_error).__name__,
                exc_info=True,
            )
            self._stream_event_id += 1
            await self._stream.publish(
                {
                    "id": self._stream_event_id,
                    "type": "error",
                    "data": {"message": str(stream_error)[:500], "code": type(stream_error).__name__},
                }
            )
            await self._set_status(RunState.FAILED)
            await schedule_cleanup(self.conversation_id)
            return

        if cancelled_by_user:
            flushed_terminal_status = await self._flush_cancelled_stream(stream_gen=stream_gen)
            if flushed_terminal_status in {"completed", "paused", "cancelled", "failed"}:
                terminal_status = flushed_terminal_status
            if terminal_status is None:
                terminal_status = "cancelled"
                self._stream_event_id += 1
                await self._stream.publish(
                    {"id": self._stream_event_id, "type": "done", "data": {"status": "cancelled"}}
                )
            await self._set_status(RunState.CANCELLED)
            await schedule_cleanup(self.conversation_id)
            log_event(
                logger,
                "INFO",
                "chat.stream.cancelled",
                "timing",
                stream_event_count=self._stream_event_id,
                elapsed_ms=self._since_submit_ms(perf_counter()),
            )
            return

        if terminal_status == "paused":
            await self._set_status(RunState.PAUSED)
            await schedule_cleanup(self.conversation_id)
            log_event(
                logger,
                "INFO",
                "chat.stream.paused",
                "timing",
                elapsed_ms=self._since_submit_ms(perf_counter()),
            )
            return

        if terminal_status == "cancelled":
            await self._set_status(RunState.CANCELLED)
            await schedule_cleanup(self.conversation_id)
            log_event(
                logger,
                "INFO",
                "chat.stream.cancelled",
                "timing",
                stream_event_count=self._stream_event_id,
                elapsed_ms=self._since_submit_ms(perf_counter()),
            )
            return

        if terminal_status == "failed":
            await self._set_status(RunState.FAILED)
            await schedule_cleanup(self.conversation_id)
            log_event(
                logger,
                "INFO",
                "chat.stream.failed_timing",
                "timing",
                elapsed_ms=self._since_submit_ms(perf_counter()),
                error_type="provider_error_event",
            )
            return

        if terminal_status is None:
            terminal_status = "completed"
            self._stream_event_id += 1
            await self._stream.publish(
                {"id": self._stream_event_id, "type": "done", "data": {"status": "completed"}}
            )

        await self._set_status(RunState.COMPLETED)
        await schedule_cleanup(self.conversation_id)
        log_event(
            logger,
            "INFO",
            "chat.stream.completed",
            "timing",
            stream_event_count=self._stream_event_id,
            elapsed_ms=self._since_submit_ms(perf_counter()),
        )

    async def _flush_cancelled_stream(self, *, stream_gen) -> Optional[str]:
        terminal_status: Optional[str] = None
        try:
            try:
                event_data = await stream_gen.athrow(asyncio.CancelledError())
                if isinstance(event_data, dict):
                    self._stream_event_id += 1
                    event_data["id"] = self._stream_event_id
                    await self._stream.publish(event_data)
                    inferred_status = infer_done_status(event_data)
                    if inferred_status:
                        terminal_status = inferred_status
                async for event_data in stream_gen:
                    if isinstance(event_data, dict):
                        self._stream_event_id += 1
                        event_data["id"] = self._stream_event_id
                        await self._stream.publish(event_data)
                        inferred_status = infer_done_status(event_data)
                        if inferred_status:
                            terminal_status = inferred_status
            except StopAsyncIteration:
                pass
        except Exception as cleanup_error:
            log_event(
                logger,
                "WARNING",
                "chat.stream.cancel_cleanup_failed",
                "retry",
                error_type=type(cleanup_error).__name__,
                exc_info=True,
            )
        return terminal_status

    async def _stream_heartbeat(self) -> None:
        """Refresh active stream TTLs so long-running generations stay resumable."""
        interval = max(5, int(getattr(settings, "redis_stream_heartbeat_interval", 30) or 30))
        try:
            while self._stream and self._stream.status == "running":
                await asyncio.sleep(interval)
                await self._stream.touch()
        except asyncio.CancelledError:
            pass
        except Exception:
            log_event(
                logger,
                "DEBUG",
                "chat.stream.heartbeat_failed",
                "retry",
                conversation_id=self.conversation_id,
                exc_info=True,
            )

    async def _set_status(self, next_state: RunState) -> None:
        if not self._stream:
            return
        try:
            self._state.transition(next_state)
        except ValueError:
            log_event(
                logger,
                "WARNING",
                "chat.run.invalid_transition",
                "retry",
                conversation_id=self.conversation_id,
                from_state=self._state.state.value,
                to_state=next_state.value,
            )
            # Keep moving in runtime to avoid leaking a stuck stream.
            self._state.state = next_state
        await self._stream.set_status(next_state.value)
        await self._persist_run_status(next_state.value)

    async def _persist_run_status(self, status: str) -> None:
        """Best-effort persistence of run status to chat_runs + event store."""
        normalized = str(status or "").strip().lower()
        if not normalized:
            return

        async with AsyncSessionLocal() as db:
            def _db_work(sync_db):
                run = (
                    sync_db.query(ChatRun)
                    .filter(ChatRun.user_message_id == self.user_message_id)
                    .order_by(ChatRun.created_at.desc())
                    .first()
                )
                run_id = None
                if run is not None:
                    run.status = normalized
                    run_id = run.id
                    if normalized in {"completed", "failed", "cancelled"}:
                        from datetime import datetime, timezone

                        run.finished_at = datetime.now(timezone.utc)

                append_event_sync(
                    sync_db,
                    conversation_id=self.conversation_id,
                    event_type="run_state",
                    actor="system",
                    run_id=run_id,
                    payload={"status": normalized, "source": "engine.status"},
                )
                sync_db.commit()

            try:
                await db.run_sync(_db_work)
            except Exception:
                log_event(
                    logger,
                    "DEBUG",
                    "chat.run.status_persist_failed",
                    "retry",
                    conversation_id=self.conversation_id,
                    user_message_id=self.user_message_id,
                    status=normalized,
                    exc_info=True,
                )

    def _extract_submit_timing(self) -> tuple[Optional[float], str]:
        submit_received_mono: Optional[float] = None
        trace_id = "unknown"
        ctx = self._stream.context if self._stream else None
        try:
            timing = (
                (ctx.prefetched_context or {}).get("timing")
                if ctx and isinstance(ctx.prefetched_context, dict)
                else None
            )
            if isinstance(timing, dict):
                raw_submit = timing.get("submit_received_monotonic")
                if isinstance(raw_submit, (int, float)):
                    submit_received_mono = float(raw_submit)
                raw_trace = timing.get("trace_id")
                if isinstance(raw_trace, str) and raw_trace.strip():
                    trace_id = raw_trace.strip()
        except Exception:
            submit_received_mono = None
            trace_id = "unknown"
        return submit_received_mono, trace_id

    def _log_prepared(self) -> None:
        log_event(
            logger,
            "INFO",
            "chat.stream.prepared",
            "timing",
            since_submit_ms=self._since_submit_ms(self._prep_done_mono),
            since_worker_ms=self._since_worker_ms(self._prep_done_mono),
        )

    def _since_submit_ms(self, now_mono: Optional[float]) -> Optional[float]:
        if now_mono is None or self._submit_received_mono is None:
            return None
        return round((now_mono - self._submit_received_mono) * 1000.0, 1)

    def _since_worker_ms(self, now_mono: Optional[float]) -> Optional[float]:
        if now_mono is None or self._worker_started_mono is None:
            return None
        return round((now_mono - self._worker_started_mono) * 1000.0, 1)

    def _since_prep_ms(self, now_mono: Optional[float]) -> Optional[float]:
        if now_mono is None or self._prep_done_mono is None:
            return None
        return round((now_mono - self._prep_done_mono) * 1000.0, 1)
