from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.chat.services import run_runtime_service


class _FailingSyncDb:
    def query(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("query should not be called for malformed UUIDs")


class _FailingAsyncDb:
    async def scalar(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("scalar should not be called for malformed UUIDs")


def test_require_accessible_conversation_sync_rejects_invalid_uuid() -> None:
    with pytest.raises(HTTPException) as exc_info:
        run_runtime_service.require_accessible_conversation_sync(
            _FailingSyncDb(),
            current_user=SimpleNamespace(id="user-1", role="member"),
            conversation_id="ws",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.asyncio
async def test_require_accessible_conversation_async_rejects_invalid_uuid() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await run_runtime_service.require_accessible_conversation_async(
            _FailingAsyncDb(),
            current_user=SimpleNamespace(id="user-1", role="member"),
            conversation_id="ws",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.asyncio
async def test_require_accessible_run_async_rejects_invalid_uuid() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await run_runtime_service.require_accessible_run_async(
            _FailingAsyncDb(),
            current_user=SimpleNamespace(id="user-1", role="member"),
            run_id="ws",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Run not found"
