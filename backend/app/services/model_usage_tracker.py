from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Mapping

from .admin.model_usage_recorder import record_model_usage_event
from .provider_costs import estimate_duration_cost, estimate_usage_cost


def _coerce_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _coerce_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        parsed = Decimal(str(value))
    except Exception:
        return Decimal("0")
    return parsed if parsed >= 0 else Decimal("0")


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()  # type: ignore[call-arg]
            if isinstance(dumped, dict):
                return dict(dumped)
        except Exception:
            return {}
    if hasattr(value, "to_dict"):
        try:
            dumped = value.to_dict()  # type: ignore[call-arg]
            if isinstance(dumped, dict):
                return dict(dumped)
        except Exception:
            return {}
    if hasattr(value, "__dict__"):
        try:
            dumped = dict(value.__dict__)
            return dumped
        except Exception:
            return {}
    return {}


def _first_non_null(mapping: Dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return mapping.get(key)
    return None


def _extract_cache_read_tokens(usage_dict: Dict[str, Any]) -> int:
    direct = _coerce_int(
        _first_non_null(
            usage_dict,
            (
                "cache_read_input_tokens",
                "cacheReadInputTokens",
                "cached_tokens",
                "cachedTokens",
            ),
        )
    )
    if direct:
        return direct

    for details_key in ("prompt_tokens_details", "input_tokens_details"):
        details = _as_dict(usage_dict.get(details_key))
        nested = _coerce_int(details.get("cached_tokens"))
        if nested:
            return nested
    return 0


def _extract_cache_creation_tokens(usage_dict: Dict[str, Any]) -> int:
    direct = _coerce_int(
        _first_non_null(
            usage_dict,
            (
                "cache_creation_input_tokens",
                "cacheCreationInputTokens",
            ),
        )
    )
    if direct:
        return direct

    for details_key in ("prompt_tokens_details", "input_tokens_details"):
        details = _as_dict(usage_dict.get(details_key))
        nested = _coerce_int(
            _first_non_null(
                details,
                (
                    "cache_creation_tokens",
                    "cacheCreationTokens",
                ),
            )
        )
        if nested:
            return nested
    return 0


def extract_openai_response_usage(response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    usage_dict = _as_dict(usage)

    input_tokens = _coerce_int(
        _first_non_null(usage_dict, ("input_tokens", "prompt_tokens", "inputTokens", "promptTokens"))
    )
    output_tokens = _coerce_int(
        _first_non_null(
            usage_dict,
            ("output_tokens", "completion_tokens", "outputTokens", "completionTokens"),
        )
    )
    total_tokens = _coerce_int(_first_non_null(usage_dict, ("total_tokens", "totalTokens")))
    if total_tokens <= 0:
        total_tokens = max(0, input_tokens + output_tokens)

    cache_read = _extract_cache_read_tokens(usage_dict)
    cache_creation = _extract_cache_creation_tokens(usage_dict)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "duration_seconds": Decimal("0"),
        "usage_metadata": usage_dict,
    }


def extract_openai_embedding_usage(response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    usage_dict = _as_dict(usage)

    input_tokens = _coerce_int(
        _first_non_null(usage_dict, ("prompt_tokens", "input_tokens", "promptTokens", "inputTokens"))
    )
    total_tokens = _coerce_int(_first_non_null(usage_dict, ("total_tokens", "totalTokens")))
    if total_tokens <= 0:
        total_tokens = input_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": 0,
        "total_tokens": total_tokens,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "duration_seconds": Decimal("0"),
        "usage_metadata": usage_dict,
    }


def extract_openai_transcription_usage(transcription: Any) -> Dict[str, Any]:
    usage = getattr(transcription, "usage", None)
    usage_dict = _as_dict(usage)
    usage_type = str(usage_dict.get("type") or "").strip().lower()

    input_tokens = _coerce_int(_first_non_null(usage_dict, ("input_tokens", "prompt_tokens", "inputTokens")))
    output_tokens = _coerce_int(
        _first_non_null(usage_dict, ("output_tokens", "completion_tokens", "outputTokens"))
    )
    total_tokens = _coerce_int(_first_non_null(usage_dict, ("total_tokens", "totalTokens")))
    if total_tokens <= 0:
        total_tokens = max(0, input_tokens + output_tokens)

    duration_seconds = Decimal("0")
    if usage_type == "duration":
        duration_seconds = _coerce_decimal(_first_non_null(usage_dict, ("seconds", "duration_seconds", "secondsUsed")))

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "duration_seconds": duration_seconds,
        "usage_metadata": usage_dict,
    }


