from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set


@dataclass
class StreamState:
    full_response: str = ""
    raw_responses: List[Dict[str, Any]] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)
    response_ids: List[str] = field(default_factory=list)
    seen_response_ids: Set[str] = field(default_factory=set)
    tool_markers: List[Dict[str, Any]] = field(default_factory=list)
    open_tool_idx_by_call_id: Dict[str, int] = field(default_factory=dict)
    had_error: bool = False
    error_payload: Optional[Dict[str, Any]] = None
    got_text_deltas: bool = False
    response_lifecycle_events: List[Dict[str, Any]] = field(default_factory=list)
    latest_response_lifecycle: Optional[Dict[str, Any]] = None
    reasoning_summaries: List[Dict[str, Any]] = field(default_factory=list)
    current_step: Optional[str] = None
    finished: bool = False
    tool_executions: List[Dict[str, Any]] = field(default_factory=list)
    awaiting_user_input: bool = False
    pending_input_payload: Optional[Dict[str, Any]] = None
    # Thinking streaming support (multi-block)
    thinking_seq: int = 0
    thinking_id_by_index: Dict[int, str] = field(default_factory=dict)
    thinking_buffers: Dict[str, str] = field(default_factory=dict)
    thinking_open_ids: Set[str] = field(default_factory=set)
    thinking_title_by_id: Dict[str, str] = field(default_factory=dict)
    # Global sequence index captured when a thinking block starts.
    thinking_sequence_by_id: Dict[str, int] = field(default_factory=dict)
    # Global sequence counter to preserve cross-type ordering (tools, thinking)
    seq_counter: int = 0
    # Mid-stream compaction markers emitted by OpenAI server-side compaction.
    compaction_markers: List[Dict[str, Any]] = field(default_factory=list)
    seen_compaction_item_ids: Set[str] = field(default_factory=set)
    # Latest live token count from the token counting API (for persistence fallback)
    live_input_tokens: int = 0
    # Snapshot of final input_items for cross-turn compaction persistence
    final_input_items: Optional[List[Dict[str, Any]]] = None
    # Compaction tracking (accumulated across sub-turns within a single stream)
    compaction_count: int = 0
    last_compaction_tokens_before: int = 0
    last_compaction_tokens_after: int = 0

    def has_stream_output(self) -> bool:
        if (
            self.full_response.strip()
            or self.tool_markers
            or self.reasoning_summaries
            or self.compaction_markers
        ):
            return True
        try:
            return any(isinstance(buf, str) and bool(buf) for buf in self.thinking_buffers.values())
        except Exception:
            return False

    def register_tool_call(
        self,
        *,
        name: Optional[str],
        call_id: Optional[str],
        position: int,
        sequence: Optional[int] = None,
        arguments: Optional[Any] = None,
    ) -> str:
        """Track the start of a tool call and return the normalized call id."""

        raw_call_id = str(call_id).strip() if isinstance(call_id, str) else ""
        normalized_call_id = raw_call_id or self._fallback_call_id(name)
        if name and name not in self.tools_used:
            self.tools_used.append(name)

        # Defensive dedupe: stream retries/replays can re-emit the same call id.
        existing_idx = self.open_tool_idx_by_call_id.get(normalized_call_id)
        if existing_idx is None:
            existing_idx = self._find_marker_by_call_id(normalized_call_id)
        if existing_idx is not None:
            marker = self.tool_markers[existing_idx]
            if (
                isinstance(name, str)
                and name.strip()
                and not (isinstance(marker.get("name"), str) and str(marker.get("name")).strip())
            ):
                marker["name"] = name
            if arguments is not None and marker.get("arguments") is None:
                marker["arguments"] = arguments
            if "result" in marker or "error" in marker:
                self.open_tool_idx_by_call_id.pop(normalized_call_id, None)
            else:
                self.open_tool_idx_by_call_id[normalized_call_id] = existing_idx
            return normalized_call_id

        marker = {
            "name": name,
            "call_id": normalized_call_id,
            "pos": position,
            **({"seq": sequence} if sequence is not None else {}),
            **({"arguments": arguments} if arguments is not None else {}),
        }
        self.tool_markers.append(marker)
        self.open_tool_idx_by_call_id[normalized_call_id] = len(self.tool_markers) - 1
        return normalized_call_id

    def record_tool_arguments(
        self,
        *,
        call_id: Optional[str],
        name: Optional[str],
        arguments: Any,
    ) -> Optional[str]:
        idx = self._find_open_tool_marker(call_id, name)
        if idx is not None:
            self.tool_markers[idx]["arguments"] = arguments
            stored_call_id = self.tool_markers[idx].get("call_id")
            return stored_call_id if isinstance(stored_call_id, str) else call_id
        return call_id

    def record_tool_query(
        self,
        *,
        call_id: Optional[str],
        name: Optional[str],
        query: Optional[str],
    ) -> Optional[str]:
        if not query:
            return call_id
        idx = self._find_open_tool_marker(call_id, name)
        if idx is not None:
            self.tool_markers[idx]["query"] = query
            stored_call_id = self.tool_markers[idx].get("call_id")
            return stored_call_id if isinstance(stored_call_id, str) else call_id
        return call_id

    def record_tool_result(
        self,
        *,
        call_id: Optional[str],
        name: Optional[str],
        payload: Any,
    ) -> Optional[str]:
        idx = self._find_open_tool_marker(call_id, name)
        if idx is not None:
            if call_id:
                self.open_tool_idx_by_call_id.pop(call_id, None)
            self.tool_markers[idx]["result"] = payload
            stored_call_id = self.tool_markers[idx].get("call_id")
            return stored_call_id if isinstance(stored_call_id, str) else call_id
        return call_id

    def record_tool_error(
        self,
        *,
        call_id: Optional[str],
        name: Optional[str],
        payload: Any,
    ) -> Optional[str]:
        idx = self._find_open_tool_marker(call_id, name)
        if idx is not None:
            if call_id:
                self.open_tool_idx_by_call_id.pop(call_id, None)
            self.tool_markers[idx]["error"] = payload
            stored_call_id = self.tool_markers[idx].get("call_id")
            return stored_call_id if isinstance(stored_call_id, str) else call_id
        return call_id

    def get_tool_marker(
        self,
        *,
        call_id: Optional[str],
        name: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        idx = self._find_open_tool_marker(call_id, name)
        if idx is None and isinstance(call_id, str) and call_id.strip():
            idx = self._find_marker_by_call_id(call_id.strip())
        if idx is None and isinstance(name, str) and name:
            for candidate in reversed(range(len(self.tool_markers))):
                marker = self.tool_markers[candidate]
                if marker.get("name") == name:
                    idx = candidate
                    break
        if idx is None:
            return None
        marker = self.tool_markers[idx]
        return dict(marker) if isinstance(marker, dict) else None

    def _find_marker_by_call_id(self, call_id: str) -> Optional[int]:
        if not call_id:
            return None
        for candidate in reversed(range(len(self.tool_markers))):
            marker = self.tool_markers[candidate]
            marker_call_id = marker.get("call_id")
            if isinstance(marker_call_id, str) and marker_call_id == call_id:
                return candidate
        return None

    def _find_open_tool_marker(
        self,
        call_id: Optional[str],
        name: Optional[str],
    ) -> Optional[int]:
        idx = None
        if call_id:
            idx = self.open_tool_idx_by_call_id.get(call_id)
        if idx is None and name:
            for candidate in reversed(range(len(self.tool_markers))):
                marker = self.tool_markers[candidate]
                if marker.get("name") != name:
                    continue
                if "result" in marker or "error" in marker:
                    continue
                idx = candidate
                break
        return idx

    def _fallback_call_id(self, name: Optional[str]) -> str:
        base = (name or "tool").strip().replace(" ", "_") or "tool"
        return f"call_{base}_{len(self.tool_markers) + 1}"

    def register_compaction_start(
        self,
        *,
        item_id: Optional[str],
        source: Optional[str],
        position: int,
        sequence: Optional[int] = None,
        label: Optional[str] = None,
    ) -> bool:
        normalized_item_id = item_id.strip() if isinstance(item_id, str) and item_id.strip() else None
        if normalized_item_id and normalized_item_id in self.seen_compaction_item_ids:
            return False

        normalized_label = (
            str(label).strip()
            if isinstance(label, str) and label.strip()
            else "Automatically compacting context"
        )

        marker: Dict[str, Any] = {
            "pos": position,
            "label": normalized_label,
            "source": (
                str(source).strip()
                if isinstance(source, str) and source.strip()
                else "openai_server"
            ),
            **({"seq": sequence} if sequence is not None else {}),
        }
        if normalized_item_id:
            marker["item_id"] = normalized_item_id
            self.seen_compaction_item_ids.add(normalized_item_id)

        self.compaction_markers.append(marker)
        return True


@dataclass
class FinalizationOptions:
    """Groups the parameters that control how a stream turn is persisted."""
    assistant_message_id: Optional[str] = None
    update_existing: bool = False
    message_status: str = "completed"
    include_done_chunk: bool = True
    update_user_message_status: bool = True
    # Checkpoint writes persist partial content while a stream is still running.
    # They intentionally skip usage/cost aggregation and completion logging.
    checkpoint_mode: bool = False
    checkpoint_stream_event_id: Optional[int] = None
    # Optional done payload enrichment for paused/user-input branches.
    done_pending_requests: Optional[List[Dict[str, Any]]] = None
    # Optional ordering override when the server cuts a turn at a queue handoff.
    assistant_created_at: Optional[datetime] = None


__all__ = ["StreamState", "FinalizationOptions"]
