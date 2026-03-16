from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import project_permissions


class _FailingSyncDb:
    def query(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("query should not be called for malformed UUIDs")


class _FailingAsyncDb:
    async def scalar(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("scalar should not be called for malformed UUIDs")


def test_require_conversation_owner_rejects_invalid_uuid() -> None:
    with pytest.raises(HTTPException) as exc_info:
        project_permissions.require_conversation_owner(
            SimpleNamespace(id="user-1"),
            "ws",
            _FailingSyncDb(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.asyncio
async def test_require_conversation_owner_async_rejects_invalid_uuid() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await project_permissions.require_conversation_owner_async(
            SimpleNamespace(id="user-1"),
            "ws",
            _FailingAsyncDb(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"
