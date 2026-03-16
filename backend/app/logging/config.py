from __future__ import annotations

import logging
import sys
import threading
from typing import Literal

from .context import ContextFieldsFilter
from .events import log_event
from .formatters import JsonEventFormatter, PrettyEventFormatter

_LOGGING_CONFIGURED = False
_LOCK = threading.Lock()


def _to_level(level_name: str) -> int:
    normalized = (level_name or "INFO").strip().upper()
    return getattr(logging, normalized, logging.INFO)


def _normalize_level_name(level_name: str) -> str:
    normalized = (level_name or "INFO").strip().upper()
    if normalized in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
        return normalized
    return "INFO"


def _resolve_format(mode: str, is_tty: bool) -> Literal["pretty", "json"]:
    normalized = (mode or "auto").strip().lower()
    if normalized == "auto":
        return "pretty" if is_tty else "json"
    if normalized in {"pretty", "json"}:
        return normalized
    return "pretty" if is_tty else "json"


def _resolve_color(mode: str, is_tty: bool) -> bool:
    normalized = (mode or "auto").strip().lower()
    if normalized in {"on", "true", "1", "always"}:
        return True
    if normalized in {"off", "false", "0", "never"}:
        return False
    return is_tty


def _clear_logger_handlers(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = True
    return logger


def configure_logging(component: str = "api") -> None:
    """Configure one cohesive logging stack for API + infra loggers."""
    global _LOGGING_CONFIGURED

    with _LOCK:
        if _LOGGING_CONFIGURED:
            return

        from ..config.settings import settings

        is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
        effective_format = _resolve_format(settings.log_format, is_tty)
        use_color = _resolve_color(settings.log_color, is_tty)
        level_name = _normalize_level_name(settings.log_level)
        root_level = _to_level(level_name)

        formatter = (
            JsonEventFormatter()
            if effective_format == "json"
            else PrettyEventFormatter(use_color=use_color)
        )

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        handler.addFilter(ContextFieldsFilter())

        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(root_level)
        root_logger.addHandler(handler)

        logging.captureWarnings(True)

        # Normalize primary application loggers.
        for logger_name in ("app", "backend.app"):
            app_logger = _clear_logger_handlers(logger_name)
            app_logger.setLevel(root_level)

        # Normalize framework/infrastructure loggers into root handler stack.
        framework_levels = {
            "uvicorn": root_level,
            "uvicorn.error": root_level,
            "uvicorn.access": logging.WARNING,
            "gunicorn": root_level,
            "gunicorn.error": root_level,
            "gunicorn.access": logging.WARNING,
            "celery": root_level,
            "celery.app.trace": root_level,
            "sqlalchemy.engine": _to_level(settings.log_sqlalchemy_level),
            "sqlalchemy.pool": _to_level(settings.log_sqlalchemy_level),
        }
        for logger_name, logger_level in framework_levels.items():
            logger = _clear_logger_handlers(logger_name)
            logger.setLevel(logger_level)

        _LOGGING_CONFIGURED = True

        log_event(
            logging.getLogger(__name__),
            "INFO",
            "logging.configured",
            "final",
            component=component,
            format=effective_format,
            log_level=level_name,
            color_enabled=use_color,
        )
