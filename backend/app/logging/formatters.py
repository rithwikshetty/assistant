from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from .context import CONTEXT_KEYS
from .events import (
    CATEGORY_ERROR,
    CATEGORY_FINAL,
    CATEGORY_RETRY,
    CATEGORY_TIMING,
    CATEGORY_TOOL,
)

_FIELD_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


class _BaseEventFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        del datefmt
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _event(record: logging.LogRecord) -> str:
        raw_event = getattr(record, "event", None)
        if isinstance(raw_event, str) and raw_event.strip():
            return raw_event.strip()
        message = record.getMessage()
        return message.strip() if isinstance(message, str) and message.strip() else record.name

    @staticmethod
    def _category(record: logging.LogRecord) -> str:
        raw_category = getattr(record, "category", None)
        if isinstance(raw_category, str) and raw_category.strip():
            return raw_category.strip()
        if record.levelno >= logging.ERROR:
            return CATEGORY_ERROR
        if record.levelno >= logging.WARNING:
            return CATEGORY_RETRY
        return CATEGORY_TIMING

    @staticmethod
    def _message(record: logging.LogRecord, event_name: str) -> str | None:
        text = record.getMessage()
        if not isinstance(text, str):
            return None
        stripped = text.strip()
        if not stripped or stripped == event_name:
            return None
        return stripped

    @staticmethod
    def _context_fields(record: logging.LogRecord) -> Dict[str, str]:
        data: Dict[str, str] = {}
        for key in CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                data[key] = text
        return data

    @staticmethod
    def _event_fields(record: logging.LogRecord) -> Dict[str, Any]:
        raw_fields = getattr(record, "fields", None)
        if not isinstance(raw_fields, dict):
            return {}
        return {str(k): v for k, v in raw_fields.items() if v is not None}


class JsonEventFormatter(_BaseEventFormatter):
    """Structured JSON formatter for non-TTY environments."""

    def format(self, record: logging.LogRecord) -> str:
        event_name = self._event(record)
        category = self._category(record)
        context = self._context_fields(record)
        fields = self._event_fields(record)

        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "event": event_name,
            "category": category,
        }

        message = self._message(record, event_name)
        if message is not None:
            payload["message"] = message

        for key in CONTEXT_KEYS:
            if key in context:
                payload[key] = context[key]

        if fields:
            payload["fields"] = fields

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True, default=str, separators=(",", ":"))


class PrettyEventFormatter(_BaseEventFormatter):
    """Concise human-readable formatter with category-aware colors."""

    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"

    CATEGORY_COLORS = {
        CATEGORY_ERROR: "\x1b[31m",
        "fatal": "\x1b[31m",
        CATEGORY_RETRY: "\x1b[33m",
        "warn": "\x1b[33m",
        CATEGORY_TOOL: "\x1b[36m",
        CATEGORY_TIMING: "\x1b[34m",
        CATEGORY_FINAL: "\x1b[32m",
    }

    LEVEL_COLORS = {
        "DEBUG": "\x1b[36m",
        "INFO": "\x1b[37m",
        "WARNING": "\x1b[33m",
        "ERROR": "\x1b[31m",
        "CRITICAL": "\x1b[31m",
    }

    def __init__(self, *, use_color: bool | None = None) -> None:
        super().__init__()
        self._use_color = self._resolve_use_color(use_color)

    @staticmethod
    def _env_bool(raw_value: str | None) -> bool | None:
        if raw_value is None:
            return None
        value = raw_value.strip().lower()
        if value in {"1", "true", "yes", "on", "always"}:
            return True
        if value in {"0", "false", "no", "off", "never"}:
            return False
        return None

    @classmethod
    def _resolve_use_color(cls, use_color: bool | None) -> bool:
        if use_color is not None:
            return bool(use_color)
        env_color = cls._env_bool(os.getenv("LOG_COLOR"))
        if env_color is not None:
            return env_color
        return bool(getattr(sys.stdout, "isatty", lambda: False)())

    def _paint(self, text: str, color: str) -> str:
        if not self._use_color:
            return text
        return f"{color}{text}{self.RESET}"

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value)
        if not text:
            return '""'
        if _FIELD_RE.fullmatch(text):
            return text
        return json.dumps(text, ensure_ascii=True)

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record)
        event_name = self._event(record)
        category = self._category(record)
        message = self._message(record, event_name)
        context = self._context_fields(record)
        fields = self._event_fields(record)

        level_text = self._paint(record.levelname, f"{self.BOLD}{self.LEVEL_COLORS.get(record.levelname, '\\x1b[37m')}")
        event_text = self._paint(event_name, self.CATEGORY_COLORS.get(category, "\x1b[37m"))

        parts = [timestamp, level_text, event_text, f"category={category}"]

        for key in CONTEXT_KEYS:
            value = context.get(key)
            if value is None:
                continue
            parts.append(f"{key}={self._format_value(value)}")

        for key in sorted(fields):
            parts.append(f"{key}={self._format_value(fields[key])}")

        if message is not None:
            parts.append(f"message={self._format_value(message)}")

        rendered = " ".join(parts)
        if record.exc_info:
            rendered = f"{rendered}\n{self.formatException(record.exc_info)}"
        return rendered
