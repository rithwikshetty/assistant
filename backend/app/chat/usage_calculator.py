from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .provider_usage_collectors import resolve_usage_collector
from ..config.settings import settings
from ..utils.coerce import coerce_int

MODEL_CONTEXT_WINDOWS: Dict[str, int] = {
    "gpt-5.4": 1_050_000,
    "gpt-4.1-mini": 1_047_576,
}

DEFAULT_CONTEXT_WINDOW: int = 1_050_000


def _normalize_model_key(model_name: Optional[str]) -> Optional[str]:
    if not model_name or not isinstance(model_name, str):
        return None
    return model_name.strip().lower()


def resolve_context_window(model_name: Optional[str]) -> Optional[int]:
    normalized = _normalize_model_key(model_name)
    if not normalized:
        return None

    base_value: Optional[int] = MODEL_CONTEXT_WINDOWS.get(normalized)

    if base_value is None:
        # Handle versioned model ids like "gpt-5-mini-2025-09-12"
        for key, value in MODEL_CONTEXT_WINDOWS.items():
            if normalized.startswith(f"{key}-"):
                base_value = value
                break

    if base_value is None:
        return None

    return base_value


def _coerce_token_value(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            # Handle floats encoded as strings just in case
            return int(float(stripped))
        except ValueError:
            return None
    return None


def _extract_token_value(data: Dict[str, Any], keys: List[str]) -> Optional[int]:
    for key in keys:
        token_value = _coerce_token_value(data.get(key))
        if token_value is not None:
            return token_value
    return None


def _extract_effective_input_tokens(data: Dict[str, Any]) -> Optional[int]:
    """Return provider-reported effective input tokens for this response.

    OpenAI usage reports `input_tokens` as effective input (including
    cache reads). Use it directly when present to avoid double counting.
    """

    direct_input = _extract_token_value(
        data,
        [
            "input_tokens",
            "prompt_tokens",
            "inputTokens",
            "promptTokens",
        ],
    )
    if direct_input is not None:
        return direct_input

    base_input = _extract_token_value(
        data,
        ["base_input_tokens", "baseInputTokens"],
    )

    cache_creation = _extract_token_value(
        data,
        ["cache_creation_input_tokens", "cacheCreationInputTokens"],
    )

    cache_read = _extract_token_value(
        data,
        ["cache_read_input_tokens", "cacheReadInputTokens", "cached_tokens", "cachedTokens"],
    )
    # Also check nested OpenAI structure: prompt_tokens_details.cached_tokens
    if cache_read is None:
        for details_key in ("prompt_tokens_details", "input_tokens_details"):
            details = data.get(details_key)
            if isinstance(details, dict):
                nested_cached = details.get("cached_tokens")
                if nested_cached is not None:
                    try:
                        cache_read = int(nested_cached)
                        break
                    except (ValueError, TypeError):
                        pass

    if (
        base_input is None
        and cache_creation is None
        and cache_read is None
    ):
        return None

    total = max(0, (base_input or 0) + (cache_creation or 0) + (cache_read or 0))
    return total


def _build_usage_payload(
    *,
    total_input: int,
    total_output: int,
    context_input: Optional[int],
    context_output: Optional[int],
    context_total: Optional[int],
    context_window: Optional[int],
    base_input: Optional[int],
    cache_creation: Optional[int],
    cache_read: Optional[int],
) -> Dict[str, Any]:
    # Context metrics should reflect the heaviest single request rather than the
    # aggregate token spend across tool loops.
    context_input_tokens = context_input if context_input is not None else total_input
    context_output_tokens = context_output if context_output is not None else total_output
    if context_total is not None:
        context_total_tokens = context_total
    else:
        context_total_tokens = context_input_tokens + context_output_tokens

    usage_payload: Dict[str, Any] = {
        "input_tokens": context_input_tokens,
        "output_tokens": context_output_tokens,
        "total_tokens": context_total_tokens,
    }

    if base_input is not None:
        usage_payload["base_input_tokens"] = base_input
    if cache_creation is not None:
        usage_payload["cache_creation_input_tokens"] = cache_creation
    if cache_read is not None:
        usage_payload["cache_read_input_tokens"] = cache_read

    if context_window is not None:
        usage_payload["max_context_tokens"] = context_window
        usage_payload["remaining_context_tokens"] = max(context_window - context_input_tokens, 0)

    aggregated_total = total_input + total_output
    if total_input and total_input != context_input_tokens:
        usage_payload["aggregated_input_tokens"] = total_input
    if total_output and total_output != context_output_tokens:
        usage_payload["aggregated_output_tokens"] = total_output
    if aggregated_total and aggregated_total != context_total_tokens:
        usage_payload["aggregated_total_tokens"] = aggregated_total

    return usage_payload


@dataclass
class RawUsageSummary:
    total_input: int
    total_output: int
    context_input: Optional[int]
    context_output: Optional[int]
    context_total: Optional[int]
    base_input: Optional[int]
    cache_creation_input: Optional[int]
    cache_read_input: Optional[int]
    reasoning_output: Optional[int]
    saw_usage: bool


class UsageCalculator:
    """Handles token accounting and conversation usage aggregation."""

    def summarize(
        self,
        raw_responses: List[Dict[str, Any]],
        provider: Optional[str] = None,
    ) -> RawUsageSummary:
        collector = resolve_usage_collector(provider)
        prepared_responses = collector.collect(raw_responses)
        return self._summarize_prepared(prepared_responses)

    def _summarize_prepared(
        self,
        prepared_responses: List[Dict[str, Any]],
    ) -> RawUsageSummary:
        usage_by_id: Dict[str, Dict[str, Optional[int]]] = {}
        unkeyed_usage: List[Dict[str, Optional[int]]] = []
        max_context_input: Optional[int] = None
        max_context_output: Optional[int] = None
        max_context_total: Optional[int] = None
        last_context_input: Optional[int] = None
        last_context_output: Optional[int] = None
        last_context_total: Optional[int] = None
        total_base_input: Optional[int] = None
        total_cache_creation: Optional[int] = None
        total_cache_read: Optional[int] = None
        total_reasoning_output: Optional[int] = None
        saw_usage = False

        for raw in prepared_responses:
            if not isinstance(raw, dict):
                continue

            usage_data = raw.get("usage")
            if not isinstance(usage_data, dict):
                continue

            input_value = _extract_effective_input_tokens(usage_data)
            output_value = _extract_token_value(
                usage_data,
                ["output_tokens", "completion_tokens", "outputTokens", "completionTokens"],
            )
            total_value = _extract_token_value(
                usage_data,
                ["total_tokens", "totalTokens", "all_tokens", "allTokens"],
            )
            base_input_value = _extract_token_value(
                usage_data,
                [
                    "base_input_tokens",
                    "input_tokens",
                    "prompt_tokens",
                    "baseInputTokens",
                    "inputTokens",
                    "promptTokens",
                ],
            )
            cache_creation_value = _extract_token_value(
                usage_data,
                ["cache_creation_input_tokens", "cacheCreationInputTokens"],
            )
            cache_read_value = _extract_token_value(
                usage_data,
                ["cache_read_input_tokens", "cacheReadInputTokens", "cached_tokens", "cachedTokens"],
            )
            reasoning_output_value = _extract_token_value(
                usage_data,
                ["reasoning_tokens", "reasoningTokens"],
            )
            # Also check nested OpenAI structure: prompt_tokens_details.cached_tokens
            if cache_read_value is None:
                for details_key in ("prompt_tokens_details", "input_tokens_details"):
                    details = usage_data.get(details_key)
                    if isinstance(details, dict):
                        nested_cached = details.get("cached_tokens")
                        if nested_cached is not None:
                            try:
                                cache_read_value = int(nested_cached)
                                break
                            except (ValueError, TypeError):
                                pass
            # Also check nested output detail structures for reasoning tokens.
            if reasoning_output_value is None:
                for details_key in ("output_tokens_details", "completion_tokens_details"):
                    details = usage_data.get(details_key)
                    if isinstance(details, dict):
                        nested_reasoning = details.get("reasoning_tokens")
                        if nested_reasoning is not None:
                            try:
                                reasoning_output_value = int(nested_reasoning)
                                break
                            except (ValueError, TypeError):
                                pass

            if any(
                value is not None
                for value in (
                    input_value,
                    output_value,
                    total_value,
                    base_input_value,
                    cache_creation_value,
                    cache_read_value,
                    reasoning_output_value,
                )
            ):
                saw_usage = True

            if input_value is None and output_value is None and total_value is None:
                # Continue collecting cache/base data for future aggregation even if
                # primary counters are absent.
                pass

            if input_value is not None:
                max_context_input = input_value if max_context_input is None else max(max_context_input, input_value)
                last_context_input = input_value
            if output_value is not None:
                max_context_output = output_value if max_context_output is None else max(max_context_output, output_value)
                last_context_output = output_value
            if total_value is not None:
                max_context_total = total_value if max_context_total is None else max(max_context_total, total_value)
                last_context_total = total_value

            resp_id_raw = raw.get("id")
            target: Dict[str, Optional[int]]
            if isinstance(resp_id_raw, str) and resp_id_raw.strip():
                resp_id = resp_id_raw.strip()
                target = usage_by_id.setdefault(
                    resp_id,
                    {
                        "input": None,
                        "output": None,
                        "total": None,
                        "base_input": None,
                        "cache_creation": None,
                        "cache_read": None,
                        "reasoning_output": None,
                    },
                )
            else:
                target = {"input": None, "output": None, "total": None}
                target["base_input"] = None
                target["cache_creation"] = None
                target["cache_read"] = None
                target["reasoning_output"] = None
                unkeyed_usage.append(target)

            if input_value is not None:
                target["input"] = input_value
            if output_value is not None:
                target["output"] = output_value
            if total_value is not None:
                target["total"] = total_value
            if base_input_value is not None:
                target["base_input"] = base_input_value
            if cache_creation_value is not None:
                target["cache_creation"] = cache_creation_value
            if cache_read_value is not None:
                target["cache_read"] = cache_read_value
            if reasoning_output_value is not None:
                target["reasoning_output"] = reasoning_output_value

        total_input = 0
        total_output = 0
        keyed_signatures: Set[
            Tuple[
                Optional[int],
                Optional[int],
                Optional[int],
                Optional[int],
                Optional[int],
                Optional[int],
                Optional[int],
            ]
        ] = set()

        for snapshot in usage_by_id.values():
            signature = (
                snapshot.get("input"),
                snapshot.get("output"),
                snapshot.get("total"),
                snapshot.get("base_input"),
                snapshot.get("cache_creation"),
                snapshot.get("cache_read"),
                snapshot.get("reasoning_output"),
            )
            keyed_signatures.add(signature)

            input_amount = snapshot.get("input")
            if input_amount is not None:
                total_input += input_amount

            output_amount = snapshot.get("output")
            if output_amount is not None:
                total_output += output_amount

            base_amount = snapshot.get("base_input")
            if base_amount is not None:
                total_base_input = (
                    base_amount
                    if total_base_input is None
                    else total_base_input + base_amount
                )

            cache_creation_amount = snapshot.get("cache_creation")
            if cache_creation_amount is not None:
                total_cache_creation = (
                    cache_creation_amount
                    if total_cache_creation is None
                    else total_cache_creation + cache_creation_amount
                )

            cache_read_amount = snapshot.get("cache_read")
            if cache_read_amount is not None:
                total_cache_read = (
                    cache_read_amount
                    if total_cache_read is None
                    else total_cache_read + cache_read_amount
                )

            reasoning_output_amount = snapshot.get("reasoning_output")
            if reasoning_output_amount is not None:
                total_reasoning_output = (
                    reasoning_output_amount
                    if total_reasoning_output is None
                    else total_reasoning_output + reasoning_output_amount
                )

        for snapshot in unkeyed_usage:
            signature = (
                snapshot.get("input"),
                snapshot.get("output"),
                snapshot.get("total"),
                snapshot.get("base_input"),
                snapshot.get("cache_creation"),
                snapshot.get("cache_read"),
                snapshot.get("reasoning_output"),
            )
            if signature in keyed_signatures:
                continue

            keyed_signatures.add(signature)

            input_amount = snapshot.get("input")
            if input_amount is not None:
                total_input += input_amount

            output_amount = snapshot.get("output")
            if output_amount is not None:
                total_output += output_amount

            base_amount = snapshot.get("base_input")
            if base_amount is not None:
                total_base_input = (
                    base_amount
                    if total_base_input is None
                    else total_base_input + base_amount
                )

            cache_creation_amount = snapshot.get("cache_creation")
            if cache_creation_amount is not None:
                total_cache_creation = (
                    cache_creation_amount
                    if total_cache_creation is None
                    else total_cache_creation + cache_creation_amount
                )

            cache_read_amount = snapshot.get("cache_read")
            if cache_read_amount is not None:
                total_cache_read = (
                    cache_read_amount
                    if total_cache_read is None
                    else total_cache_read + cache_read_amount
                )

            reasoning_output_amount = snapshot.get("reasoning_output")
            if reasoning_output_amount is not None:
                total_reasoning_output = (
                    reasoning_output_amount
                    if total_reasoning_output is None
                    else total_reasoning_output + reasoning_output_amount
                )

        context_input = max_context_input if max_context_input is not None else last_context_input
        context_output = max_context_output if max_context_output is not None else last_context_output
        context_total = max_context_total if max_context_total is not None else last_context_total

        if context_total is None and context_input is not None and context_output is not None:
            context_total = context_input + context_output
        elif context_total is None and context_input is not None:
            context_total = context_input + (context_output or 0)
        elif context_total is None and context_output is not None:
            context_total = (context_input or 0) + context_output

        # Ensure downstream consumers receive explicit zeroes for cache metrics
        # so database columns store 0 instead of NULL when no cache activity occurs.
        if saw_usage:
            if total_cache_creation is None:
                total_cache_creation = 0
            if total_cache_read is None:
                total_cache_read = 0

        return RawUsageSummary(
            total_input=total_input,
            total_output=total_output,
            context_input=context_input,
            context_output=context_output,
            context_total=context_total,
            base_input=total_base_input,
            cache_creation_input=total_cache_creation,
            cache_read_input=total_cache_read,
            reasoning_output=total_reasoning_output,
            saw_usage=saw_usage,
        )

    def resolve_context_window(self, model_name: Optional[str]) -> Optional[int]:
        return resolve_context_window(model_name)

    def build_usage_payload(
        self,
        summary: RawUsageSummary,
        context_window: Optional[int],
    ) -> Dict[str, Any]:
        return _build_usage_payload(
            total_input=summary.total_input,
            total_output=summary.total_output,
            context_input=summary.context_input,
            context_output=summary.context_output,
            context_total=summary.context_total,
            context_window=context_window,
            base_input=summary.base_input,
            cache_creation=summary.cache_creation_input,
            cache_read=summary.cache_read_input,
        )

    def create_conversation_usage(
        self,
        existing_metadata: Optional[Dict[str, Any]],
        usage_payload: Dict[str, Any],
        context_window: Optional[int],
    ) -> Tuple[Dict[str, int], Dict[str, Any]]:
        base_metadata: Dict[str, Any] = {}
        if isinstance(existing_metadata, dict):
            try:
                base_metadata = dict(existing_metadata)
            except Exception:
                base_metadata = {}

        existing_usage_section = base_metadata.get("usage")
        usage_meta = dict(existing_usage_section) if isinstance(existing_usage_section, dict) else {}

        self._update_usage_section(usage_meta, "input_tokens", usage_payload.get("input_tokens"))
        self._update_usage_section(usage_meta, "output_tokens", usage_payload.get("output_tokens"))
        self._update_usage_section(usage_meta, "total_tokens", usage_payload.get("total_tokens"))
        self._accumulate_usage_totals(usage_meta, usage_payload)
        self._update_context_tracking_metrics(usage_meta, usage_payload)
        self._apply_context_window(usage_meta, context_window)

        updated_metadata = dict(base_metadata)
        updated_metadata["usage"] = usage_meta

        conversation_usage_payload: Dict[str, int] = {}
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "max_context_tokens",
            "remaining_context_tokens",
            "cumulative_input_tokens",
            "cumulative_output_tokens",
            "cumulative_total_tokens",
            "current_context_tokens",
            "peak_context_tokens",
        ):
            value = self._coerce_int(usage_meta.get(key))
            if value is not None:
                conversation_usage_payload[key] = value

        return conversation_usage_payload, updated_metadata

    _coerce_int = staticmethod(coerce_int)

    @classmethod
    def _update_usage_section(cls, target: Dict[str, Any], key: str, candidate: Optional[int]) -> None:
        if candidate is None:
            return
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            return

        existing = cls._coerce_int(target.get(key))
        if existing is None or value > existing:
            target[key] = value

    @classmethod
    def _apply_context_window(cls, target: Dict[str, Any], context_window: Optional[int]) -> None:
        resolved_window = cls._coerce_int(context_window)
        if resolved_window is None:
            existing_window = cls._coerce_int(target.get("max_context_tokens"))
            if existing_window is None:
                target.pop("remaining_context_tokens", None)
            return

        target["max_context_tokens"] = resolved_window
        # Context occupancy should account for both prompt/input and generated
        # assistant output retained in history. Prefer total tokens when available.
        active_current = cls._coerce_int(target.get("current_context_tokens"))
        active_total = cls._coerce_int(target.get("total_tokens"))
        active_input = cls._coerce_int(target.get("input_tokens"))
        if active_current is not None:
            active_context = active_current
        elif active_total is not None:
            active_context = active_total
        else:
            active_context = active_input or 0
        target["remaining_context_tokens"] = max(resolved_window - active_context, 0)

    @classmethod
    def _accumulate_usage_totals(cls, target: Dict[str, Any], usage_payload: Dict[str, Any]) -> None:
        """Maintain cumulative token totals for feedback gating and analytics."""

        def coerce_candidate(primary_key: str, fallback_key: str) -> Optional[int]:
            value = usage_payload.get(primary_key)
            if value is None:
                value = usage_payload.get(fallback_key)
            coerced = cls._coerce_int(value)
            return coerced if coerced is not None else None

        message_input = coerce_candidate("aggregated_input_tokens", "input_tokens") or 0
        message_output = coerce_candidate("aggregated_output_tokens", "output_tokens") or 0
        message_total = coerce_candidate("aggregated_total_tokens", "total_tokens")
        if message_total is None:
            message_total = message_input + message_output

        for key, increment in (
            ("cumulative_input_tokens", message_input),
            ("cumulative_output_tokens", message_output),
            ("cumulative_total_tokens", message_total),
        ):
            existing = cls._coerce_int(target.get(key)) or 0
            if increment is None:
                continue
            next_value = existing + max(increment, 0)
            target[key] = next_value

    @classmethod
    def _update_context_tracking_metrics(
        cls,
        target: Dict[str, Any],
        usage_payload: Dict[str, Any],
    ) -> None:
        """Track current and peak context occupancy separately from spend totals."""
        current_total = cls._coerce_int(usage_payload.get("total_tokens"))
        current_input = cls._coerce_int(usage_payload.get("input_tokens"))
        if current_total is None and current_input is None:
            current_total = cls._coerce_int(target.get("total_tokens"))
            current_input = cls._coerce_int(target.get("input_tokens"))
        current_context = current_total if current_total is not None else current_input
        if current_context is None:
            return

        current_context = max(0, int(current_context))
        target["current_context_tokens"] = current_context

        existing_peak = cls._coerce_int(target.get("peak_context_tokens"))
        peak = max(existing_peak or 0, current_context)
        target["peak_context_tokens"] = peak


__all__ = [
    "MODEL_CONTEXT_WINDOWS",
    "RawUsageSummary",
    "UsageCalculator",
    "resolve_context_window",
]
