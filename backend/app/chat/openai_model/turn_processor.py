"""Per-turn event processing for OpenAI Responses streaming.

This module isolates event routing/state updates from the top-level provider
orchestration logic in ``openai_model.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ...logging import log_event


@dataclass
class StreamTurnDecision:
    """Decision returned after handling one stream event."""

    emitted_events: List[Dict[str, Any]] = field(default_factory=list)
    break_turn: bool = False
    terminate_stream: bool = False


class OpenAIStreamTurnProcessor:
    """Stateful handler for one model turn's stream events."""

    def __init__(
        self,
        *,
        provider_name: str,
        model: str,
        logger,
        use_openai_websocket: bool,
        seen_uncaptured_event_types: Set[str],
        extract_text_from_response_payload,
        extract_reasoning_replay_items,
        extract_reasoning_summary_part_text,
        merge_reasoning_summary_text,
        extract_reasoning_title,
    ) -> None:
        self.provider_name = provider_name
        self.model = model
        self.logger = logger
        self.use_openai_websocket = use_openai_websocket
        self._seen_uncaptured_event_types = seen_uncaptured_event_types

        self._extract_text_from_response_payload = extract_text_from_response_payload
        self._extract_reasoning_replay_items = extract_reasoning_replay_items
        self._extract_reasoning_summary_part_text = extract_reasoning_summary_part_text
        self._merge_reasoning_summary_text = merge_reasoning_summary_text
        self._extract_reasoning_title = extract_reasoning_title

        self.tool_calls: List[Dict[str, Any]] = []
        self.seen_tool_call_ids: Set[str] = set()
        self.reasoning_summaries: Dict[str, str] = {}
        self.thinking_started: Set[str] = set()
        self.thinking_finished: Set[str] = set()
        self.turn_text_chunks: List[str] = []

        self.latest_response_id: Optional[str] = None
        self.latest_response_reasoning_items: List[Dict[str, Any]] = []
        self.latest_response_payload: Optional[Dict[str, Any]] = None

        self.retry_with_full_context = False
        self.reconnect_websocket = False
        self.turn_emitted_visible_output = False
        self.last_stream_event_monotonic: Optional[float] = None
        self.last_stream_event_type: Optional[str] = None

        self._handlers: Dict[str, Callable[[Dict[str, Any]], StreamTurnDecision]] = {
            "response.output_text.delta": self._handle_output_text_delta,
            "response.output_text.done": self._handle_output_text_done,
            "response.reasoning_summary_text.delta": self._handle_reasoning_text_delta,
            "response.reasoning_summary_part.added": self._handle_reasoning_part_event,
            "response.reasoning_summary_part.done": self._handle_reasoning_part_event,
            "response.reasoning_summary_text.done": self._handle_reasoning_text_done,
            "response.output_item.added": self._handle_output_item_added,
            "response.function_call_arguments.delta": self._handle_function_args_delta,
            "response.function_call_arguments.done": self._handle_function_args_done,
            "response.output_item.done": self._handle_output_item_done,
            "response.created": self._handle_lifecycle_passthrough,
            "response.in_progress": self._handle_lifecycle_passthrough,
            "response.content_part.added": self._handle_lifecycle_passthrough,
            "response.content_part.done": self._handle_lifecycle_passthrough,
            "response.completed": self._handle_response_completed,
            "response.failed": self._handle_response_failed,
            "response.incomplete": self._handle_response_incomplete,
            "response.error": self._handle_response_error,
            "error": self._handle_error_event,
        }

    def process_event(self, data: Dict[str, Any]) -> StreamTurnDecision:
        event_type = data.get("type")
        if not isinstance(event_type, str):
            return StreamTurnDecision()

        self._record_event_gap(event_type)

        handler = self._get_handler(event_type)
        if handler is not None:
            return handler(data)

        if event_type.startswith("response."):
            return self._handle_uncaptured_response_event(event_type, data)
        return self._handle_uncaptured_nonresponse_event(event_type, data)

    def _get_handler(self, event_type: str) -> Optional[Callable[[Dict[str, Any]], StreamTurnDecision]]:
        return self._handlers.get(event_type)

    def _record_event_gap(self, event_type: str) -> None:
        now_monotonic = time.monotonic()
        if self.last_stream_event_monotonic is not None:
            gap_ms = int((now_monotonic - self.last_stream_event_monotonic) * 1000)
            if gap_ms >= 5000:
                log_event(
                    self.logger,
                    "INFO",
                    "chat.stream.openai_event_gap",
                    "timing",
                    provider=self.provider_name,
                    model=self.model,
                    gap_ms=gap_ms,
                    previous_event_type=self.last_stream_event_type,
                    current_event_type=event_type,
                    emitted_visible_output=self.turn_emitted_visible_output,
                )
        self.last_stream_event_monotonic = now_monotonic
        self.last_stream_event_type = event_type

    def _build_reasoning_updates(
        self,
        *,
        item_id: Any,
        summary_index: Any,
        text: str,
        treat_as_snapshot: bool = False,
    ) -> List[Dict[str, Any]]:
        if not isinstance(item_id, str) or item_id in self.thinking_finished:
            return []

        existing = self.reasoning_summaries.get(item_id, "")
        combined, delta_to_emit = self._merge_reasoning_summary_text(
            existing=existing,
            incoming=text,
            treat_as_snapshot=treat_as_snapshot,
        )
        if combined != existing:
            self.reasoning_summaries[item_id] = combined

        updates: List[Dict[str, Any]] = []
        if item_id not in self.thinking_started:
            title = self._extract_reasoning_title(combined)
            if title is not None:
                self.thinking_started.add(item_id)
                updates.append(
                    {
                        "type": "thinking_start",
                        "content": {"index": summary_index, "title": title},
                    }
                )
                if combined.strip():
                    updates.append(
                        {
                            "type": "thinking_delta",
                            "content": {"text": combined, "index": summary_index},
                        }
                    )
            return updates

        if delta_to_emit:
            updates.append(
                {
                    "type": "thinking_delta",
                    "content": {"text": delta_to_emit, "index": summary_index},
                }
            )
        return updates

    def _classify_retry_strategy(self, error_code: Any) -> Tuple[bool, bool]:
        """Return (retry_with_full_context, reconnect_websocket_first)."""
        normalized_code = str(error_code or "").strip().lower()
        if (
            self.use_openai_websocket
            and normalized_code == "websocket_connection_limit_reached"
            and not self.turn_emitted_visible_output
        ):
            return True, True
        return False, False

    def _with_emitted(self, *events: Dict[str, Any]) -> StreamTurnDecision:
        return StreamTurnDecision(emitted_events=list(events))

    def _error_terminal(self, *, message: str, code: str, emitted_events: Optional[List[Dict[str, Any]]] = None) -> StreamTurnDecision:
        events = list(emitted_events or [])
        events.append({"type": "error", "content": {"message": message, "code": code}})
        events.append({"type": "final"})
        return StreamTurnDecision(emitted_events=events, terminate_stream=True)

    def _handle_output_text_delta(self, data: Dict[str, Any]) -> StreamTurnDecision:
        raw_delta = data.get("delta")
        delta = raw_delta if isinstance(raw_delta, str) else ""
        if delta:
            self.turn_emitted_visible_output = True
            return self._with_emitted({"type": "response", "delta": delta})
        return StreamTurnDecision()

    def _handle_output_text_done(self, data: Dict[str, Any]) -> StreamTurnDecision:
        raw_text = data.get("text")
        text = raw_text if isinstance(raw_text, str) else ""
        if text:
            self.turn_emitted_visible_output = True
            self.turn_text_chunks.append(text)
            return self._with_emitted({"type": "response_complete", "content": text})
        return StreamTurnDecision()

    def _handle_reasoning_text_delta(self, data: Dict[str, Any]) -> StreamTurnDecision:
        item_id = data.get("item_id")
        raw_delta = data.get("delta")
        delta = raw_delta if isinstance(raw_delta, str) else ""
        summary_index = data.get("summary_index")
        if not delta:
            return StreamTurnDecision()

        updates = self._build_reasoning_updates(
            item_id=item_id,
            summary_index=summary_index,
            text=delta,
        )
        if updates:
            self.turn_emitted_visible_output = True
            return StreamTurnDecision(emitted_events=updates)
        return StreamTurnDecision()

    def _handle_reasoning_part_event(self, data: Dict[str, Any]) -> StreamTurnDecision:
        event_type = str(data.get("type") or "")
        item_id = data.get("item_id")
        summary_index = data.get("summary_index")
        part_text = self._extract_reasoning_summary_part_text(data.get("part"))
        updates = self._build_reasoning_updates(
            item_id=item_id,
            summary_index=summary_index,
            text=part_text,
            treat_as_snapshot=(event_type == "response.reasoning_summary_part.done"),
        )

        events: List[Dict[str, Any]] = []
        if updates:
            self.turn_emitted_visible_output = True
            events.extend(updates)

        if (
            event_type == "response.reasoning_summary_part.done"
            and isinstance(item_id, str)
            and item_id in self.thinking_started
            and item_id not in self.thinking_finished
        ):
            self.thinking_finished.add(item_id)
            self.turn_emitted_visible_output = True
            events.append({"type": "thinking_end", "content": {"index": summary_index}})

        return StreamTurnDecision(emitted_events=events)

    def _handle_reasoning_text_done(self, data: Dict[str, Any]) -> StreamTurnDecision:
        item_id = data.get("item_id")
        summary_index = data.get("summary_index")
        if (
            isinstance(item_id, str)
            and item_id in self.thinking_started
            and item_id not in self.thinking_finished
        ):
            self.thinking_finished.add(item_id)
            self.turn_emitted_visible_output = True
            return self._with_emitted({"type": "thinking_end", "content": {"index": summary_index}})
        return StreamTurnDecision()

    def _handle_output_item_added(self, data: Dict[str, Any]) -> StreamTurnDecision:
        item = data.get("item") or {}
        lifecycle_payload = data.get("response") or data

        if isinstance(item, dict) and item.get("type") == "compaction":
            item_id = item.get("id")
            payload: Dict[str, Any] = {
                "item_id": str(item_id) if item_id is not None else None,
                "source": "openai_server",
            }
            return self._with_emitted(
                {"type": "compaction_started", "data": payload},
                {"type": "response.output_item.added", "data": lifecycle_payload},
            )

        if not (isinstance(item, dict) and item.get("type") == "function_call"):
            return self._with_emitted({"type": "response.output_item.added", "data": lifecycle_payload})

        name = item.get("name")
        call_id = item.get("call_id")
        item_id = item.get("id") or call_id or name or f"call_{len(self.tool_calls) + 1}"
        args_raw = item.get("arguments")
        call = {
            "id": str(item_id),
            "call_id": str(call_id or item_id),
            "name": str(name) if name is not None else "",
            "arguments": args_raw if isinstance(args_raw, str) else "",
        }

        for existing in self.tool_calls:
            if existing.get("call_id") == call["call_id"]:
                current_arguments = str(existing.get("arguments") or "")
                incoming_arguments = call["arguments"]
                if len(incoming_arguments) >= len(current_arguments):
                    existing["arguments"] = incoming_arguments
                return self._with_emitted({"type": "response.output_item.added", "data": lifecycle_payload})

        if call["call_id"] in self.seen_tool_call_ids:
            return self._with_emitted({"type": "response.output_item.added", "data": lifecycle_payload})

        self.seen_tool_call_ids.add(call["call_id"])
        self.tool_calls.append(call)
        self.turn_emitted_visible_output = True

        return self._with_emitted(
            {
                "type": "tool_call",
                "name": call["name"],
                "call_id": call["call_id"],
                "item_id": call["id"],
                "arguments": call["arguments"],
                "content": f"TOOL CALL: {call['name']}",
            },
            {"type": "response.output_item.added", "data": lifecycle_payload},
        )

    def _handle_function_args_delta(self, data: Dict[str, Any]) -> StreamTurnDecision:
        item_id = data.get("item_id")
        delta = data.get("delta") or ""
        if not isinstance(item_id, str) or not delta:
            return StreamTurnDecision()

        for call in self.tool_calls:
            if call.get("id") == item_id or call.get("call_id") == item_id:
                call["arguments"] = (call.get("arguments") or "") + delta
                break
        return StreamTurnDecision()

    def _handle_function_args_done(self, data: Dict[str, Any]) -> StreamTurnDecision:
        item_id = data.get("item_id")
        final_arguments = data.get("arguments")
        if isinstance(item_id, str) and isinstance(final_arguments, str):
            for call in self.tool_calls:
                if call.get("id") == item_id or call.get("call_id") == item_id:
                    current_arguments = call.get("arguments") or ""
                    if len(final_arguments) >= len(current_arguments):
                        call["arguments"] = final_arguments
                    break
        lifecycle_payload = data.get("response") or data
        return self._with_emitted({"type": "response.function_call_arguments.done", "data": lifecycle_payload})

    def _handle_output_item_done(self, data: Dict[str, Any]) -> StreamTurnDecision:
        item = data.get("item") or {}
        if isinstance(item, dict) and item.get("type") == "compaction":
            item_id = item.get("id")
            payload: Dict[str, Any] = {
                "item_id": str(item_id) if item_id is not None else None,
                "source": "openai_server",
            }
            lifecycle_payload = data.get("response") or data
            return self._with_emitted(
                {"type": "compaction_completed", "data": payload},
                {"type": "response.output_item.done", "data": lifecycle_payload},
            )

        if isinstance(item, dict) and item.get("type") == "function_call":
            item_id = item.get("id") or item.get("call_id")
            final_arguments = item.get("arguments")
            if isinstance(item_id, str) and isinstance(final_arguments, str):
                for call in self.tool_calls:
                    if call.get("id") == item_id or call.get("call_id") == item_id:
                        current_arguments = call.get("arguments") or ""
                        if len(final_arguments) >= len(current_arguments):
                            call["arguments"] = final_arguments
                        break
        lifecycle_payload = data.get("response") or data
        return self._with_emitted({"type": "response.output_item.done", "data": lifecycle_payload})

    def _handle_lifecycle_passthrough(self, data: Dict[str, Any]) -> StreamTurnDecision:
        event_type = str(data.get("type") or "")
        lifecycle_payload = data.get("response") or data
        return self._with_emitted({"type": event_type, "data": lifecycle_payload})

    def _handle_response_completed(self, data: Dict[str, Any]) -> StreamTurnDecision:
        response_payload = data.get("response") or data
        events: List[Dict[str, Any]] = []

        if not self.turn_emitted_visible_output and isinstance(response_payload, dict):
            completion_text = self._extract_text_from_response_payload(response_payload)
            if completion_text:
                self.turn_emitted_visible_output = True
                self.turn_text_chunks.append(completion_text)
                events.append({"type": "response_complete", "content": completion_text})

        events.append({"type": "response.completed", "data": response_payload})

        if isinstance(response_payload, dict):
            self.latest_response_payload = response_payload

            response_snapshot = dict(response_payload)
            response_snapshot["model"] = self.model
            events.append({"type": "raw_response", "content": response_snapshot})

            self.latest_response_reasoning_items = self._extract_reasoning_replay_items(response_payload)
            response_id = response_payload.get("id")
            if isinstance(response_id, str) and response_id.strip():
                self.latest_response_id = response_id.strip()

        return StreamTurnDecision(emitted_events=events)

    def _handle_response_failed(self, data: Dict[str, Any]) -> StreamTurnDecision:
        response_payload = data.get("response") or {}
        err = (response_payload or {}).get("error") or {}
        should_retry, should_reconnect = self._classify_retry_strategy(err.get("code"))
        if should_retry:
            self.reconnect_websocket = self.reconnect_websocket or should_reconnect
            self.retry_with_full_context = True
            return StreamTurnDecision(
                emitted_events=[{"type": "response.failed", "data": response_payload}],
                break_turn=True,
            )

        return self._error_terminal(
            message=err.get("message") or "The model failed to generate a response.",
            code=err.get("code") or "response_failed",
            emitted_events=[{"type": "response.failed", "data": response_payload}],
        )

    def _handle_response_incomplete(self, data: Dict[str, Any]) -> StreamTurnDecision:
        response_payload = data.get("response") or {}
        details = (response_payload or {}).get("incomplete_details") or {}
        reason = details.get("reason") or "unknown"
        return self._error_terminal(
            message=f"Response was incomplete (reason: {reason}).",
            code="response_incomplete",
            emitted_events=[{"type": "response.incomplete", "data": response_payload}],
        )

    def _handle_response_error(self, data: Dict[str, Any]) -> StreamTurnDecision:
        error_payload = data.get("error") or {}
        should_retry, should_reconnect = self._classify_retry_strategy(error_payload.get("code"))
        if should_retry:
            self.reconnect_websocket = self.reconnect_websocket or should_reconnect
            self.retry_with_full_context = True
            return StreamTurnDecision(
                emitted_events=[{"type": "response.error", "data": error_payload}],
                break_turn=True,
            )

        return self._error_terminal(
            message=error_payload.get("message") or "An error occurred while streaming the response.",
            code=error_payload.get("code") or "response_error",
            emitted_events=[{"type": "response.error", "data": error_payload}],
        )

    def _handle_error_event(self, data: Dict[str, Any]) -> StreamTurnDecision:
        error_payload = data.get("error") or {}
        should_retry, should_reconnect = self._classify_retry_strategy(error_payload.get("code"))
        if should_retry:
            self.reconnect_websocket = self.reconnect_websocket or should_reconnect
            self.retry_with_full_context = True
            return StreamTurnDecision(break_turn=True)

        return self._error_terminal(
            message=error_payload.get("message") or "An error occurred while streaming the response.",
            code=error_payload.get("code") or "response_error",
        )

    def _handle_uncaptured_response_event(self, event_type: str, data: Dict[str, Any]) -> StreamTurnDecision:
        lifecycle_payload = data.get("response") or data
        events = [{"type": event_type, "data": lifecycle_payload}]

        if event_type not in self._seen_uncaptured_event_types:
            self._seen_uncaptured_event_types.add(event_type)
            payload_keys = list(data.keys())
            sensitive_payload_keys = [
                key
                for key in payload_keys
                if key in {"delta", "text", "arguments", "content", "output", "response", "part"}
            ]
            log_event(
                self.logger,
                "INFO",
                "chat.stream.openai_uncaptured_event",
                "timing",
                provider=self.provider_name,
                model=self.model,
                event_type=event_type,
                payload_keys=payload_keys,
                sensitive_payload_keys=sensitive_payload_keys,
                forwarded_as_lifecycle=True,
            )

        return StreamTurnDecision(emitted_events=events)

    def _handle_uncaptured_nonresponse_event(self, event_type: str, data: Dict[str, Any]) -> StreamTurnDecision:
        if event_type not in self._seen_uncaptured_event_types:
            self._seen_uncaptured_event_types.add(event_type)
            payload_keys = list(data.keys())
            sensitive_payload_keys = [
                key
                for key in payload_keys
                if key in {"delta", "text", "arguments", "content", "output", "response", "part"}
            ]
            log_event(
                self.logger,
                "INFO",
                "chat.stream.openai_uncaptured_event",
                "timing",
                provider=self.provider_name,
                model=self.model,
                event_type=event_type,
                payload_keys=payload_keys,
                sensitive_payload_keys=sensitive_payload_keys,
                forwarded_as_lifecycle=False,
            )

        return StreamTurnDecision()