def extract_google_generate_usage(response: Any) -> Dict[str, Any]:
    usage_metadata = getattr(response, "usage_metadata", None)
    usage_dict = _as_dict(usage_metadata)

    input_tokens = _coerce_int(
        _first_non_null(usage_dict, ("prompt_token_count", "promptTokenCount"))
    )
    output_tokens = _coerce_int(
        _first_non_null(usage_dict, ("candidates_token_count", "candidatesTokenCount"))
    )
    total_tokens = _coerce_int(_first_non_null(usage_dict, ("total_token_count", "totalTokenCount")))
    if total_tokens <= 0:
        total_tokens = max(0, input_tokens + output_tokens)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "duration_seconds": Decimal("0"),
        "usage_metadata": usage_dict,
    }


def estimate_model_usage_cost(
    *,
    provider: str,
    model_name: str,
    usage: Dict[str, Any],
) -> Decimal:
    token_cost = estimate_usage_cost(
        provider=provider,
        model_name=model_name,
        input_tokens=_coerce_int(usage.get("input_tokens")),
        output_tokens=_coerce_int(usage.get("output_tokens")),
        total_tokens=_coerce_int(usage.get("total_tokens")),
        cache_creation_tokens=_coerce_int(usage.get("cache_creation_input_tokens")),
        cache_read_tokens=_coerce_int(usage.get("cache_read_input_tokens")),
        allow_fallback=False,
    )
    duration_cost = estimate_duration_cost(
        provider=provider,
        model_name=model_name,
        duration_seconds=usage.get("duration_seconds"),
    )
    return token_cost + duration_cost


def record_estimated_model_usage(
    *,
    provider: str,
    model_name: str,
    operation_type: str,
    usage: Mapping[str, Any] | None,
    analytics_context: Mapping[str, Any] | None = None,
    db: Any = None,
    source: str = "non_chat",
    latency_ms: int | None = None,
) -> Decimal:
    usage_dict = _as_dict(usage)
    resolved_context = dict(analytics_context or {})
    resolved_db = db if db is not None else resolved_context.get("db")

    cost = estimate_model_usage_cost(
        provider=provider,
        model_name=model_name,
        usage=usage_dict,
    )

    record_model_usage_event(
        db=resolved_db,
        source=source,
        operation_type=operation_type,
        provider=provider,
        model_name=model_name,
        user_id=resolved_context.get("user_id"),
        conversation_id=resolved_context.get("conversation_id"),
        project_id=resolved_context.get("project_id"),
        input_tokens=_coerce_int(usage_dict.get("input_tokens")),
        output_tokens=_coerce_int(usage_dict.get("output_tokens")),
        total_tokens=_coerce_int(usage_dict.get("total_tokens")),
        cache_creation_input_tokens=_coerce_int(usage_dict.get("cache_creation_input_tokens")),
        cache_read_input_tokens=_coerce_int(usage_dict.get("cache_read_input_tokens")),
        duration_seconds=usage_dict.get("duration_seconds", 0),
        latency_ms=(_coerce_int(latency_ms) if latency_ms is not None else None),
        cost_usd=cost,
        usage_metadata=usage_dict.get("usage_metadata") if isinstance(usage_dict.get("usage_metadata"), dict) else {},
    )
    return cost


__all__ = [
    "extract_openai_response_usage",
    "extract_openai_embedding_usage",
    "extract_openai_transcription_usage",
    "extract_google_generate_usage",
    "estimate_model_usage_cost",
    "record_estimated_model_usage",
]
