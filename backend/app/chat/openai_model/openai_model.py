from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

import aiohttp

from ...config.settings import settings
from ...config.database import AsyncSessionLocal
from ...logging import log_event
from ..services.queued_turn_handoff_service import peek_queued_turn_handoff
from ..tool_definitions import get_openai_tool_specs
from ..toolkit import execute_tool
from .input_builder import (
    build_input_from_history as _build_input_from_history,
    build_pre_compaction_summary as _build_pre_compaction_summary,
    build_user_input_item as _build_user_input_item,
    clean_output_for_input as _clean_output_for_input,
    coerce_system_instructions as _coerce_system_instructions,
    strip_session_context_messages as _strip_session_context_messages,
)
from .reasoning import (
    extract_reasoning_replay_items as _extract_reasoning_replay_items,
    extract_reasoning_summary_part_text as _extract_reasoning_summary_part_text,
    extract_reasoning_title as _extract_reasoning_title,
    extract_text_from_response_payload as _extract_text_from_response_payload,
    merge_reasoning_summary_text as _merge_reasoning_summary_text,
)
from .tool_loop import execute_openai_tool_loop_turn
from .transport import (
    compact_openai_input as _compact_openai_input,
    count_openai_input_tokens as _count_openai_input_tokens,
    normalize_provider_name as _normalize_provider_name,
    open_openai_responses_websocket as _open_openai_responses_websocket,
    stream_openai_ws_turn as _stream_openai_ws_turn,
)
from .turn_processor import OpenAIStreamTurnProcessor


logger = logging.getLogger(__name__)
_REASONING_INCLUDE_FIELDS: tuple[str, ...] = ("reasoning.encrypted_content",)
_VALID_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh"}


