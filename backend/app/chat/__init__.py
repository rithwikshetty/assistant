"""Chat package exports.

Keep this module side-effect free so non-API imports (for example Celery task
autodiscovery that imports chat services) do not eagerly import route modules
and create circular imports.
"""

from __future__ import annotations

from typing import Any

__all__ = ["router"]


def __getattr__(name: str) -> Any:
    if name == "router":
        from .routes import router

        return router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
