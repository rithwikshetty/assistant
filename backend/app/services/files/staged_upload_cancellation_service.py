"""Track and cancel in-flight staged file uploads."""

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple


class StagedUploadCancelledError(Exception):
    """Raised when a staged upload is cancelled by the user."""


@dataclass
class _StagedUploadState:
    user_id: str
    task: Optional[asyncio.Task[object]]
    cancelled: bool = False


class StagedUploadCancellationService:
    """In-memory cancellation registry for staged uploads."""

    def __init__(self) -> None:
        self._states: Dict[Tuple[str, str], _StagedUploadState] = {}
        self._pending_cancellations: Set[Tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        upload_id: str,
        user_id: str,
        task: Optional[asyncio.Task[object]],
    ) -> None:
        key = (user_id, upload_id)
        pending_cancel = False
        async with self._lock:
            pending_cancel = key in self._pending_cancellations
            if pending_cancel:
                self._pending_cancellations.discard(key)

            self._states[key] = _StagedUploadState(
                user_id=user_id,
                task=task,
                cancelled=pending_cancel,
            )

        if pending_cancel and task and not task.done():
            task.cancel()

    async def unregister(self, *, upload_id: str, user_id: str) -> None:
        key = (user_id, upload_id)
        async with self._lock:
            self._states.pop(key, None)
            self._pending_cancellations.discard(key)

    async def is_cancelled(self, *, upload_id: str, user_id: str) -> bool:
        key = (user_id, upload_id)
        async with self._lock:
            if key in self._pending_cancellations:
                return True
            state = self._states.get(key)
            return bool(state and state.cancelled)

    async def cancel(self, *, upload_id: str, user_id: str) -> bool:
        task: Optional[asyncio.Task[object]] = None
        key = (user_id, upload_id)
        async with self._lock:
            state = self._states.get(key)
            if not state:
                self._pending_cancellations.add(key)
            else:
                state.cancelled = True
                task = state.task

        if task and not task.done():
            task.cancel()
            return True
        return bool(state)


staged_upload_cancellation_service = StagedUploadCancellationService()
