from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import AsyncGenerator, Dict, Any, List, Optional, Set

import anyio
from sqlalchemy import select

from ..config.settings import settings
from ..logging import bind_log_context, log_event
from ..services.files import file_service
from .provider_registry import get_chat_streamer
from .streaming_support import StreamState
from .streaming_helpers import StreamingHelpersMixin
from .streaming_persistence import StreamingPersistenceMixin
from .usage_calculator import UsageCalculator
from .services.stream_attempt_builder import StreamAttemptBuilder
from .services.stream_context_builder import StreamContextBuilder
from .services.stream_event_handler import StreamEventHandler
from .services.stream_finalizer import StreamFinalizer
from .services.input_items_cache import get_cached_input_items, set_cached_input_items
from .services.stream_runtime_context_loader import StreamRuntimeContextLoader
from .services.history_formatter import format_history_for_provider


logger = logging.getLogger(__name__)


class ChatStreamingManager(StreamingHelpersMixin, StreamingPersistenceMixin):
    """Encapsulates live chat stream orchestration for chat responses."""

    def __init__(self) -> None:
        self._attempt_builder = StreamAttemptBuilder()
        self._context_builder = StreamContextBuilder()
        self._event_handler = StreamEventHandler()
        self._finalizer = StreamFinalizer()
        self._runtime_context_loader = StreamRuntimeContextLoader()

    @staticmethod
    def _pending_request_count(state: StreamState) -> int:
        pending_requests = (
            state.pending_input_payload.get("pendingRequests")
            if isinstance(state.pending_input_payload, dict)
            else None
        )
        return len(pending_requests) if isinstance(pending_requests, list) else 0

    @classmethod
    def _persistence_signature(cls, state: StreamState) -> tuple[Any, ...]:
        completed_tools = 0
        errored_tools = 0
        queried_tools = 0
        last_tool_call_id = ""
        for marker in state.tool_markers:
            if not isinstance(marker, dict):
                continue
            if "result" in marker:
                completed_tools += 1
            if "error" in marker:
                errored_tools += 1
            if isinstance(marker.get("query"), str) and marker.get("query"):
                queried_tools += 1
            call_id = marker.get("call_id")
            if isinstance(call_id, str) and call_id:
                last_tool_call_id = call_id

        last_reasoning_id = ""
        if state.reasoning_summaries:
            last_reasoning = state.reasoning_summaries[-1]
            if isinstance(last_reasoning, dict):
                candidate = last_reasoning.get("id")
                if isinstance(candidate, str) and candidate:
                    last_reasoning_id = candidate

        return (
            state.current_step or "",
            len(state.tool_markers),
            completed_tools,
            errored_tools,
            queried_tools,
            last_tool_call_id,
            len(state.reasoning_summaries),
            last_reasoning_id,
            len(state.compaction_markers),
            cls._pending_request_count(state),
            bool(state.awaiting_user_input),
            bool(state.finished),
        )

    @classmethod
    def _should_persist_live_runtime_projection(
        cls,
        *,
        state: StreamState,
        last_signature: tuple[Any, ...],
        last_text_len: int,
    ) -> bool:
        current_signature = cls._persistence_signature(state)
        if current_signature != last_signature:
            return True
        return len(state.full_response) > last_text_len

    async def stream_response(
        self,
        *,
        conversation_id: str,
        current_user_id: str,
        run_id: Optional[str],
        conversation_history: List[Dict[str, str]],
        raw_messages: List[Dict[str, Any]],
        user_prompt: str,
        allowed_file_ids: Set[str],
        user_message_id: str,
        current_message_attachments: Optional[List[Dict[str, Any]]] = None,
        is_admin: bool = False,
        prefetched_context: Optional[Dict[str, Any]] = None,
        resume_assistant_message_id: Optional[str] = None,
        seed_response_text: Optional[str] = None,
        seed_tool_markers: Optional[List[Dict[str, Any]]] = None,
        seed_reasoning_summaries: Optional[List[Dict[str, Any]]] = None,
        seed_compaction_markers: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        start_time = datetime.now(timezone.utc)
        prefetched_context = prefetched_context or {}
        timing = prefetched_context.get("timing") if isinstance(prefetched_context, dict) else None
        trace_id = "unknown"
        submit_received_mono: Optional[float] = None
        if isinstance(timing, dict):
            raw_trace = timing.get("trace_id")
            if isinstance(raw_trace, str) and raw_trace.strip():
                trace_id = raw_trace.strip()
            raw_submit = timing.get("submit_received_monotonic")
            if isinstance(raw_submit, (int, float)):
                submit_received_mono = float(raw_submit)

        runtime_context = await self._runtime_context_loader.load(
            prefetched_context=prefetched_context,
            current_user_id=current_user_id,
            conversation_id=conversation_id,
            context_builder=self._context_builder,
            resolve_provider_and_model=self._resolve_provider_and_model,
            coerce_metadata_dict=self._coerce_metadata_dict,
        )
        current_user = runtime_context.current_user
        provider_name = runtime_context.provider_name
        effective_model = runtime_context.effective_model
        reasoning_effort = runtime_context.reasoning_effort
        user_name = runtime_context.user_name
        project_name = runtime_context.project_name
        project_description = runtime_context.project_description
        project_custom_instructions = runtime_context.project_custom_instructions
        project_id = runtime_context.project_id
        project_files_summary = runtime_context.project_files_summary
        current_date = runtime_context.current_date
        current_time = runtime_context.current_time
        effective_timezone = runtime_context.effective_timezone
        user_custom_instructions = runtime_context.user_custom_instructions
        base_conversation_metadata = runtime_context.base_conversation_metadata
        skills_prompt_section = runtime_context.skills_prompt_section

        # Always format history for the resolved provider so block types align
        # with the downstream API request shape.
        conversation_history = format_history_for_provider(
            provider_name,
            raw_messages,
            file_service=file_service,
            db=None,
        )

        bind_log_context(
            conversation_id=conversation_id,
            user_id=current_user_id,
            trace_id=trace_id,
        )
        log_event(
            logger,
            "INFO",
            "chat.stream.model_resolved",
            "timing",
            model=effective_model,
        )

        # Build tool context using service
        tool_context = self._context_builder.build_tool_context(
            None,
            current_user_id,
            conversation_id,
            allowed_file_ids,
            project_id,
            current_user,
            user_timezone=effective_timezone,
        )
        # Add admin flag to tool context for conditional tool access
        tool_context["is_admin"] = is_admin
        if isinstance(run_id, str) and run_id.strip():
            tool_context["active_run_id"] = run_id.strip()

        # Load prior input snapshot from Redis cache for follow-up continuity.
        try:
            cached_input_items = await get_cached_input_items(conversation_id)
            if cached_input_items:
                tool_context["stored_input_items"] = cached_input_items
                log_event(
                    logger,
                    "INFO",
                    "chat.stream.input_snapshot_cache_hit",
                    "timing",
                    conversation_id=conversation_id,
                    item_count=len(cached_input_items),
                )
        except Exception:
            log_event(
                logger, "WARNING", "chat.stream.input_snapshot_load_failed",
                "retry", conversation_id=conversation_id, exc_info=True,
            )

        usage_calculator = UsageCalculator()
        state: Optional[StreamState] = None
        active_provider = provider_name
        active_model = effective_model
        active_reasoning_effort = reasoning_effort
        is_resume = bool(resume_assistant_message_id)
        persisted_assistant_message_id: Optional[str] = resume_assistant_message_id
        checkpoint_interval_seconds = max(
            0.5,
            float(getattr(settings, "stream_checkpoint_interval_seconds", 2.0) or 2.0),
        )
        live_runtime_projection_interval_seconds = 0.5
        checkpoint_char_threshold = 1200
        checkpoint_dirty = False
        live_runtime_projection_dirty = False
        last_checkpoint_mono = 0.0
        last_live_runtime_projection_mono = 0.0
        published_event_cursor = 0
        queued_turn_handoff_created_at: Optional[datetime] = None

        try:
            prepared_attempt = self._attempt_builder.prepare_attempt(
                provider_name=provider_name,
                effective_model=effective_model,
                reasoning_effort=reasoning_effort,
                conversation_history=conversation_history,
                user_prompt=user_prompt,
                current_message_attachments=current_message_attachments,
                tool_context=tool_context,
                is_admin=is_admin,
                user_name=user_name,
                current_date=current_date,
                current_time=current_time,
                user_timezone=effective_timezone,
                project_name=project_name,
                project_description=project_description,
                project_custom_instructions=project_custom_instructions,
                project_files_summary=project_files_summary,
                user_custom_instructions=user_custom_instructions,
                skills_prompt_section=skills_prompt_section,
                resume_assistant_message_id=resume_assistant_message_id,
                seed_response_text=seed_response_text,
                seed_tool_markers=seed_tool_markers,
                seed_reasoning_summaries=seed_reasoning_summaries,
                seed_compaction_markers=seed_compaction_markers,
                file_service=file_service,
                base_conversation_metadata=base_conversation_metadata,
            )

            attempt_provider = prepared_attempt.provider_name
            attempt_model = prepared_attempt.model_name
            attempt_reasoning_effort = prepared_attempt.reasoning_effort
            attempt_streamer = get_chat_streamer(attempt_provider)
            state = prepared_attempt.state
            stream_kwargs = prepared_attempt.stream_kwargs
            active_provider = attempt_provider
            active_model = attempt_model
            active_reasoning_effort = attempt_reasoning_effort

            def _finalize_base_kwargs() -> Dict[str, Any]:
                return {
                    "conversation_id": conversation_id,
                    "user_message_id": user_message_id,
                    "state": state,
                    "usage_calculator": usage_calculator,
                    "provider_name": active_provider,
                    "effective_model": active_model,
                    "start_time": start_time,
                    "assistant_message_id": persisted_assistant_message_id,
                }

            assert state is not None
            last_live_runtime_projection_signature = self._persistence_signature(state)
            last_checkpoint_signature = last_live_runtime_projection_signature
            last_live_runtime_projection_text_len = len(state.full_response)
            last_checkpoint_text_len = len(state.full_response)

            log_event(
                logger,
                "INFO",
                "chat.stream.provider_selected",
                "timing",
                provider=attempt_provider,
                model=attempt_model,
            )

            live_usage_signature: Optional[str] = None

            provider_request_started_mono = perf_counter()
            log_event(
                logger,
                "INFO",
                "chat.stream.provider_start",
                "timing",
                provider=attempt_provider,
                model=attempt_model,
                since_submit_ms=(
                    round((provider_request_started_mono - submit_received_mono) * 1000.0, 1)
                    if submit_received_mono is not None
                    else None
                ),
            )

            stream_iterator = attempt_streamer(**stream_kwargs)
            stream_timeout_seconds = int(getattr(settings, "stream_timeout_seconds", 3600) or 0)
            first_provider_update_logged = False
            first_provider_text_logged = False

            # Wrap stream iteration with timeout to detect stuck streams
            async for update in self._stream_with_timeout(stream_iterator, stream_timeout_seconds):
                update_type = str(update.get("type") or "")

                # `input_items_snapshot` updates are consumed internally by
                # StreamEventHandler (not emitted as client events), so cache
                # side effects must run against the raw provider update.
                await self._cache_input_snapshot_if_present(
                    conversation_id=conversation_id,
                    update=update,
                )

                if not first_provider_update_logged:
                    first_provider_update_logged = True
                    now_mono = perf_counter()
                    log_event(
                        logger,
                        "INFO",
                        "chat.stream.provider_first_update",
                        "timing",
                        provider=attempt_provider,
                        model=attempt_model,
                        event_type=update_type,
                        since_submit_ms=(
                            round((now_mono - submit_received_mono) * 1000.0, 1)
                            if submit_received_mono is not None
                            else None
                        ),
                        since_provider_start_ms=round((now_mono - provider_request_started_mono) * 1000.0, 1),
                    )

                if not first_provider_text_logged:
                    has_text_delta = False
                    if update_type == "message":
                        has_text_delta = bool(update.get("content"))
                    elif update_type == "response":
                        has_text_delta = bool(update.get("delta"))
                    elif update_type == "response_complete":
                        has_text_delta = bool(update.get("content"))

                    if has_text_delta:
                        first_provider_text_logged = True
                        now_mono = perf_counter()
                        log_event(
                            logger,
                            "INFO",
                            "chat.stream.provider_first_text",
                            "timing",
                            provider=attempt_provider,
                            model=attempt_model,
                            event_type=update_type,
                            since_submit_ms=(
                                round((now_mono - submit_received_mono) * 1000.0, 1)
                                if submit_received_mono is not None
                                else None
                            ),
                            since_provider_start_ms=round((now_mono - provider_request_started_mono) * 1000.0, 1),
                        )

                for event_payload in self._event_handler.handle(update, state):
                    published_event_cursor += 1
                    yield event_payload

                if update_type == "queued_turn_handoff":
                    payload = update.get("data") or update.get("content") or {}
                    if isinstance(payload, dict):
                        raw_created_at = payload.get("created_at")
                        if isinstance(raw_created_at, str) and raw_created_at.strip():
                            try:
                                parsed_created_at = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
                            except ValueError:
                                parsed_created_at = None
                            if parsed_created_at is not None:
                                queued_turn_handoff_created_at = parsed_created_at - timedelta(microseconds=1)
                    state.current_step = None
                    break

                if update_type == "live_context_usage" and state.live_input_tokens > 0:
                    token_usage_event = self._build_token_count_conversation_usage_event(
                        input_tokens=state.live_input_tokens,
                        usage_calculator=usage_calculator,
                        model_name=attempt_model,
                    )
                    if token_usage_event is not None:
                        candidate_sig = self._live_usage_signature(token_usage_event)
                        if candidate_sig != live_usage_signature:
                            live_usage_signature = candidate_sig
                            published_event_cursor += 1
                            yield token_usage_event

                # Emit provider-derived usage events only when the token
                # counting API is NOT in use. When we have accurate live
                # token counts (WebSocket + store=false path), provider
                # raw_responses report 0 usage which — combined with
                # max()-based accumulation in create_conversation_usage —
                # would overwrite the accurate post-compaction values with
                # stale highs from previous turns.
                if (
                    self._event_handler.is_live_usage_relevant_event(update_type)
                    and state.live_input_tokens <= 0
                ):
                    live_usage_event = self._build_live_conversation_usage_event(
                        state=state,
                        usage_calculator=usage_calculator,
                        provider_name=attempt_provider,
                        fallback_model=attempt_model,
                        base_conversation_metadata=base_conversation_metadata,
                    )
                    if live_usage_event is not None:
                        candidate_signature = self._live_usage_signature(live_usage_event)
                        if candidate_signature != live_usage_signature:
                            live_usage_signature = candidate_signature
                            published_event_cursor += 1
                            yield live_usage_event

                if self._event_handler.is_checkpoint_relevant_event(update_type):
                    checkpoint_dirty = True
                    live_runtime_projection_dirty = True

                if (
                    live_runtime_projection_dirty
                    and not state.had_error
                    and not state.finished
                    and (state.has_stream_output() or bool(state.current_step))
                ):
                    now_mono = perf_counter()
                    if (now_mono - last_live_runtime_projection_mono) >= live_runtime_projection_interval_seconds:
                        if self._should_persist_live_runtime_projection(
                            state=state,
                            last_signature=last_live_runtime_projection_signature,
                            last_text_len=last_live_runtime_projection_text_len,
                        ):
                            await self._persist_live_runtime_projection(
                                conversation_id=conversation_id,
                                user_message_id=user_message_id,
                                state=state,
                                assistant_message_id=persisted_assistant_message_id,
                                stream_event_id=published_event_cursor,
                            )
                            last_live_runtime_projection_signature = self._persistence_signature(state)
                            last_live_runtime_projection_text_len = len(state.full_response)
                            live_runtime_projection_dirty = False
                            last_live_runtime_projection_mono = now_mono

                if (
                    checkpoint_dirty
                    and not state.had_error
                    and not state.finished
                    and state.has_stream_output()
                ):
                    now_mono = perf_counter()
                    if (now_mono - last_checkpoint_mono) >= checkpoint_interval_seconds:
                        try:
                            current_signature = self._persistence_signature(state)
                            text_growth = len(state.full_response) - last_checkpoint_text_len
                            if current_signature != last_checkpoint_signature or text_growth >= checkpoint_char_threshold:
                                persisted_assistant_message_id = await self._checkpoint_partial_state(
                                    conversation_id=conversation_id,
                                    user_message_id=user_message_id,
                                    state=state,
                                    usage_calculator=usage_calculator,
                                    provider_name=attempt_provider,
                                    effective_model=attempt_model,
                                    start_time=start_time,
                                    assistant_message_id=persisted_assistant_message_id,
                                    checkpoint_stream_event_id=published_event_cursor,
                                )
                                last_checkpoint_signature = current_signature
                                last_checkpoint_text_len = len(state.full_response)
                                checkpoint_dirty = False
                                last_checkpoint_mono = now_mono

                                # Re-emit usage immediately after checkpoint so reconnects
                                # that resume from checkpoint_stream_event_id still receive a fresh
                                # memory snapshot without waiting for a new tool/raw event.
                                # Skip when token counting API is active — it provides accurate
                                # values; provider-derived usage would revert to stale highs.
                                if state.live_input_tokens <= 0:
                                    checkpoint_live_usage_event = self._build_live_conversation_usage_event(
                                        state=state,
                                        usage_calculator=usage_calculator,
                                        provider_name=attempt_provider,
                                        fallback_model=attempt_model,
                                        base_conversation_metadata=base_conversation_metadata,
                                    )
                                    if checkpoint_live_usage_event is not None:
                                        live_usage_signature = self._live_usage_signature(checkpoint_live_usage_event)
                                        published_event_cursor += 1
                                        yield checkpoint_live_usage_event
                        except Exception:
                            log_event(
                                logger,
                                "WARNING",
                                "chat.stream.checkpoint_failed",
                                "retry",
                                conversation_id=conversation_id,
                                user_message_id=user_message_id,
                                exc_info=True,
                            )

                if state.had_error or state.finished:
                    break

            if state.had_error:
                await self._finalize_if_stream_output(
                    **_finalize_base_kwargs(),
                    message_status="failed",
                    include_done_chunk=False,
                    update_user_message_status=not is_resume,
                    warning_event_name="chat.stream.persist_failed_state_failed",
                    fallback_user_message_status=None if is_resume else "failed",
                )
                return

            if state.awaiting_user_input:
                paused_payload = state.pending_input_payload or {}
                pending_requests = paused_payload.get("pendingRequests")
                if not isinstance(pending_requests, list):
                    pending_requests = []

                assistant_message_id, done_events = await self._finalize_state(
                    **_finalize_base_kwargs(),
                    message_status="awaiting_input",
                    include_done_chunk=True,
                    done_pending_requests=pending_requests,
                )
                persisted_assistant_message_id = assistant_message_id
                for done_event in done_events:
                    yield done_event
                return

            assistant_message_id, done_events = await self._finalize_state(
                **_finalize_base_kwargs(),
                update_user_message_status=not is_resume,
                assistant_created_at=queued_turn_handoff_created_at,
            )
            persisted_assistant_message_id = assistant_message_id

            # Analytics-only background task; does not impact user response path.
            self._enqueue_sector_classification(conversation_id)
            # Signal completion immediately to minimize perceived latency
            for done_event in done_events:
                yield done_event

            # Follow-up suggestions are generated on-demand via a separate API
            # when the user clicks the button in the UI. We intentionally do not
            # auto-generate suggestions here to save cost.

        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):  # type: ignore[arg-type]
            self._log_cancellation(
                state=state,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                provider_name=active_provider,
                start_time=start_time,
            )
            if state:
                _, done_events = await self._finalize_if_stream_output(
                    **_finalize_base_kwargs(),
                    message_status="cancelled",
                    update_user_message_status=not is_resume,
                    warning_event_name="chat.stream.persist_cancelled_state_failed",
                    fallback_user_message_status=None if is_resume else "cancelled",
                )
                for done_event in done_events:
                    yield done_event
        except Exception as exc:
            # Log the error for debugging
            log_event(
                logger,
                "ERROR",
                "chat.stream.failed",
                "error",
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                provider=active_provider,
                had_output=state.has_stream_output() if state else False,
                exc_info=True,
            )
            # Save partial message if we have any output (same as cancellation behavior)
            if state:
                _, done_events = await self._finalize_if_stream_output(
                    **_finalize_base_kwargs(),
                    message_status="failed",
                    update_user_message_status=not is_resume,
                    warning_event_name="chat.stream.persist_failed_state_unhandled",
                    fallback_user_message_status=None if is_resume else "failed",
                )
                for done_event in done_events:
                    yield done_event
            else:
                # No output to save, just mark user message as failed
                if not is_resume:
                    await self._mark_message_status(user_message_id, "failed")

            # Check if this is a context limit error and provide user-friendly guidance
            error_msg = str(exc).lower()
            if any(keyword in error_msg for keyword in ["context_length", "too many tokens", "maximum context", "token limit"]):
                error_info = {
                    "message": "This conversation exceeded the model context limit. Please retry and we will compact context automatically during long runs.",
                    "code": "CONTEXT_LIMIT_EXCEEDED"
                }
            else:
                error_info = {"message": "Generation failed. Please try regenerating.", "code": "GENERATION_ERROR"}
            yield {"type": "error", "data": error_info}

    async def _cache_input_snapshot_if_present(
        self,
        *,
        conversation_id: str,
        update: Dict[str, Any],
    ) -> None:
        """Cache per-turn snapshot updates for follow-up continuity."""
        if str(update.get("type") or "") != "input_items_snapshot":
            return
        snapshot_items = update.get("content")
        if not isinstance(snapshot_items, list) or not snapshot_items:
            return
        try:
            await set_cached_input_items(conversation_id, snapshot_items)
            log_event(
                logger,
                "INFO",
                "chat.stream.input_snapshot_cached",
                "timing",
                conversation_id=conversation_id,
                item_count=len(snapshot_items),
            )
        except Exception:
            # Cache write is best-effort; stream output must continue.
            log_event(
                logger,
                "WARNING",
                "chat.stream.input_snapshot_cache_write_failed",
                "retry",
                conversation_id=conversation_id,
                item_count=len(snapshot_items),
                exc_info=True,
            )

    def _log_cancellation(
        self,
        *,
        state: StreamState,
        conversation_id: str,
        user_message_id: str,
        provider_name: str,
        start_time: datetime,
    ) -> None:
        if not logger.isEnabledFor(logging.INFO):
            return
        elapsed_seconds = self._get_elapsed_seconds(start_time)
        try:
            log_event(
                logger,
                "INFO",
                "chat.stream.cancelled_by_client",
                "timing",
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                provider=provider_name,
                elapsed_seconds=elapsed_seconds,
                tools_open=list(state.open_tool_idx_by_call_id.keys()),
                partial_response=bool(state.full_response.strip()),
            )
        except Exception:
            pass

    @staticmethod
    def _get_elapsed_seconds(start_time: datetime) -> Optional[float]:
        try:
            return (datetime.now(timezone.utc) - start_time).total_seconds()
        except Exception:
            return None

    # Removed: automatic suggestion generation methods. Suggestions are now
    # generated on-demand via the REST endpoint when the user requests them.

    @staticmethod
    async def _stream_with_timeout(stream_iterator, timeout_seconds: int):
        """Wrap an async iterator with a timeout that resets on each yielded item.

        If no update is received within timeout_seconds, raises asyncio.TimeoutError.
        This detects stuck streams where the provider connection has hung.
        """
        async def _get_next(iterator):
            """Helper to get next item from iterator."""
            return await iterator.__anext__()

        iterator = stream_iterator.__aiter__()

        if timeout_seconds <= 0:
            async for update in iterator:
                yield update
            return

        while True:
            try:
                # Wait for next update with timeout
                update = await asyncio.wait_for(
                    _get_next(iterator),
                    timeout=timeout_seconds
                )
                yield update
            except StopAsyncIteration:
                # Normal stream completion
                break
            except asyncio.TimeoutError:
                # Stream stuck - no updates for timeout_seconds
                log_event(
                    logger,
                    "ERROR",
                    "chat.stream.timeout",
                    "error",
                    timeout_seconds=timeout_seconds,
                )
                raise
