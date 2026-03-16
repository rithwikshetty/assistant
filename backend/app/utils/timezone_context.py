"""Helpers for user timezone and locale context.

This module centralizes timezone parsing/validation and prompt-time context
generation so chat orchestration and APIs use consistent semantics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo


DEFAULT_REPORTING_TIMEZONE = "UTC"


def normalize_timezone_name(value: Optional[str]) -> Optional[str]:
    """Return a valid IANA timezone name or None.

    Accepts strings like "Australia/Sydney". Invalid or empty values return
    None so callers can safely fall back to UTC.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > 64:
        return None
    try:
        ZoneInfo(cleaned)
    except Exception:
        return None
    return cleaned


def normalize_locale(value: Optional[str]) -> Optional[str]:
    """Return a sanitized locale string (e.g. en-AU) or None."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > 32:
        return None
    return cleaned


def resolve_timezone_name(candidate: Optional[str], fallback: str = DEFAULT_REPORTING_TIMEZONE) -> str:
    """Resolve a candidate timezone to a valid timezone name.

    Falls back to the provided fallback (defaults to UTC) if the candidate is
    missing/invalid.
    """
    normalized = normalize_timezone_name(candidate)
    if normalized:
        return normalized

    fallback_normalized = normalize_timezone_name(fallback)
    return fallback_normalized or DEFAULT_REPORTING_TIMEZONE


def build_prompt_time_context(user_timezone: Optional[str]) -> Tuple[str, str, str]:
    """Build local date/time values for prompt context.

    Returns:
        (current_date_human, current_time_human, effective_timezone)
    """
    effective_timezone = resolve_timezone_name(user_timezone)
    now_local = datetime.now(ZoneInfo(effective_timezone)).replace(microsecond=0)
    current_date = now_local.strftime("%A, %B %d, %Y")
    current_time = now_local.strftime("%I:%M %p").lstrip("0")
    return current_date, current_time, effective_timezone
