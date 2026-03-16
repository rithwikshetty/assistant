"""Shared datetime formatting helpers."""

from datetime import datetime, timezone
from typing import Optional


def format_utc_z(value: Optional[datetime]) -> Optional[str]:
    """Format a datetime as a UTC ISO-8601 string with trailing 'Z'.

    - Returns None if the input is None.
    - Treats naive datetimes as UTC.
    - Converts tz-aware datetimes to UTC before formatting.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        normalized = value.replace(tzinfo=timezone.utc)
    else:
        normalized = value.astimezone(timezone.utc)
    return normalized.replace(tzinfo=None).isoformat() + "Z"
