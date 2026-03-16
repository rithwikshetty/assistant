"""Event handling for provider stream updates.

This module owns mutation of ``StreamState`` and normalized event payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..interactive_tools import step_label_for_tool
from ..streaming_support import StreamState
from ..tool_payload_sanitizer import sanitize_tool_payload_for_storage

_OPENAI_LIFECYCLE_PREFIX = "response."
_OPENAI_NON_LIFECYCLE_EVENTS: frozenset[str] = frozenset(
    {
        # Streamed text deltas are normalized to generic "response"/"content" events.
        "response.output_text.delta",
        "response.output_text.done",
        # Reasoning summary events are normalized to thinking_* updates.
        "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.done",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_part.done",
    }
)

_GENERIC_MODEL_STEP = "thinking"


def is_openai_lifecycle_event(update_type: Any) -> bool:
    if not isinstance(update_type, str):
        return False
    normalized = update_type.strip()
    if not normalized.startswith(_OPENAI_LIFECYCLE_PREFIX):
        return False
    if normalized.endswith(".delta"):
        return False
    if normalized in _OPENAI_NON_LIFECYCLE_EVENTS:
        return False
    return True


class StreamEventHandler:
    """Convert provider updates into normalized events and mutate stream state."""

    def handle(self, update: Dict[str, Any], state: StreamState) -> List[Dict[str, Any]]:
        output: List[Dict[str, Any]] = []
        update_type = update.get("type")

        if update_type in ("message", "response"):
            content = update.get("content") if update_type == "message" else update.get("delta", "")
            if content:
                state.full_response += content
                state.got_text_deltas = True
                state.current_step = "Generating response"
                output.append(
                    self._event_payload(
                        "content.delta",
                        {
                            "delta": content,
                            "statusLabel": state.current_step,
                        },
                    )
                )
            return output

        if update_type == "response_complete":
            content = update.get("content") or ""
            if content and not state.got_text_deltas:
                state.full_response += content
                state.current_step = "Generating response"
                output.append(
                    self._event_payload(
                        "content.delta",
                        {
                            "delta": content,
                            "statusLabel": state.current_step,
                        },
                    )
                )
            output.append(
                self._event_payload(
                    "content.done",
                    {
                        "text": "",
                    },
                )
            )
            return output

        if update_type == "raw_response":
            self._record_raw_response(update, state)
            return output

        if update_type == "error":
            state.had_error = True
            error_payload = update.get("content") or update.get("data") or {"message": "Generation error"}
            state.error_payload = error_payload
            state.current_step = None
            output.append(self._event_payload("run.failed", error_payload))
            state.finished = True
            return output

        if update_type == "thinking_start":
            self._handle_thinking_start(update, state)
            output.append(self._run_status_event(state))
            return output

        if update_type == "thinking_delta":
            # Keep reasoning text server-side for persistence, but do not stream
            # raw reasoning content to clients.
            self._handle_thinking_delta(update, state)
            return output

        if update_type == "thinking_end":
            self._set_model_step(state, "Thinking")
            self._handle_thinking_end(update, state)
            output.append(self._run_status_event(state))
            return output

        if update_type == "live_context_usage":
            payload = update.get("data") or update.get("content") or {}
            if not isinstance(payload, dict):
                payload = {}
            # Track latest token count on state for persistence fallback
            live_tokens = payload.get("input_tokens")
            if isinstance(live_tokens, (int, float)) and live_tokens > 0:
                state.live_input_tokens = int(live_tokens)
            return output

        if update_type == "compaction_started":
            payload = update.get("data") or update.get("content") or {}
            if not isinstance(payload, dict):
                payload = {}
            state.current_step = "Compacting context"
            try:
                state.seq_counter += 1
                state.register_compaction_start(
                    item_id=payload.get("item_id") if isinstance(payload.get("item_id"), str) else None,
                    source=payload.get("source") if isinstance(payload.get("source"), str) else None,
                    label=payload.get("label") if isinstance(payload.get("label"), str) else None,
                    position=len(state.full_response),
                    sequence=state.seq_counter,
                )
            except Exception:
                pass
            output.append(self._run_status_event(state))
            return output

        if update_type == "compaction_completed":
            payload = update.get("data") or update.get("content") or {}
            if not isinstance(payload, dict):
                payload = {}
            self._set_model_step(state, "Thinking")
            state.compaction_count += 1
            if isinstance(payload.get("tokens_before"), (int, float)):
                state.last_compaction_tokens_before = int(payload["tokens_before"])
            if isinstance(payload.get("tokens_after"), (int, float)):
                state.last_compaction_tokens_after = int(payload["tokens_after"])
            output.append(self._run_status_event(state))
            return output

        if update_type == "input_items_snapshot":
            content = update.get("content")
            if isinstance(content, list) and content:
                state.final_input_items = content
            return output

        if is_openai_lifecycle_event(update_type):
            previous_step = self._normalize_step_label(state.current_step)
            if previous_step is None or previous_step.strip().lower() in {
                "starting",
                "resuming",
                "generating response",
                _GENERIC_MODEL_STEP,
            }:
                state.current_step = "Thinking"
            lifecycle_payload = update.get("data") or update.get("content")
            try:
                event_entry: Dict[str, Any] = {
                    "type": str(update_type),
                    "receivedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
                }
                if lifecycle_payload is not None:
                    event_entry["data"] = lifecycle_payload
                state.response_lifecycle_events.append(event_entry)
                state.latest_response_lifecycle = event_entry
            except Exception:
                pass
            current_step = self._normalize_step_label(state.current_step)
            if current_step and current_step != previous_step:
                output.append(self._run_status_event(state))
            return output

        if update_type == "tool_call":
            tool_event = self._handle_tool_call(update, state)
            if tool_event is not None:
                output.append(tool_event)
            return output

        if update_type == "tool_arguments":
            tool_name = update.get("name")
            state.current_step = step_label_for_tool(tool_name)
            raw_call_id = update.get("call_id") or update.get("item_id")
            tool_arguments = update.get("content")
            try:
                state.record_tool_arguments(
                    call_id=raw_call_id,
                    name=tool_name,
                    arguments=tool_arguments,
                )
            except Exception:
                pass
            return output

        if update_type == "tool_query":
            tool_event = self._handle_tool_query(update, state)
            if tool_event is not None:
                output.append(tool_event)
            return output

        if update_type == "tool_result":
            self._set_model_step(state, "Thinking")
            tool_event = self._handle_tool_result(update, state)
            if tool_event is not None:
                output.append(tool_event)
            output.append(self._run_status_event(state))
            return output

        if update_type == "tool_error":
            self._set_model_step(state, "Thinking")
            tool_event = self._handle_tool_error(update, state)
            if tool_event is not None:
                output.append(tool_event)
            output.append(self._run_status_event(state))
            return output

        if update_type == "tool_execution_structure":
            execution_entry = {
                "assistant_blocks": update.get("assistant_blocks", []),
                "user_blocks": update.get("user_blocks", []),
            }
            state.tool_executions.append(execution_entry)
            return output

        if update_type == "await_user_input":
            payload = update.get("content") or update.get("data") or {}
            if not isinstance(payload, dict):
                payload = {}
            pending_requests = payload.get("pending_requests")
            state.pending_input_payload = {
                "pendingRequests": pending_requests if isinstance(pending_requests, list) else [],
            }
            state.awaiting_user_input = True
            state.current_step = "Waiting for your input"
            output.append(
                self._event_payload(
                    "input.requested",
                    {
                        "pendingRequests": state.pending_input_payload["pendingRequests"],
                        "statusLabel": state.current_step,
                    },
                )
            )
            state.finished = True
            return output

        if update_type == "final":
            state.current_step = None
            state.finished = True
            return output

        return output

    @staticmethod
    def is_checkpoint_relevant_event(update_type: str) -> bool:
        if not update_type:
            return False
        return update_type != "raw_response" and not is_openai_lifecycle_event(update_type)

    @staticmethod
    def is_live_usage_relevant_event(update_type: str) -> bool:
        if not update_type:
            return False
        return is_openai_lifecycle_event(update_type) or update_type in {
            "raw_response",
            "tool_call",
            "tool_result",
            "tool_error",
            "thinking_start",
            "live_context_usage",
        }

    @staticmethod
    def _event_payload(event_type: str, data: Any) -> Dict[str, Any]:
        return {"type": event_type, "data": data}

    def _run_status_event(self, state: StreamState) -> Dict[str, Any]:
        return self._event_payload("run.status", {"statusLabel": state.current_step})

    @staticmethod
    def _normalize_step_label(raw: Any) -> Optional[str]:
        if not isinstance(raw, str):
            return None
        normalized = raw.strip()
        return normalized or None

    def _set_model_step(self, state: StreamState, label: str) -> None:
        normalized_label = self._normalize_step_label(label)
        if not normalized_label:
            return

        if normalized_label.lower() == _GENERIC_MODEL_STEP:
            existing = self._normalize_step_label(state.current_step)
            if existing and existing.lower() != _GENERIC_MODEL_STEP:
                return

        state.current_step = normalized_label

    @staticmethod
    def _record_raw_response(update: Dict[str, Any], state: StreamState) -> None:
        raw_data = update.get("content")
        if isinstance(raw_data, dict):
            state.raw_responses.append(raw_data)
            resp_id_raw = raw_data.get("id")
            if resp_id_raw is not None:
                resp_id_str = str(resp_id_raw).strip()
                if resp_id_str and resp_id_str not in state.seen_response_ids:
                    state.response_ids.append(resp_id_str)
                    state.seen_response_ids.add(resp_id_str)
            for item in raw_data.get("output", []) or []:
                if isinstance(item, dict) and item.get("type") == "function_call":
                    tool_name = item.get("name")
                    if tool_name and tool_name not in state.tools_used:
                        state.tools_used.append(tool_name)
        elif raw_data is not None:
            state.raw_responses.append({"value": raw_data})

    def _handle_thinking_start(self, update: Dict[str, Any], state: StreamState) -> None:
        payload = update.get("content") or update.get("data") or {}
        block_index = None
        title = "Thinking"
        if isinstance(payload, dict):
            bi = payload.get("index")
            if isinstance(bi, int):
                block_index = bi
            maybe_title = payload.get("title")
            if isinstance(maybe_title, str) and maybe_title.strip():
                title = maybe_title.strip()
        self._set_model_step(state, title)
        state.thinking_seq += 1
        thinking_id = f"thinking_{state.thinking_seq}"
        if isinstance(block_index, int):
            state.thinking_id_by_index[block_index] = thinking_id
        state.thinking_buffers[thinking_id] = ""
        state.thinking_open_ids.add(thinking_id)
        state.seq_counter += 1
        state.thinking_sequence_by_id[thinking_id] = state.seq_counter
        state.thinking_title_by_id[thinking_id] = title
        return None

    def _handle_thinking_delta(self, update: Dict[str, Any], state: StreamState) -> None:
        payload = update.get("content") or update.get("data") or {}
        text = None
        block_index = None
        if isinstance(payload, dict):
            maybe_text = payload.get("text") or payload.get("delta")
            if isinstance(maybe_text, str):
                text = maybe_text
            bi = payload.get("index")
            if isinstance(bi, int):
                block_index = bi
        thinking_id = self._resolve_thinking_id(state, block_index)
        if thinking_id and isinstance(text, str) and text:
            state.thinking_buffers[thinking_id] = state.thinking_buffers.get(thinking_id, "") + text
        return None

    def _handle_thinking_end(self, update: Dict[str, Any], state: StreamState) -> None:
        payload = update.get("content") or update.get("data") or {}
        block_index = None
        if isinstance(payload, dict):
            bi = payload.get("index")
            if isinstance(bi, int):
                block_index = bi
        thinking_id = self._resolve_thinking_id(state, block_index)
        if thinking_id:
            buffer = state.thinking_buffers.get(thinking_id, "")
            title = state.thinking_title_by_id.get(thinking_id, "Thinking")
            sequence = state.thinking_sequence_by_id.pop(thinking_id, None)
            if not isinstance(sequence, int):
                state.seq_counter += 1
                sequence = state.seq_counter
            entry = {
                "title": title,
                "raw_text": buffer,
                "position": len(state.full_response),
                "id": thinking_id,
                "sequence": sequence,
            }
            state.reasoning_summaries.append(entry)
            state.thinking_open_ids.discard(thinking_id)
            state.thinking_title_by_id.pop(thinking_id, None)
        return None

    @staticmethod
    def _resolve_thinking_id(state: StreamState, block_index: Optional[int]) -> Optional[str]:
        thinking_id = None
        if isinstance(block_index, int):
            thinking_id = state.thinking_id_by_index.get(block_index)
        if thinking_id is None and state.thinking_open_ids:
            try:
                thinking_id = max(state.thinking_open_ids, key=lambda value: int(value.split("_")[-1]))
            except Exception:
                thinking_id = next(iter(state.thinking_open_ids))
        return thinking_id

    def _handle_tool_call(self, update: Dict[str, Any], state: StreamState) -> Optional[Dict[str, Any]]:
        tool_name = update.get("name")
        state.current_step = step_label_for_tool(tool_name)
        raw_call_id = update.get("call_id") or update.get("item_id")
        tool_arguments = update.get("arguments")
        normalized_call_id = str(raw_call_id or "").strip() or None
        try:
            state.seq_counter += 1
            normalized_call_id = state.register_tool_call(
                name=tool_name,
                call_id=raw_call_id,
                position=len(state.full_response),
                sequence=state.seq_counter,
                arguments=tool_arguments,
            )
        except Exception:
            pass
        tool_ordering = self._tool_ordering_fields(
            state,
            call_id=normalized_call_id,
            name=tool_name,
        )
        return self._event_payload(
            "tool.started",
            {
                "toolCallId": normalized_call_id,
                "toolName": tool_name,
                "arguments": tool_arguments if isinstance(tool_arguments, dict) else {},
                "statusLabel": state.current_step,
                **tool_ordering,
            },
        )

    def _handle_tool_query(self, update: Dict[str, Any], state: StreamState) -> Optional[Dict[str, Any]]:
        tool_name = update.get("name")
        state.current_step = step_label_for_tool(tool_name)
        raw_call_id = update.get("call_id") or update.get("item_id")
        query_text = update.get("content")
        normalized_call_id = str(raw_call_id or "").strip() or None
        try:
            normalized_call_id = state.record_tool_query(
                call_id=raw_call_id,
                name=tool_name,
                query=query_text,
            )
        except Exception:
            pass
        tool_ordering = self._tool_ordering_fields(
            state,
            call_id=normalized_call_id,
            name=tool_name,
        )
        return self._event_payload(
            "tool.progress",
            {
                "toolCallId": normalized_call_id,
                "toolName": tool_name,
                "query": query_text if isinstance(query_text, str) else None,
                "statusLabel": state.current_step,
                **tool_ordering,
            },
        )

    def _handle_tool_result(self, update: Dict[str, Any], state: StreamState) -> Optional[Dict[str, Any]]:
        tool_name = update.get("name")
        raw_call_id = update.get("call_id") or update.get("item_id")
        result_payload = update.get("content")
        stored_payload = sanitize_tool_payload_for_storage(str(tool_name or ""), result_payload)
        normalized_call_id = str(raw_call_id or "").strip() or None
        try:
            normalized_call_id = state.record_tool_result(
                call_id=raw_call_id,
                name=tool_name,
                payload=stored_payload,
            )
        except Exception:
            pass
        tool_ordering = self._tool_ordering_fields(
            state,
            call_id=normalized_call_id,
            name=tool_name,
        )
        return self._event_payload(
            "tool.completed",
            {
                "toolCallId": normalized_call_id,
                "toolName": tool_name,
                "result": stored_payload if isinstance(stored_payload, dict) else {},
                **tool_ordering,
            },
        )

    def _handle_tool_error(self, update: Dict[str, Any], state: StreamState) -> Optional[Dict[str, Any]]:
        tool_name = update.get("name")
        raw_call_id = update.get("call_id") or update.get("item_id")
        error_payload = update.get("content")
        stored_error_payload = sanitize_tool_payload_for_storage(str(tool_name or ""), error_payload)
        normalized_call_id = str(raw_call_id or "").strip() or None
        try:
            normalized_call_id = state.record_tool_error(
                call_id=raw_call_id,
                name=tool_name,
                payload=stored_error_payload,
            )
        except Exception:
            pass
        tool_ordering = self._tool_ordering_fields(
            state,
            call_id=normalized_call_id,
            name=tool_name,
        )
        return self._event_payload(
            "tool.failed",
            {
                "toolCallId": normalized_call_id,
                "toolName": tool_name,
                "error": stored_error_payload if isinstance(stored_error_payload, dict) else {},
                **tool_ordering,
            },
        )

    @staticmethod
    def _tool_ordering_fields(
        state: StreamState,
        *,
        call_id: Optional[str],
        name: Optional[str],
    ) -> Dict[str, Any]:
        marker = state.get_tool_marker(call_id=call_id, name=name)
        if not isinstance(marker, dict):
            return {}

        payload: Dict[str, Any] = {}
        position = marker.get("position") if "position" in marker else marker.get("pos")
        if isinstance(position, (int, float)):
            payload["position"] = max(0, int(position))

        sequence = marker.get("sequence") if "sequence" in marker else marker.get("seq")
        if isinstance(sequence, (int, float)):
            payload["sequence"] = max(0, int(sequence))

        return payload


__all__ = ["is_openai_lifecycle_event", "StreamEventHandler"]
