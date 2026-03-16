import json
import logging

from app.logging.context import CONTEXT_KEYS
from app.logging.events import (
    CATEGORY_ERROR,
    CATEGORY_FINAL,
    CATEGORY_RETRY,
    CATEGORY_TIMING,
    CATEGORY_TOOL,
)
from app.logging.formatters import JsonEventFormatter, PrettyEventFormatter


def _record(
    *,
    level: int = logging.INFO,
    event: str = "test.event",
    category: str = CATEGORY_TIMING,
    message: str = "test.event",
    fields: dict | None = None,
    exc_info=None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=exc_info,
    )
    record.event = event
    record.category = category
    record.fields = fields or {}
    record.request_id = "req-123"
    return record


def test_pretty_formatter_category_color_mapping() -> None:
    formatter = PrettyEventFormatter(use_color=True)
    expected = {
        CATEGORY_ERROR: "\x1b[31m",
        CATEGORY_RETRY: "\x1b[33m",
        CATEGORY_TOOL: "\x1b[36m",
        CATEGORY_TIMING: "\x1b[34m",
        CATEGORY_FINAL: "\x1b[32m",
    }

    for category, color in expected.items():
        assert formatter.CATEGORY_COLORS[category] == color
        rendered = formatter.format(_record(event=f"event.{category}", category=category))
        assert f"{color}event.{category}" in rendered


def test_json_formatter_emits_parseable_payload_without_ansi() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        exc_info = (type(exc), exc, exc.__traceback__)

    formatter = JsonEventFormatter()
    rendered = formatter.format(
        _record(
            level=logging.ERROR,
            event="http.unhandled_exception",
            category=CATEGORY_ERROR,
            message="server failed",
            fields={"status": 500, "duration_ms": 12.4},
            exc_info=exc_info,
        )
    )

    assert "\x1b[" not in rendered
    payload = json.loads(rendered)
    assert payload["event"] == "http.unhandled_exception"
    assert payload["category"] == CATEGORY_ERROR
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "test.logger"
    assert payload["fields"]["status"] == 500
    assert payload["fields"]["duration_ms"] == 12.4
    assert payload["request_id"] == "req-123"
    assert "timestamp" in payload
    assert "exception" in payload

    for key in CONTEXT_KEYS:
        if key == "request_id":
            continue
        assert key not in payload