async def chat_stream(
    query: str | List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    system_prompt: Optional[Any] = None,
    model: str = "gpt-5.4",
    reasoning_effort: Optional[str] = None,
    tool_context: Optional[Dict[str, Any]] = None,
    context_prefix: Optional[str] = None,
    resume_continuation: Optional[List[Dict[str, Any]]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Streaming chat implementation for OpenAI using the Responses API.

    Uses stateless input-array chaining: full input_items are sent every turn,
    with explicit token counting and compaction via the /responses/compact
    endpoint when context grows beyond the trigger threshold.

    Emits provider/runtime updates consumed server-side by ChatStreamingManager:
    - streamed text / reasoning / tool / compaction updates that mutate StreamState
    - {type: "response.*", data: {...}} lifecycle events for server-side usage tracking
    - {type: "live_context_usage", data: {...}} token count before each turn
    - {type: "error"} on failures
    - {type: "final"} when the tool loop is complete

    Public client transport no longer mirrors those provider-detail events directly.
    ChatStreamingManager projects them into coarse runtime updates plus terminal events.
    """

    tool_context = tool_context or {}
    provider_name = _normalize_provider_name(tool_context.get("provider"))
    conversation_id = str(tool_context.get("conversation_id") or "").strip() or None
    active_run_id = str(tool_context.get("active_run_id") or "").strip() or None

    use_openai_websocket = True
    ws_session: Optional[aiohttp.ClientSession] = None
    ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None

    # Guard: ensure transport and credentials are available.
    try:
        ws_session, ws_connection = await _open_openai_responses_websocket()
    except Exception as exc:
        yield {
            "type": "error",
            "content": {
                "message": str(exc),
                "code": "OPENAI_NOT_CONFIGURED",
                "provider": provider_name,
                "model": model,
            },
        }
        yield {"type": "final"}
        return

    # Resolve tool visibility from context
    include_project_tools = bool(tool_context.get("project_id"))
    is_admin = bool(tool_context.get("is_admin"))
    # Build OpenAI-style function tools if not provided explicitly
    if tools is None:
        try:
            tools = get_openai_tool_specs(
                include_project_tools=include_project_tools,
                is_admin=is_admin,
            )
        except Exception:
            tools = []

    stored_input_items = tool_context.get("stored_input_items")
    if resume_continuation and isinstance(resume_continuation, list):
        # Resume a paused tool loop from the latest persisted history.
        # Do not start from stored snapshot items here: those can be from
        # an earlier completed turn and may omit the current paused turn's
        # user prompt/context.
        input_items = _build_input_from_history(conversation_history, "", context_prefix)
        input_items.extend(resume_continuation)
    elif stored_input_items and isinstance(stored_input_items, list):
        input_items = list(stored_input_items)
        user_item = _build_user_input_item(query, context_prefix)
        if user_item is not None:
            input_items.append(user_item)
    else:
        input_items = _build_input_from_history(conversation_history, query, context_prefix)
    instructions = _coerce_system_instructions(system_prompt)

    normalized_reasoning_effort = str(
        reasoning_effort or getattr(settings, "chat_reasoning_effort", "medium") or "medium"
    ).strip().lower()
    if normalized_reasoning_effort not in _VALID_REASONING_EFFORTS:
        normalized_reasoning_effort = str(getattr(settings, "chat_reasoning_effort", "medium") or "medium").strip().lower()
    if normalized_reasoning_effort not in _VALID_REASONING_EFFORTS:
        normalized_reasoning_effort = "medium"

    reasoning_config: Dict[str, Any] = {
        "effort": normalized_reasoning_effort,
        "summary": "auto",
    }

    # Text verbosity: keep responses compact by default.
    text_config: Dict[str, Any] = {
        "verbosity": "low",
    }

    effective_model = model

    # Compact trigger threshold from tool_context (set by stream_attempt_builder)
    compact_trigger_threshold: int = 0
    raw_compact_trigger = tool_context.get("openai_compact_trigger_tokens")
    if isinstance(raw_compact_trigger, (int, float)) and raw_compact_trigger > 0:
        compact_trigger_threshold = int(raw_compact_trigger)

    _seen_uncaptured_event_types: Set[str] = set()

    try:
        # Tool loop: continue until the model no longer issues tool calls.
        while True:
            # ── Token counting & explicit compaction (OpenAI WebSocket path) ──
            if use_openai_websocket and compact_trigger_threshold > 0:
                try:
                    tokens = await _count_openai_input_tokens(
                        effective_model, input_items, instructions, tools,
                    )
                    log_event(
                        logger,
                        "INFO",
                        "chat.stream.token_count",
                        "timing",
                        model=effective_model,
                        input_tokens=tokens,
                        input_items=len(input_items),
                        compact_trigger_threshold=compact_trigger_threshold,
                    )
                    # Emit live token count for the frontend header badge
                    yield {
                        "type": "live_context_usage",
                        "data": {"input_tokens": tokens},
                    }

                    if tokens > compact_trigger_threshold:
                        log_event(
                            logger,
                            "INFO",
                            "chat.stream.compaction_triggered",
                            "timing",
                            model=effective_model,
                            input_tokens=tokens,
                            input_items_before=len(input_items),
                            compact_trigger_threshold=compact_trigger_threshold,
                        )
                        yield {
                            "type": "compaction_started",
                            "data": {"source": "explicit_compact", "input_tokens": tokens},
                        }
                        # Inject a session state summary before compacting.
                        # Compaction preserves user messages but compresses
                        # tool calls/outputs into an opaque blob.  The summary
                        # gives the model explicit awareness of prior actions
                        # so it avoids redundant tool calls after compaction.
                        input_items = _strip_session_context_messages(input_items)
                        pre_compact_summary = _build_pre_compaction_summary(input_items)
                        if pre_compact_summary is not None:
                            input_items.append(pre_compact_summary)
                        compact_output, compact_usage = await _compact_openai_input(
                            effective_model, input_items, instructions,
                        )
                        items_before = len(input_items)
                        input_items = _clean_output_for_input(compact_output)
                        # Re-count tokens after compaction so the frontend
                        # header immediately reflects the reduced context size.
                        post_compact_tokens = await _count_openai_input_tokens(
                            effective_model, input_items, instructions, tools,
                        )
                        log_event(
                            logger,
                            "INFO",
                            "chat.stream.compaction_completed",
                            "timing",
                            model=effective_model,
                            items_before=items_before,
                            items_after=len(input_items),
                            tokens_before=tokens,
                            tokens_after=post_compact_tokens,
                            compact_input_tokens=compact_usage.get("input_tokens", 0),
                            compact_output_tokens=compact_usage.get("output_tokens", 0),
                        )
                        yield {
                            "type": "compaction_completed",
                            "data": {
                                "source": "explicit_compact",
                                "tokens_before": tokens,
                                "tokens_after": post_compact_tokens,
                                "items_before": items_before,
                                "items_after": len(input_items),
                                "compact_input_tokens": compact_usage.get("input_tokens", 0),
                                "compact_output_tokens": compact_usage.get("output_tokens", 0),
                            },
                        }
                        # Emit updated token count so the frontend badge drops
                        yield {
                            "type": "live_context_usage",
                            "data": {"input_tokens": post_compact_tokens},
                        }
                except Exception:
                    log_event(
                        logger,
                        "WARNING",
                        "chat.stream.compaction_failed",
                        "retry",
                        model=effective_model,
                        input_items=len(input_items),
                        exc_info=True,
                    )
                    # Token counting or compaction failed — proceed with
                    # current input_items; the model may still succeed.

            stream_iter: Any
            try:
                if use_openai_websocket:
                    if ws_connection is None:
                        raise RuntimeError("OpenAI websocket connection is not available")
                    ws_payload: Dict[str, Any] = {
                        "type": "response.create",
                        "model": effective_model,
                        "store": False,
                        "input": input_items,
                        "tools": tools or [],
                        "include": list(_REASONING_INCLUDE_FIELDS),
                        "reasoning": reasoning_config,
                        "text": text_config,
                        "tool_choice": "auto",
                        "parallel_tool_calls": True,
                    }
                    if instructions:
                        ws_payload["instructions"] = instructions
                    stream_iter = _stream_openai_ws_turn(ws=ws_connection, payload=ws_payload)
            except Exception as exc:
                yield {
                    "type": "error",
                    "content": {
                        "message": f"OpenAI chat error: {exc}",
                        "code": "OPENAI_STREAM_FAILED",
                        "provider": provider_name,
                        "model": model,
                    },
                }
                yield {"type": "final"}
                return

            # Stream events from OpenAI and translate into generic updates
            processor = OpenAIStreamTurnProcessor(
                provider_name=provider_name,
                model=model,
                logger=logger,
                use_openai_websocket=use_openai_websocket,
                seen_uncaptured_event_types=_seen_uncaptured_event_types,
                extract_text_from_response_payload=_extract_text_from_response_payload,
                extract_reasoning_replay_items=_extract_reasoning_replay_items,
                extract_reasoning_summary_part_text=_extract_reasoning_summary_part_text,
                merge_reasoning_summary_text=_merge_reasoning_summary_text,
                extract_reasoning_title=_extract_reasoning_title,
            )

            try:
                async for event in stream_iter:
                    if use_openai_websocket:
                        data = event if isinstance(event, dict) else {}
                    else:
                        # All stream events are Pydantic models; convert to dict
                        try:
                            data = event.model_dump()
                        except Exception:
                            # Fallback: try generic dict conversion
                            data = getattr(event, "__dict__", {}) or {}

                    decision = processor.process_event(data)
                    for emitted_event in decision.emitted_events:
                        yield emitted_event
                    if decision.terminate_stream:
                        return
                    if decision.break_turn:
                        break
            except Exception as exc:
                if use_openai_websocket:
                    if processor.turn_emitted_visible_output:
                        yield {
                            "type": "error",
                            "content": {
                                "message": "Streaming connection dropped after partial output; please retry.",
                                "code": "OPENAI_STREAM_EXCEPTION",
                            },
                        }
                        yield {"type": "final"}
                        return
                    processor.reconnect_websocket = True
                    processor.retry_with_full_context = True
                else:
                    yield {
                        "type": "error",
                        "content": {
                            "message": f"OpenAI streaming exception: {exc}",
                            "code": "OPENAI_STREAM_EXCEPTION",
                        },
                    }
                    yield {"type": "final"}
                    return

            reconnect_websocket = processor.reconnect_websocket
            retry_with_full_context = processor.retry_with_full_context
            tool_calls = processor.tool_calls
            turn_text_chunks = processor.turn_text_chunks
            response_payload = processor.latest_response_payload

            if reconnect_websocket:
                with suppress(Exception):
                    if ws_connection is not None:
                        await ws_connection.close()
                with suppress(Exception):
                    if ws_session is not None:
                        await ws_session.close()
                ws_session = None
                ws_connection = None
                try:
                    ws_session, ws_connection = await _open_openai_responses_websocket()
                except Exception as exc:
                    yield {
                        "type": "error",
                        "content": {
                            "message": f"OpenAI websocket reconnect failed: {exc}",
                            "code": "OPENAI_STREAM_EXCEPTION",
                        },
                    }
                    yield {"type": "final"}
                    return

            if retry_with_full_context:
                # Retry with full context — input_items already has everything
                continue

            # ── Append cleaned response output to input_items ──
            if isinstance(response_payload, dict):
                output_items = response_payload.get("output") or []
                if isinstance(output_items, list) and output_items:
                    cleaned_output = _clean_output_for_input(output_items)
                    input_items.extend(cleaned_output)

            # If we have tool calls, execute them and feed outputs back into the model
            if tool_calls:
                tool_turn = await execute_openai_tool_loop_turn(
                    tool_calls=tool_calls,
                    tool_context=tool_context,
                    execute_tool_fn=execute_tool,
                )

                for emitted_event in tool_turn.emitted_events:
                    yield emitted_event

                if tool_turn.await_user_input_event is not None:
                    yield tool_turn.await_user_input_event
                    return

                if tool_turn.tool_execution_structure is not None:
                    yield tool_turn.tool_execution_structure

                if conversation_id and active_run_id:
                    try:
                        async with AsyncSessionLocal() as handoff_db:
                            queued_turn_handoff = await peek_queued_turn_handoff(
                                db=handoff_db,
                                conversation_id=conversation_id,
                                blocked_by_run_id=active_run_id,
                            )
                    except Exception:
                        queued_turn_handoff = None
                        log_event(
                            logger,
                            "WARNING",
                            "chat.queue.handoff_probe_failed",
                            "retry",
                            conversation_id=conversation_id,
                            run_id=active_run_id,
                            exc_info=True,
                        )
                    if queued_turn_handoff is not None:
                        created_at = queued_turn_handoff.created_at
                        yield {
                            "type": "queued_turn_handoff",
                            "data": {
                                "run_id": queued_turn_handoff.run_id,
                                "user_message_id": queued_turn_handoff.user_message_id,
                                "created_at": created_at.isoformat() if created_at is not None else None,
                            },
                        }
                        return

                # Append function_call_output items from tool execution
                input_items.extend(tool_turn.next_items)

                # Loop again to let the model produce the final assistant message.
                continue

            # No tool calls – we are done.
            # Refresh token count after appending this assistant output.
            # Without this, no-tool turns can leave the header stuck at the
            # pre-turn count until a later tool-loop turn happens.
            if use_openai_websocket and compact_trigger_threshold > 0:
                try:
                    final_tokens = await _count_openai_input_tokens(
                        effective_model,
                        input_items,
                        instructions,
                        tools,
                    )
                    if isinstance(final_tokens, (int, float)) and final_tokens > 0:
                        yield {
                            "type": "live_context_usage",
                            "data": {"input_tokens": int(final_tokens)},
                        }
                except Exception:
                    log_event(
                        logger,
                        "WARNING",
                        "chat.stream.final_token_count_failed",
                        "retry",
                        model=effective_model,
                        input_items=len(input_items),
                        exc_info=True,
                    )
            # Persist the full stateless input chain after each completed turn.
            # This preserves monotonic context continuity across follow-up turns
            # until compaction intentionally reduces it.
            yield {"type": "input_items_snapshot", "content": input_items}
            yield {"type": "final", "content": "FINAL ANSWER PROVIDED"}
            return
    finally:
        with suppress(Exception):
            if ws_connection is not None:
                await ws_connection.close()
        with suppress(Exception):
            if ws_session is not None:
                await ws_session.close()
