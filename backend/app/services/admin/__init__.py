"""No-op analytics compatibility layer.

This open-source build removes the admin analytics surface and disables
background activity capture without forcing a large runtime rewrite.
Modules that still import the recorder can keep doing so safely.
"""

from __future__ import annotations

from typing import Any


class _NullAdminService:
    def __getattr__(self, _name: str) -> Any:
        def _noop(*_args: Any, **_kwargs: Any) -> dict[str, int]:
            return {}

        return _noop


class _NullEventRecorder:
    def __getattr__(self, _name: str) -> Any:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


AdminService = _NullAdminService
AdminEventRecorder = _NullEventRecorder
analytics_event_recorder = _NullEventRecorder()
sync_analytics_event_recorder = analytics_event_recorder

__all__ = [
    "AdminService",
    "AdminEventRecorder",
    "analytics_event_recorder",
    "sync_analytics_event_recorder",
]
