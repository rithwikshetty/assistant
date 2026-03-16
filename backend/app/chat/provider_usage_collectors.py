from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Protocol, runtime_checkable

from ..utils.coerce import coerce_int as _coerce_int


def _canonicalize_usage(raw_usage: Dict[str, Any]) -> Dict[str, int]:
    numeric_entries: Dict[str, int] = {}
    for key, value in raw_usage.items():
        coerced = _coerce_int(value)
        if coerced is not None:
            numeric_entries[key] = coerced

    # Extract nested cached tokens from OpenAI's response structure
    # OpenAI uses: prompt_tokens_details.cached_tokens or input_tokens_details.cached_tokens
    for details_key in ("prompt_tokens_details", "input_tokens_details"):
        details = raw_usage.get(details_key)
        if isinstance(details, dict):
            cached = _coerce_int(details.get("cached_tokens"))
            if cached is not None and "cached_tokens" not in numeric_entries:
                numeric_entries["cached_tokens"] = cached

    # Extract nested reasoning tokens when providers report detailed output usage.
    # OpenAI Responses typically uses `output_tokens_details.reasoning_tokens`.
    for details_key in ("output_tokens_details", "completion_tokens_details"):
        details = raw_usage.get(details_key)
        if isinstance(details, dict):
            reasoning = _coerce_int(details.get("reasoning_tokens"))
            if reasoning is not None and "reasoning_tokens" not in numeric_entries:
                numeric_entries["reasoning_tokens"] = reasoning

    def ensure(target: str, *candidates: str) -> None:
        if target in numeric_entries:
            return
        for candidate in candidates:
            candidate_value = numeric_entries.get(candidate)
            if candidate_value is not None:
                numeric_entries[target] = candidate_value
                return

    ensure("input_tokens", "input_tokens", "prompt_tokens", "inputTokens", "promptTokens")
    ensure("base_input_tokens", "base_input_tokens", "input_tokens", "prompt_tokens", "baseInputTokens")
    ensure("output_tokens", "output_tokens", "completion_tokens", "outputTokens", "completionTokens")
    ensure("total_tokens", "total_tokens", "totalTokens")
    ensure("cache_creation_input_tokens", "cache_creation_input_tokens", "cacheCreationInputTokens")
    # Map cache read fields to a canonical key across provider payload variants.
    ensure("cache_read_input_tokens", "cache_read_input_tokens", "cacheReadInputTokens", "cached_tokens", "cachedTokens")
    ensure("context_input_tokens", "context_input_tokens", "input_tokens", "prompt_tokens")
    ensure("context_output_tokens", "context_output_tokens", "output_tokens", "completion_tokens")
    ensure("context_total_tokens", "context_total_tokens", "total_tokens")
    ensure("reasoning_tokens", "reasoning_tokens", "reasoningTokens")

    if "total_tokens" not in numeric_entries and "input_tokens" in numeric_entries:
        total = numeric_entries["input_tokens"] + numeric_entries.get("output_tokens", 0)
        numeric_entries["total_tokens"] = total

    if "base_input_tokens" not in numeric_entries and "input_tokens" in numeric_entries:
        numeric_entries["base_input_tokens"] = numeric_entries["input_tokens"]

    return numeric_entries


def _sanitize_payload(raw: Dict[str, Any], usage_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if usage_data is None:
        return None

    canonical = _canonicalize_usage(usage_data)
    if not canonical:
        return None

    payload = dict(raw)
    payload["usage"] = canonical
    return payload


@runtime_checkable
class ProviderUsageCollector(Protocol):
    provider: str

    def collect(self, raw_responses: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ...


class BaseUsageCollector:
    provider = "default"

    def collect(self, raw_responses: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:  # pragma: no cover - thin wrapper
        prepared: List[Dict[str, Any]] = []
        for raw in raw_responses:
            if not isinstance(raw, dict):
                continue
            usage = self._extract_usage(raw)
            sanitized = _sanitize_payload(raw, usage)
            if sanitized is not None:
                prepared.append(sanitized)
        return prepared

    def _extract_usage(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        usage = raw.get("usage")
        return usage if isinstance(usage, dict) else None


_DEFAULT_COLLECTOR = BaseUsageCollector()


def resolve_usage_collector(provider: Optional[str]) -> ProviderUsageCollector:
    _ = provider
    return _DEFAULT_COLLECTOR


__all__ = [
    "ProviderUsageCollector",
    "resolve_usage_collector",
]
