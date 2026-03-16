"""No-op model usage recorder for the open-source build."""

from __future__ import annotations

from typing import Any, Dict

MODEL_USAGE_OUTBOX_EVENT = "analytics.model_usage.recorded"
MODEL_USAGE_OUTBOX_EVENT_VERSION = 1


def dispatch_model_usage_outbox_worker(*, force: bool = False) -> bool:
    """Skip analytics worker dispatch in the open-source build."""
    return False


def record_model_usage_event(
    *,
    db: Any = None,
    source: str,
    operation_type: str,
    provider: str | None,
    model_name: str | None,
    user_id: Any | None = None,
    conversation_id: Any | None = None,
    project_id: Any | None = None,
    call_count: int = 1,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    duration_seconds: Decimal | float | int = 0,
    latency_ms: int | None = None,
    cost_usd: Decimal | float | int = 0,
    usage_metadata: Dict[str, Any] | None = None,
    created_at: Any | None = None,
    event_id: str | None = None,
    dispatch_worker: bool = True,
) -> str | None:
    return str(event_id).strip() or None if event_id is not None else None


__all__ = [
    "MODEL_USAGE_OUTBOX_EVENT",
    "MODEL_USAGE_OUTBOX_EVENT_VERSION",
    "record_model_usage_event",
    "dispatch_model_usage_outbox_worker",
]
