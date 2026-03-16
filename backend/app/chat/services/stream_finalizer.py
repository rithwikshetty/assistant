"""Service for finalizing chat streams into canonical conversation events."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from ...config.settings import settings
from ...database.models import (
    ChatRun,
    Conversation,
    ConversationState,
    Message,
)
from ...logging import log_event
from ...services.admin import analytics_event_recorder
from ...services.provider_costs import compute_message_cost
from .assistant_turn_persistence import AssistantTurnPersistenceService
from .payload_cleaner import strip_nul_bytes
from .run_activity_service import (
    build_run_activity_items_from_stream_state,
    sync_run_activity_items,
)
from .run_snapshot_service import (
    _normalize_pending_requests as normalize_pending_requests,
    clear_run_snapshot,
    upsert_run_snapshot,
)
from ..streaming_support import FinalizationOptions, StreamState
from ..usage_calculator import DEFAULT_CONTEXT_WINDOW, RawUsageSummary, UsageCalculator

logger = logging.getLogger(__name__)

# Keep milestone event names discoverable for logging-contract tests.
_CHAT_MILESTONE_EVENTS = ("chat.finalized",)


class StreamFinalizer:
    """Persist stream outcomes to the event store and run lifecycle tables."""

    def __init__(
        self,
        *,
        persistence: Optional[AssistantTurnPersistenceService] = None,
    ) -> None:
        self._persistence = persistence or AssistantTurnPersistenceService()

    @staticmethod
    def _strip_nul_bytes(value: Any) -> Any:
        return strip_nul_bytes(value)

    def finalize_response(
        self,
        *,
        db: Session,
        conversation_id: str,
        user_message_id: str,
        state: StreamState,
        usage_calculator: UsageCalculator,
        provider_name: str,
        effective_model: str,
        start_time: datetime,
        cancelled: bool,
        opts: Optional[FinalizationOptions] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Finalize one stream segment and return (assistant_message_id, done_events)."""
        if opts is None:
            opts = FinalizationOptions()

        assistant_message_id = opts.assistant_message_id or str(uuid4())
        working_state = self._build_checkpoint_state(state) if opts.checkpoint_mode else state
        self._flush_thinking_blocks(working_state)

        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conversation is None:
            raise ValueError("Conversation not found")

        run = self._load_latest_run(
            db=db,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
        )
        message_status, run_status = self._normalize_status_values(opts.message_status)

        now = datetime.now(timezone.utc)
        self._apply_run_status(
            run=run,
            run_status=run_status,
            checkpoint_mode=opts.checkpoint_mode,
            now=now,
        )

        elapsed_seconds = self._get_elapsed_seconds(start_time)
        response_latency_ms = self._to_latency_ms(elapsed_seconds)

        summary, usage_payload, conversation_usage_payload, model_for_context, message_cost_decimal = self._compute_usage_and_cost(
            conversation=conversation,
            usage_calculator=usage_calculator,
            provider_name=provider_name,
            effective_model=effective_model,
            working_state=working_state,
            checkpoint_mode=opts.checkpoint_mode,
        )
        is_final_message = run_status in {"completed", "failed", "cancelled"}
        assistant_payload = self._build_assistant_payload(
            state=working_state,
            run_status=run_status,
            provider_name=provider_name,
            model_for_context=model_for_context,
            response_latency_ms=response_latency_ms,
            cancelled=cancelled,
            message_cost_decimal=message_cost_decimal,
            checkpoint_mode=opts.checkpoint_mode,
        )

        assistant_message: Optional[Message] = None
        if not opts.checkpoint_mode:
            assistant_message = self._upsert_assistant_message(
                db=db,
                conversation_id=conversation_id,
                run_id=run.id if run is not None else None,
                assistant_message_id=assistant_message_id,
                update_existing=opts.update_existing,
                payload=assistant_payload,
                status=message_status,
                completed=is_final_message,
                created_at=opts.assistant_created_at,
            )
            assistant_message_id = str(assistant_message.id)

            self._persist_assistant_turn(
                db=db,
                message=assistant_message,
                run_id=run.id if run is not None else None,
                tool_markers=working_state.tool_markers,
                run_status=run_status,
                checkpoint_mode=opts.checkpoint_mode,
                usage_payload=usage_payload,
                conversation_usage_payload=conversation_usage_payload,
                run=run,
            )
        self._persist_runtime_projection(
            db=db,
            conversation_id=conversation_id,
            run=run,
            user_message_id=user_message_id,
            assistant_message_id=None if opts.checkpoint_mode else assistant_message_id,
            run_status=run_status,
            working_state=working_state,
            checkpoint_mode=opts.checkpoint_mode,
            checkpoint_stream_event_id=opts.checkpoint_stream_event_id,
            pending_requests=opts.done_pending_requests,
            conversation_usage_payload=conversation_usage_payload,
        )

        state_row = self._update_state_row(
            db=db,
            conversation_id=conversation_id,
            run=run,
            run_status=run_status,
            conversation_usage_payload=conversation_usage_payload,
            usage_calculator=usage_calculator,
            model_for_context=model_for_context,
            working_state=working_state,
            now=now,
            assistant_message_id=None if opts.checkpoint_mode else assistant_message_id,
        )

        self._update_compaction_metadata(
            conversation=conversation,
            checkpoint_mode=opts.checkpoint_mode,
            now=now,
            working_state=working_state,
        )
        self._record_compaction_activity(
            db=db,
            checkpoint_mode=opts.checkpoint_mode,
            conversation=conversation,
            working_state=working_state,
        )

        if is_final_message and assistant_message is not None:
            conversation.updated_at = now
            conversation.last_message_at = assistant_message.created_at or now

        db.commit()

        done_events = self._build_done_events(
            conversation_id=conversation_id,
            run_id=run.id if run is not None else None,
            run_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            usage_payload=usage_payload,
            conversation_usage_payload=conversation_usage_payload,
            elapsed_seconds=elapsed_seconds,
            cancelled=cancelled,
            run_status=run_status,
            include_done_chunk=opts.include_done_chunk,
            checkpoint_mode=opts.checkpoint_mode,
            message_cost_decimal=message_cost_decimal,
            pending_requests=opts.done_pending_requests,
        )

        self._log_finalized_event(
            checkpoint_mode=opts.checkpoint_mode,
            run_status=run_status,
            provider_name=provider_name,
            model_for_context=model_for_context,
            conversation_id=conversation_id,
            summary=summary,
            message_cost_decimal=message_cost_decimal,
        )

        return assistant_message_id, done_events

    @staticmethod
    def _record_compaction_activity(
        *,
        db: Session,
        checkpoint_mode: bool,
        conversation: Conversation,
        working_state: StreamState,
    ) -> None:
        if checkpoint_mode:
            return
        compaction_count = max(0, int(getattr(working_state, "compaction_count", 0) or 0))
        if compaction_count <= 0:
            return
        user_id = str(getattr(conversation, "user_id", "") or "").strip()
        conversation_id = str(getattr(conversation, "id", "") or "").strip()
        if not user_id or not conversation_id:
            return
        for _ in range(compaction_count):
            analytics_event_recorder.record_compaction(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
            )

    def _load_latest_run(
        self,
        *,
        db: Session,
        conversation_id: str,
        user_message_id: str,
    ) -> Optional[ChatRun]:
        return (
            db.query(ChatRun)
            .filter(
                ChatRun.conversation_id == conversation_id,
                ChatRun.user_message_id == user_message_id,
            )
            .order_by(ChatRun.started_at.desc(), ChatRun.id.desc())
            .first()
        )

    @staticmethod
    def _normalize_status_values(message_status: Optional[str]) -> Tuple[str, str]:
        normalized_status = str(message_status or "completed").strip().lower()
        if normalized_status in {"awaiting_input", "paused"}:
            return "awaiting_input", "paused"
        if normalized_status in {"streaming", "running", "pending"}:
            return "streaming", "running"
        return normalized_status, normalized_status

    @staticmethod
    def _apply_run_status(
        *,
        run: Optional[ChatRun],
        run_status: str,
        checkpoint_mode: bool,
        now: datetime,
    ) -> None:
        if run is None:
            return
        run.status = run_status or run.status
        if (not checkpoint_mode) and run_status in {"completed", "failed", "cancelled"}:
            run.finished_at = now

    def _compute_usage_and_cost(
        self,
        *,
        conversation: Conversation,
        usage_calculator: UsageCalculator,
        provider_name: str,
        effective_model: str,
        working_state: StreamState,
        checkpoint_mode: bool,
    ) -> Tuple[RawUsageSummary, Dict[str, Any], Dict[str, Any], str, Decimal]:
        usage_payload: Dict[str, Any] = {}
        conversation_usage_payload: Dict[str, Any] = {}
        model_for_context = effective_model
        message_cost_decimal = Decimal("0")

        from ...utils.coerce import coerce_int as _coerce_int

        if checkpoint_mode:
            summary = RawUsageSummary(
                total_input=0,
                total_output=0,
                context_input=None,
                context_output=None,
                context_total=None,
                base_input=None,
                cache_creation_input=None,
                cache_read_input=None,
                reasoning_output=None,
                saw_usage=False,
            )
            return summary, usage_payload, conversation_usage_payload, model_for_context, message_cost_decimal

        summary = usage_calculator.summarize(working_state.raw_responses, provider=provider_name)
        model_for_context = self._resolve_model_from_raw(working_state.raw_responses, effective_model)
        message_cost_decimal = compute_message_cost(
            provider=provider_name,
            model_name=model_for_context,
            base_input_tokens=summary.base_input,
            cache_creation_tokens=summary.cache_creation_input,
            cache_read_tokens=summary.cache_read_input,
            output_tokens=summary.total_output,
            effective_input_tokens=summary.total_input,
        )
        try:
            message_cost_decimal = message_cost_decimal.quantize(
                Decimal("0.000001"),
                rounding=ROUND_HALF_UP,
            )
        except Exception:
            message_cost_decimal = Decimal("0")

        if summary.saw_usage:
            context_window = self._resolve_display_context_window(
                usage_calculator=usage_calculator,
                model_name=model_for_context,
            )
            usage_payload = usage_calculator.build_usage_payload(summary, context_window)
            conversation_usage_payload, updated_meta = usage_calculator.create_conversation_usage(
                conversation.conversation_metadata,
                usage_payload,
                context_window,
            )
            if isinstance(updated_meta, dict):
                conversation.conversation_metadata = updated_meta

        # WebSocket + store=false can report zero provider usage while the
        # token counting API has an accurate live input count.
        if working_state.live_input_tokens > 0:
            context_window = self._resolve_display_context_window(
                usage_calculator=usage_calculator,
                model_name=model_for_context,
            )
            live_input = working_state.live_input_tokens
            compact_trigger = getattr(settings, "openai_compact_trigger_tokens", None)
            live_usage_payload = {
                "input_tokens": live_input,
                "output_tokens": 0,
                "total_tokens": live_input,
                "max_context_tokens": context_window,
                "remaining_context_tokens": max(0, context_window - live_input),
                "current_context_tokens": live_input,
                **({"compact_trigger_tokens": compact_trigger} if compact_trigger and compact_trigger > 0 else {}),
            }

            existing_peak = _coerce_int(conversation_usage_payload.get("peak_context_tokens"))
            if existing_peak is None:
                meta = conversation.conversation_metadata if isinstance(conversation.conversation_metadata, dict) else {}
                usage_meta = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
                existing_peak = _coerce_int(usage_meta.get("peak_context_tokens"))
            live_usage_payload["peak_context_tokens"] = max(existing_peak or 0, live_input)

            if conversation_usage_payload:
                # Keep aggregated/cumulative fields from provider-derived
                # usage while replacing only the live "current context" view.
                merged_usage = dict(conversation_usage_payload)
                merged_usage.update(live_usage_payload)
                conversation_usage_payload = merged_usage
            else:
                conversation_usage_payload = live_usage_payload

        return summary, usage_payload, conversation_usage_payload, model_for_context, message_cost_decimal

    def _build_assistant_payload(
        self,
        *,
        state: StreamState,
        run_status: str,
        provider_name: str,
        model_for_context: str,
        response_latency_ms: Optional[int],
        cancelled: bool,
        message_cost_decimal: Decimal,
        checkpoint_mode: bool,
    ) -> Dict[str, Any]:
        assistant_payload: Dict[str, Any] = {
            "text": state.full_response,
            "model_provider": provider_name,
            "model_name": model_for_context,
        }
        if response_latency_ms is not None and run_status in {"completed", "failed", "cancelled", "paused"}:
            assistant_payload["response_latency_ms"] = response_latency_ms
        if cancelled or run_status == "cancelled":
            assistant_payload["finish_reason"] = "cancelled"
        if not checkpoint_mode:
            assistant_payload["cost_usd"] = float(message_cost_decimal)
        return assistant_payload

    def _persist_assistant_turn(
        self,
        *,
        db: Session,
        message: Message,
        run_id: Optional[str],
        tool_markers: List[Dict[str, Any]],
        run_status: str,
        checkpoint_mode: bool,
        usage_payload: Dict[str, Any],
        conversation_usage_payload: Dict[str, Any],
        run: Optional[ChatRun],
    ) -> None:
        if (not checkpoint_mode) or bool(tool_markers):
            self._persist_tool_calls(
                db=db,
                message=message,
                run_id=run_id,
                tool_markers=tool_markers,
            )
        self._persist_pending_user_inputs(
            db=db,
            message=message,
            run_id=run_id,
            tool_markers=tool_markers,
            run_status=run_status,
        )
        if checkpoint_mode:
            return
        self._enqueue_outbox_event(
            db=db,
            message=message,
            run=run,
            usage_payload=usage_payload,
            conversation_usage_payload=conversation_usage_payload,
        )

    def _update_state_row(
        self,
        *,
        db: Session,
        conversation_id: str,
        run: Optional[ChatRun],
        run_status: str,
        conversation_usage_payload: Dict[str, Any],
        usage_calculator: UsageCalculator,
        model_for_context: str,
        working_state: StreamState,
        now: datetime,
        assistant_message_id: Optional[str],
    ) -> ConversationState:
        state_row = self._ensure_state_row(db=db, conversation_id=conversation_id)
        if assistant_message_id:
            state_row.last_assistant_message_id = assistant_message_id
        state_row.awaiting_user_input = run_status == "paused"
        state_row.active_run_id = run.id if (run is not None and run_status in {"running", "paused"}) else None

        if conversation_usage_payload:
            if "input_tokens" in conversation_usage_payload:
                state_row.input_tokens = conversation_usage_payload.get("input_tokens")
            if "output_tokens" in conversation_usage_payload:
                state_row.output_tokens = conversation_usage_payload.get("output_tokens")
            if "total_tokens" in conversation_usage_payload:
                state_row.total_tokens = conversation_usage_payload.get("total_tokens")
            if "max_context_tokens" in conversation_usage_payload:
                state_row.max_context_tokens = conversation_usage_payload.get("max_context_tokens")
            if "remaining_context_tokens" in conversation_usage_payload:
                state_row.remaining_context_tokens = conversation_usage_payload.get("remaining_context_tokens")
            # Preserve existing cumulative totals when the incoming payload is
            # a live/current snapshot that omits cumulative keys.
            if "cumulative_input_tokens" in conversation_usage_payload:
                state_row.cumulative_input_tokens = conversation_usage_payload.get("cumulative_input_tokens")
            if "cumulative_output_tokens" in conversation_usage_payload:
                state_row.cumulative_output_tokens = conversation_usage_payload.get("cumulative_output_tokens")
            if "cumulative_total_tokens" in conversation_usage_payload:
                state_row.cumulative_total_tokens = conversation_usage_payload.get("cumulative_total_tokens")
        elif working_state.live_input_tokens > 0:
            context_window = self._resolve_display_context_window(
                usage_calculator=usage_calculator,
                model_name=model_for_context,
            )
            state_row.input_tokens = working_state.live_input_tokens
            state_row.output_tokens = 0
            state_row.total_tokens = working_state.live_input_tokens
            state_row.max_context_tokens = context_window
            state_row.remaining_context_tokens = max(0, context_window - working_state.live_input_tokens)

        state_row.updated_at = now
        return state_row

    @staticmethod
    def _persist_runtime_projection(
        *,
        db: Session,
        conversation_id: str,
        run: Optional[ChatRun],
        user_message_id: str,
        assistant_message_id: Optional[str],
        run_status: str,
        working_state: StreamState,
        checkpoint_mode: bool,
        checkpoint_stream_event_id: Optional[int],
        pending_requests: Optional[List[Dict[str, Any]]],
        conversation_usage_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if run is not None:
            sync_run_activity_items(
                db=db,
                conversation_id=conversation_id,
                run_id=run.id,
                assistant_message_id=assistant_message_id,
                activity_items=build_run_activity_items_from_stream_state(run_id=run.id, state=working_state),
            )

        if run is not None and (checkpoint_mode or run_status in {"running", "paused"}):
            upsert_run_snapshot(
                db=db,
                conversation_id=conversation_id,
                run_id=run.id,
                run_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                status="paused" if run_status == "paused" else "running",
                seq=checkpoint_stream_event_id or 0,
                status_label=(
                    "Waiting for your input"
                    if run_status == "paused"
                    else working_state.current_step
                ),
                draft_text=working_state.full_response,
                usage=conversation_usage_payload if isinstance(conversation_usage_payload, dict) else {},
            )
            return

        clear_run_snapshot(
            db=db,
            conversation_id=conversation_id,
        )

    @staticmethod
    def _update_compaction_metadata(
        *,
        conversation: Conversation,
        checkpoint_mode: bool,
        now: datetime,
        working_state: StreamState,
    ) -> None:
        if checkpoint_mode or working_state.compaction_count <= 0:
            return
        meta = conversation.conversation_metadata
        if not isinstance(meta, dict):
            meta = {}
        existing_compaction = meta.get("compaction")
        if not isinstance(existing_compaction, dict):
            existing_compaction = {"total_compactions": 0}
        existing_compaction["total_compactions"] = (
            existing_compaction.get("total_compactions", 0) + working_state.compaction_count
        )
        existing_compaction["last_tokens_before"] = working_state.last_compaction_tokens_before
        existing_compaction["last_tokens_after"] = working_state.last_compaction_tokens_after
        existing_compaction["last_compacted_at"] = now.isoformat()
        meta["compaction"] = existing_compaction
        conversation.conversation_metadata = meta

    def _build_done_events(
        self,
        *,
        conversation_id: str,
        run_id: Optional[str],
        run_message_id: str,
        assistant_message_id: str,
        usage_payload: Dict[str, Any],
        conversation_usage_payload: Dict[str, Any],
        elapsed_seconds: Optional[float],
        cancelled: bool,
        run_status: str,
        include_done_chunk: bool,
        checkpoint_mode: bool,
        message_cost_decimal: Decimal,
        pending_requests: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        if not include_done_chunk:
            return []
        return [
            self._build_done_event(
                conversation_id=conversation_id,
                run_id=run_id,
                run_message_id=run_message_id,
                message_id=assistant_message_id,
                usage_payload=usage_payload,
                conversation_usage=conversation_usage_payload,
                elapsed_seconds=elapsed_seconds,
                cancelled=cancelled,
                status=run_status,
                message_cost=None if checkpoint_mode else message_cost_decimal,
                pending_requests=pending_requests,
            )
        ]

    @staticmethod
    def _log_finalized_event(
        *,
        checkpoint_mode: bool,
        run_status: str,
        provider_name: str,
        model_for_context: str,
        conversation_id: str,
        summary: RawUsageSummary,
        message_cost_decimal: Decimal,
    ) -> None:
        if checkpoint_mode or run_status not in {"completed", "failed", "cancelled"}:
            return
        try:
            log_event(
                logger,
                "INFO",
                "chat.stream.finalized",
                "final",
                provider=provider_name,
                model=model_for_context,
                conversation_id=conversation_id,
                input_tokens=int(summary.total_input or 0),
                output_tokens=int(summary.total_output or 0),
                cost_usd=float(message_cost_decimal),
                status=run_status,
            )
        except Exception:
            pass

    @staticmethod
    def _build_checkpoint_state(state: StreamState) -> StreamState:
        """Build a lightweight checkpoint snapshot without deep-copying large raw payloads."""
        pending_payload = None
        if isinstance(state.pending_input_payload, dict):
            pending_payload = dict(state.pending_input_payload)
        return StreamState(
            full_response=state.full_response,
            # Checkpoints skip usage/cost aggregation, so raw responses are not needed.
            raw_responses=[],
            tools_used=list(state.tools_used),
            response_ids=list(state.response_ids),
            seen_response_ids=set(state.seen_response_ids),
            tool_markers=[dict(marker) for marker in (state.tool_markers or []) if isinstance(marker, dict)],
            open_tool_idx_by_call_id=dict(state.open_tool_idx_by_call_id),
            had_error=state.had_error,
            error_payload=dict(state.error_payload) if isinstance(state.error_payload, dict) else state.error_payload,
            got_text_deltas=state.got_text_deltas,
            response_lifecycle_events=[
                dict(event) for event in (state.response_lifecycle_events or []) if isinstance(event, dict)
            ],
            latest_response_lifecycle=(
                dict(state.latest_response_lifecycle)
                if isinstance(state.latest_response_lifecycle, dict)
                else state.latest_response_lifecycle
            ),
            reasoning_summaries=[
                dict(summary) for summary in (state.reasoning_summaries or []) if isinstance(summary, dict)
            ],
            finished=state.finished,
            tool_executions=[dict(exe) for exe in (state.tool_executions or []) if isinstance(exe, dict)],
            awaiting_user_input=state.awaiting_user_input,
            pending_input_payload=pending_payload,
            current_step=state.current_step,
            thinking_seq=state.thinking_seq,
            thinking_id_by_index=dict(state.thinking_id_by_index),
            thinking_buffers=dict(state.thinking_buffers),
            thinking_open_ids=set(state.thinking_open_ids),
            thinking_title_by_id=dict(state.thinking_title_by_id),
            thinking_sequence_by_id=dict(state.thinking_sequence_by_id),
            seq_counter=state.seq_counter,
            compaction_markers=[
                dict(marker) for marker in (state.compaction_markers or []) if isinstance(marker, dict)
            ],
            seen_compaction_item_ids=set(state.seen_compaction_item_ids),
            live_input_tokens=state.live_input_tokens,
        )

    def _ensure_state_row(self, *, db: Session, conversation_id: str) -> ConversationState:
        return self._persistence.ensure_state_row(db=db, conversation_id=conversation_id)

    def _upsert_assistant_message(
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
        return self._persistence.upsert_assistant_message(
            db=db,
            conversation_id=conversation_id,
            run_id=run_id,
            assistant_message_id=assistant_message_id,
            update_existing=update_existing,
            payload=payload,
            status=status,
            completed=completed,
            created_at=created_at,
        )

    def _persist_tool_calls(
        self,
        *,
        db: Session,
        message: Message,
        run_id: Optional[str],
        tool_markers: List[Dict[str, Any]],
    ) -> None:
        self._persistence.persist_tool_calls(
            db=db,
            message=message,
            run_id=run_id,
            tool_markers=tool_markers,
        )

    def _persist_pending_user_inputs(
        self,
        *,
        db: Session,
        message: Message,
        run_id: Optional[str],
        tool_markers: List[Dict[str, Any]],
        run_status: str,
    ) -> None:
        self._persistence.persist_pending_user_inputs(
            db=db,
            message=message,
            run_id=run_id,
            tool_markers=tool_markers,
            run_status=run_status,
        )

    def _enqueue_outbox_event(
        self,
        *,
        db: Session,
        message: Message,
        run: Optional[ChatRun],
        usage_payload: Dict[str, Any],
        conversation_usage_payload: Dict[str, Any],
    ) -> None:
        self._persistence.enqueue_outbox_event(
            db=db,
            message=message,
            run=run,
            usage_payload=usage_payload,
            conversation_usage_payload=conversation_usage_payload,
        )

    @staticmethod
    def _resolve_model_from_raw(raw_responses: List[Dict[str, Any]], fallback_model: str) -> str:
        for raw in reversed(raw_responses or []):
            if not isinstance(raw, dict):
                continue
            candidate = raw.get("model")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return fallback_model

    @staticmethod
    def _resolve_display_context_window(*, usage_calculator: UsageCalculator, model_name: Optional[str]) -> int:
        actual_context_window = usage_calculator.resolve_context_window(model_name)
        try:
            if settings.display_context_window_tokens is not None:
                return int(settings.display_context_window_tokens)
        except Exception:
            pass
        return int(actual_context_window or DEFAULT_CONTEXT_WINDOW)

    @staticmethod
    def _to_latency_ms(elapsed_seconds: Optional[float]) -> Optional[int]:
        if elapsed_seconds is None:
            return None
        try:
            ms = int(max(0.0, float(elapsed_seconds)) * 1000)
            return ms if ms > 0 else None
        except Exception:
            return None

    @staticmethod
    def _normalize_pending_requests(
        pending_requests: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        canonical_requests: List[Dict[str, Any]] = []
        for entry in pending_requests or []:
            if not isinstance(entry, dict):
                continue
            canonical_requests.append(
                {
                    "call_id": entry.get("call_id") or entry.get("callId"),
                    "tool_name": entry.get("tool_name") or entry.get("toolName"),
                    "request": entry.get("request"),
                    "result": entry.get("result"),
                }
            )
        normalized_requests = normalize_pending_requests(canonical_requests)
        return [
            {
                "callId": request.get("call_id"),
                "toolName": request.get("tool_name"),
                "request": request.get("request") if isinstance(request.get("request"), dict) else {},
                "result": request.get("result") if isinstance(request.get("result"), dict) else {},
            }
            for request in normalized_requests
            if isinstance(request, dict)
        ]

    @staticmethod
    def _build_done_event(
        *,
        conversation_id: str,
        run_id: Optional[str],
        run_message_id: str,
        message_id: str,
        usage_payload: Dict[str, Any],
        conversation_usage: Dict[str, Any],
        elapsed_seconds: Optional[float],
        cancelled: bool,
        status: str,
        message_cost: Optional[Decimal],
        pending_requests: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        done_data: Dict[str, Any] = {
            "conversationId": conversation_id,
            "runId": run_id,
            "runMessageId": run_message_id,
            "assistantMessageId": message_id,
        }
        normalized_status = status.strip().lower() if isinstance(status, str) else ""
        if normalized_status == "awaiting_input":
            normalized_status = "paused"
        if normalized_status not in {"completed", "paused", "cancelled", "failed"}:
            normalized_status = "cancelled" if cancelled else "completed"

        normalized_pending_requests = StreamFinalizer._normalize_pending_requests(pending_requests)
        done_data["status"] = normalized_status
        done_data["cancelled"] = bool(cancelled or normalized_status == "cancelled")
        done_data["pendingRequests"] = normalized_pending_requests
        if usage_payload:
            done_data["usage"] = usage_payload.copy()
        if conversation_usage:
            done_data["conversationUsage"] = dict(conversation_usage)
        if elapsed_seconds is not None:
            done_data["elapsedSeconds"] = elapsed_seconds
        if message_cost is not None:
            done_data["costUsd"] = float(message_cost)
        return {"type": "done", "data": done_data}

    def _flush_thinking_blocks(self, state: StreamState) -> None:
        if not state.thinking_open_ids:
            return
        try:
            for thinking_id in list(state.thinking_open_ids):
                buffer = state.thinking_buffers.get(thinking_id, "")
                title = state.thinking_title_by_id.get(thinking_id, "Thinking")
                sequence = state.thinking_sequence_by_id.pop(thinking_id, None)
                if not isinstance(sequence, int):
                    state.seq_counter += 1
                    sequence = state.seq_counter
                state.reasoning_summaries.append(
                    {
                        "title": title,
                        "raw_text": buffer,
                        "position": len(state.full_response),
                        "id": thinking_id,
                        "sequence": sequence,
                    }
                )
        except Exception:
            pass
        state.thinking_open_ids.clear()
        state.thinking_sequence_by_id.clear()

    @staticmethod
    def _get_elapsed_seconds(start_time: datetime) -> Optional[float]:
        try:
            return (datetime.now(timezone.utc) - start_time).total_seconds()
        except Exception:
            return None
