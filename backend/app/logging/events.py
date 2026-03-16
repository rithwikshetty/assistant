from __future__ import annotations

import logging
from typing import Any, Dict, Mapping

from .context import bind_context, get_context

CATEGORY_ERROR = "error"
CATEGORY_RETRY = "retry"
CATEGORY_TOOL = "tool"
CATEGORY_TIMING = "timing"
CATEGORY_FINAL = "final"


def bind_log_context(**values: object) -> Dict[str, object]:
    """Bind request-scoped context values to contextvars."""
    return bind_context(**values)


def _coerce_level(level: int | str) -> int:
    if isinstance(level, int):
        return level
    normalized = str(level).strip().upper()
    return getattr(logging, normalized, logging.INFO)


def _default_category(level_no: int) -> str:
    if level_no >= logging.ERROR:
        return CATEGORY_ERROR
    if level_no >= logging.WARNING:
        return CATEGORY_RETRY
    return CATEGORY_TIMING


def _clean_fields(fields: Mapping[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        clean[str(key)] = value
    return clean


def log_event(
    logger: logging.Logger,
    level: int | str,
    event: str,
    category: str | None = None,
    *,
    message: str | None = None,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    """Emit a structured log event with stable metadata."""
    level_no = _coerce_level(level)
    event_name = str(event).strip() or "log.event"
    event_category = (category or _default_category(level_no)).strip() or _default_category(level_no)
    payload_fields = _clean_fields(fields)

    extra: Dict[str, Any] = {
        "event": event_name,
        "category": event_category,
        "fields": payload_fields,
    }
    for key, value in get_context().items():
        extra.setdefault(key, value)

    logger.log(level_no, message or event_name, extra=extra, exc_info=exc_info)
