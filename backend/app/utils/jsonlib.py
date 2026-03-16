"""
Fast JSON serialization helpers with optional orjson acceleration.

Provides `json_dumps` returning a str, with compact separators and
handling of non-serializable objects via default=str as a safe fallback.
"""
from __future__ import annotations

from typing import Any

try:
    import orjson  # type: ignore

    def json_dumps(obj: Any) -> str:
        # orjson returns bytes; OPT_NON_STR_KEYS allows dicts with non-str keys safely
        # OPT_UTC_Z adds 'Z' for UTC datetimes when encoded by orjson (if encountered)
        return orjson.dumps(
            obj,
            option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_SORT_KEYS,
            default=str,
        ).decode("utf-8")

except Exception:  # pragma: no cover - optional dependency
    import json as _json

    def json_dumps(obj: Any) -> str:
        return _json.dumps(obj, separators=(",", ":"), default=str)


__all__ = ["json_dumps"]

