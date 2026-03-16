"""Build provider-specific stream attempt inputs from normalized context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ...config.settings import settings
from ...utils.jsonlib import json_dumps
from ..provider_registry import get_tool_specs_for_provider
from ..streaming_support import StreamState
from ..tool_payload_sanitizer import sanitize_tool_payload_for_model


@dataclass
class PreparedStreamAttempt:
    provider_name: str
    model_name: str
    reasoning_effort: str
    tool_specs: List[Dict[str, Any]]
    system_prompt: Any
    conversation_history: List[Dict[str, Any]]
    query: Any
    state: StreamState
    stream_kwargs: Dict[str, Any]


class StreamAttemptBuilder:
    """Encapsulates stream request preparation for a single provider attempt."""

    def prepare_attempt(
        self,
        *,
        provider_name: str,
        effective_model: str,
        reasoning_effort: str,
        conversation_history: List[Dict[str, Any]],
        user_prompt: str,
        current_message_attachments: Optional[List[Dict[str, Any]]],
        tool_context: Dict[str, Any],
        is_admin: bool,
        user_name: str,
        current_date: str,
        current_time: str,
        user_timezone: str,
        project_name: Optional[str],
        project_description: Optional[str],
        project_custom_instructions: Optional[str],
        project_files_summary: Optional[Dict[str, Any]],
        user_custom_instructions: Optional[str],
        skills_prompt_section: Optional[str] = None,
        resume_assistant_message_id: Optional[str],
        seed_response_text: Optional[str],
        seed_tool_markers: Optional[List[Dict[str, Any]]],
        seed_reasoning_summaries: Optional[List[Dict[str, Any]]],
        seed_compaction_markers: Optional[List[Dict[str, Any]]],
        file_service: Any,
        base_conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> PreparedStreamAttempt:
        try:
            include_project_tools = bool(tool_context.get("project_id"))
            tool_specs = get_tool_specs_for_provider(
                provider_name,
                include_project_tools=include_project_tools,
                is_admin=is_admin,
            )
        except Exception:
            tool_specs = []

        system_prompt = self.build_system_prompt(
            user_name=user_name,
            current_date=current_date,
            current_time=current_time,
            user_timezone=user_timezone,
            project_name=project_name,
            project_description=project_description,
            project_custom_instructions=project_custom_instructions,
            project_files_summary=project_files_summary,
            user_custom_instructions=user_custom_instructions,
            skills_prompt_section=skills_prompt_section,
        )

        pruned_history = self.prune_history_to_fit(
            conversation_history=conversation_history,
            max_chars=800_000,
        )

        query = self._build_query_content(
            user_prompt=user_prompt,
            current_message_attachments=current_message_attachments,
            file_service=file_service,
        )

        state = self._build_seeded_state(
            seed_response_text=seed_response_text,
            seed_tool_markers=seed_tool_markers,
            seed_reasoning_summaries=seed_reasoning_summaries,
            seed_compaction_markers=seed_compaction_markers,
        )

        stream_tool_context = dict(tool_context)
        stream_tool_context["provider"] = provider_name

        if provider_name == "openai":
            stream_tool_context["openai_compact_trigger_tokens"] = settings.openai_compact_trigger_tokens

        stream_kwargs: Dict[str, Any] = {
            "query": query,
            "conversation_history": pruned_history,
            "tools": tool_specs,
            "model": effective_model,
            "reasoning_effort": reasoning_effort,
            "tool_context": stream_tool_context,
            "system_prompt": system_prompt,
        }
        if resume_assistant_message_id and seed_tool_markers:
            stream_kwargs["resume_continuation"] = self.build_resume_continuation(
                seed_markers=seed_tool_markers,
            )

        return PreparedStreamAttempt(
            provider_name=provider_name,
            model_name=effective_model,
            reasoning_effort=reasoning_effort,
            tool_specs=tool_specs,
            system_prompt=system_prompt,
            conversation_history=pruned_history,
            query=query,
            state=state,
            stream_kwargs=stream_kwargs,
        )

    @staticmethod
    def query_to_estimate_text(query: Any) -> str:
        if isinstance(query, str):
            return query

        if isinstance(query, list):
            segments: List[str] = []
            for block in query:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").strip().lower()
                if block_type in {"text", "input_text", "output_text"}:
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        segments.append(text.strip())
                    continue
                if block_type in {"image", "input_image"}:
                    segments.append("[image]")
                    continue
                fallback_text = block.get("text")
                if isinstance(fallback_text, str) and fallback_text.strip():
                    segments.append(fallback_text.strip())

            if segments:
                return "\n".join(segments)

        try:
            return json_dumps(query)
        except Exception:
            return str(query)

    @staticmethod
    def normalize_system_blocks_for_estimate(
        system_prompt: Any,
    ) -> Optional[List[Dict[str, Any]]]:
        if system_prompt is None:
            return None

        if isinstance(system_prompt, list):
            normalized: List[Dict[str, Any]] = []
            for block in system_prompt:
                if not isinstance(block, dict):
                    continue
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    normalized.append({"text": text})
            return normalized or None

        if isinstance(system_prompt, dict):
            text = system_prompt.get("text")
            if isinstance(text, str) and text.strip():
                return [{"text": text}]
            return None

        text_value = str(system_prompt).strip()
        if not text_value:
            return None
        return [{"text": text_value}]

    @staticmethod
    def build_resume_continuation(
        *,
        seed_markers: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for marker in seed_markers:
            items.append(
                {
                    "type": "function_call",
                    "name": marker.get("name") or "",
                    "call_id": marker.get("call_id") or "",
                    "arguments": marker.get("query") or "{}",
                }
            )
            is_error = "error" in marker
            result = marker.get("error") if is_error else marker.get("result")
            result = sanitize_tool_payload_for_model(str(marker.get("name") or ""), result)
            try:
                output_str = json.dumps(result) if result is not None else "{}"
            except Exception:
                output_str = str(result) if result is not None else "{}"
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": marker.get("call_id") or "",
                    "output": output_str,
                }
            )
        return items

    def build_system_prompt(
        self,
        *,
        user_name: str,
        current_date: str,
        current_time: str,
        user_timezone: str,
        project_name: Optional[str],
        project_description: Optional[str],
        project_custom_instructions: Optional[str],
        project_files_summary: Optional[Dict[str, Any]],
        user_custom_instructions: Optional[str] = None,
        skills_prompt_section: Optional[str] = None,
    ) -> Any:
        from ...prompts import build_openai_system_prompt

        return build_openai_system_prompt(
            user_name=user_name,
            current_date=current_date,
            current_time=current_time,
            user_timezone=user_timezone,
            project_name=project_name,
            project_description=project_description,
            project_custom_instructions=project_custom_instructions,
            project_files_summary=project_files_summary,
            user_custom_instructions=user_custom_instructions,
            skills_prompt_section=skills_prompt_section,
        )

    @staticmethod
    def prune_history_to_fit(
        *,
        conversation_history: List[Dict[str, Any]],
        max_chars: int = 800_000,
    ) -> List[Dict[str, Any]]:
        """Drop oldest messages until serialized size is under max_chars.

        This is a coarse safety net.  Exact token counting + compaction
        happens in the model layer via the OpenAI token counting API.
        """
        history = list(conversation_history or [])
        if not history:
            return history

        def _estimated_chars(msgs: List[Dict[str, Any]]) -> int:
            try:
                return len(json_dumps(msgs))
            except Exception:
                return sum(len(str(m)) for m in msgs)

        if _estimated_chars(history) <= max_chars:
            return history

        min_tail = 4
        while len(history) > min_tail:
            history.pop(0)
            if _estimated_chars(history) <= max_chars:
                break
        return history

    @staticmethod
    def _build_query_content(
        *,
        user_prompt: str,
        current_message_attachments: Optional[List[Dict[str, Any]]],
        file_service: Any,
    ) -> Any:
        attempt_query: Any = user_prompt
        if not current_message_attachments:
            return attempt_query

        from .message_formatter import build_image_content_blocks

        content_blocks = build_image_content_blocks(
            current_message_attachments,
            file_service,
        )

        image_parts: List[Dict[str, Any]] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "image":
                continue
            source = block.get("source") or {}
            url = None
            if isinstance(source, dict):
                url = source.get("url")
            if isinstance(url, str) and url.strip():
                image_parts.append(
                    {
                        "type": "input_image",
                        "image_url": url,
                    }
                )

        if image_parts:
            content_parts: List[Dict[str, Any]] = []
            if isinstance(user_prompt, str) and user_prompt.strip():
                content_parts.append({"type": "input_text", "text": user_prompt})
            content_parts.extend(image_parts)
            return content_parts

        return attempt_query

    @staticmethod
    def _build_seeded_state(
        *,
        seed_response_text: Optional[str],
        seed_tool_markers: Optional[List[Dict[str, Any]]],
        seed_reasoning_summaries: Optional[List[Dict[str, Any]]],
        seed_compaction_markers: Optional[List[Dict[str, Any]]],
    ) -> StreamState:
        state = StreamState()
        if seed_response_text:
            state.full_response = seed_response_text
        if seed_tool_markers:
            state.tool_markers = [dict(marker) for marker in seed_tool_markers]
            max_seq = 0
            for idx, marker in enumerate(state.tool_markers):
                seq = marker.get("seq")
                if isinstance(seq, int):
                    max_seq = max(max_seq, seq)
                call_id = marker.get("call_id")
                if not isinstance(call_id, str):
                    continue
                normalized_call_id = call_id.strip()
                if not normalized_call_id:
                    continue
                marker["call_id"] = normalized_call_id
                if "result" in marker or "error" in marker:
                    continue
                state.open_tool_idx_by_call_id[normalized_call_id] = idx
            state.seq_counter = max_seq
        if seed_reasoning_summaries:
            state.reasoning_summaries = [dict(summary) for summary in seed_reasoning_summaries]
            for summary in state.reasoning_summaries:
                seq = summary.get("sequence")
                if isinstance(seq, int) and seq > state.seq_counter:
                    state.seq_counter = seq
        if seed_compaction_markers:
            state.compaction_markers = [dict(marker) for marker in seed_compaction_markers]
            for marker in state.compaction_markers:
                seq = marker.get("seq")
                if isinstance(seq, int) and seq > state.seq_counter:
                    state.seq_counter = seq
                item_id = marker.get("item_id")
                if isinstance(item_id, str) and item_id.strip():
                    state.seen_compaction_item_ids.add(item_id.strip())
        return state


__all__ = ["PreparedStreamAttempt", "StreamAttemptBuilder"]
