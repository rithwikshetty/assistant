"""Import-compat shim after removing Celery from the open-source runtime."""

from __future__ import annotations

from functools import update_wrapper
from typing import Any, Callable


class _RemovedTask:
    def __init__(self, fn: Callable[..., Any]) -> None:
        self._fn = fn
        update_wrapper(self, fn)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._fn(*args, **kwargs)

    def delay(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Celery has been removed from this build.")

    def apply_async(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Celery has been removed from this build.")


class _CeleryCompat:
    def task(self, *_args: Any, **_kwargs: Any) -> Callable[[Callable[..., Any]], _RemovedTask]:
        def _decorator(fn: Callable[..., Any]) -> _RemovedTask:
            return _RemovedTask(fn)

        return _decorator

    def autodiscover_tasks(self, *_args: Any, **_kwargs: Any) -> list[str]:
        return []


celery_app = _CeleryCompat()
