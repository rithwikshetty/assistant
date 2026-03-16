"""Shared type-coercion helpers."""

import math
from typing import Any, Optional
from uuid import UUID


def coerce_int(value: Any) -> Optional[int]:
    """Coerce a value to int, returning None for invalid/missing inputs.

    Handles None, bool, int, float (rejecting NaN/inf), and numeric strings.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or not math.isfinite(value):
            return None
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(float(stripped))
        except ValueError:
            return None
    return None


def normalize_non_empty_string(raw: Any) -> Optional[str]:
    """Return trimmed string if non-empty, else None."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value if value else None


def normalize_uuid_string(raw: Any) -> Optional[str]:
    """Return a canonical UUID string or None when the input is invalid."""
    value = normalize_non_empty_string(raw)
    if value is None:
        return None
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError):
        return None


def coerce_non_negative_int(raw: Any) -> Optional[int]:
    """Coerce to a non-negative int, returning None on failure."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, float) and raw >= 0:
        return max(0, int(raw))
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        try:
            parsed = int(float(value))
        except ValueError:
            return None
        return max(0, parsed)
    return None
