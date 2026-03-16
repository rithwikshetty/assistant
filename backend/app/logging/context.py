from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Dict, Iterator, Mapping

CONTEXT_KEYS = ("request_id", "user_id", "conversation_id", "trace_id", "project_id")

_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_USER_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
_CONVERSATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("conversation_id", default=None)
_TRACE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
_PROJECT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("project_id", default=None)

_CONTEXT_VARS: Dict[str, contextvars.ContextVar[str | None]] = {
    "request_id": _REQUEST_ID,
    "user_id": _USER_ID,
    "conversation_id": _CONVERSATION_ID,
    "trace_id": _TRACE_ID,
    "project_id": _PROJECT_ID,
}


def _normalize(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def bind_context(**values: object) -> Dict[str, contextvars.Token[str | None]]:
    tokens: Dict[str, contextvars.Token[str | None]] = {}
    for key, value in values.items():
        var = _CONTEXT_VARS.get(key)
        if var is None:
            continue
        tokens[key] = var.set(_normalize(value))
    return tokens


def reset_context(tokens: Mapping[str, contextvars.Token[str | None]]) -> None:
    for key, token in tokens.items():
        var = _CONTEXT_VARS.get(key)
        if var is None:
            continue
        var.reset(token)


def clear_context(*keys: str) -> None:
    target_keys = keys or CONTEXT_KEYS
    for key in target_keys:
        var = _CONTEXT_VARS.get(key)
        if var is None:
            continue
        var.set(None)


def get_context() -> Dict[str, str]:
    payload: Dict[str, str] = {}
    for key, var in _CONTEXT_VARS.items():
        value = var.get()
        if value is not None:
            payload[key] = value
    return payload


@contextmanager
def context_scope(**values: object) -> Iterator[None]:
    tokens = bind_context(**values)
    try:
        yield
    finally:
        reset_context(tokens)


class ContextFieldsFilter(logging.Filter):
    """Inject request/user/conversation context onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_context()
        for key in CONTEXT_KEYS:
            if not hasattr(record, key):
                setattr(record, key, context.get(key))
        return True
