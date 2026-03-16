"""Helpers for cleaning payloads before persistence."""

from __future__ import annotations

from typing import Any


def strip_nul_bytes(value: Any) -> Any:
    """Recursively strip NUL bytes from string payloads."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [strip_nul_bytes(item) for item in value]
    if isinstance(value, dict):
        return {k: strip_nul_bytes(v) for k, v in value.items()}
    return value

