"""LAT-002: Verify submit locks the conversation path before mutating state."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi import HTTPException

from app.chat.services.submit_runtime_service import _ensure_state_row


class _TrackingQuery:
    """Minimal stub that records whether with_for_update() was called."""

    def __init__(self, result: Any = None) -> None:
        self._result = result
        self.for_update_called = False

    def filter(self, *args, **kwargs) -> "_TrackingQuery":
        return self

    def with_for_update(self, **kwargs) -> "_TrackingQuery":
        self.for_update_called = True
        return self

    def first(self) -> Any:
        return self._result


class _FakeSession:
    """Minimal session stub that intercepts query() calls."""

    def __init__(self, *, existing_conversation: Any = None, existing_state: Any = None) -> None:
        self._existing_conversation = existing_conversation
        self._existing_state = existing_state
        self.tracking_queries: List[_TrackingQuery] = []
        self.added: List[Any] = []
        self.flushed = False

    def query(self, model_class: Any) -> _TrackingQuery:
        name = getattr(model_class, "__name__", "")
        if name == "Conversation":
            query = _TrackingQuery(result=self._existing_conversation)
        else:
            query = _TrackingQuery(result=self._existing_state)
        self.tracking_queries.append(query)
        return query

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flushed = True


def test_ensure_state_row_uses_for_update_when_row_exists() -> None:
    """Existing submits must lock both the conversation and its state row."""
    fake_conversation = SimpleNamespace(id="conv-1")
    fake_state = SimpleNamespace(
        conversation_id="conv-1",
        active_run_id=None,
        awaiting_user_input=False,
    )
    session = _FakeSession(existing_conversation=fake_conversation, existing_state=fake_state)

    result = _ensure_state_row(session, "conv-1")

    assert result is fake_state
    assert len(session.tracking_queries) == 2
    assert session.tracking_queries[0].for_update_called is True, (
        "LAT-002: the parent conversation row must be locked to serialize first-submit races"
    )
    assert session.tracking_queries[1].for_update_called is True, (
        "LAT-002: the state row must also be locked when it already exists"
    )


def test_ensure_state_row_creates_when_missing() -> None:
    """Missing state rows should still be serialized by the conversation lock."""
    fake_conversation = SimpleNamespace(id="conv-new")
    session = _FakeSession(existing_conversation=fake_conversation, existing_state=None)

    result = _ensure_state_row(session, "conv-new")

    assert result is not None
    assert len(session.added) == 1
    assert session.flushed is True
    assert len(session.tracking_queries) == 2
    assert session.tracking_queries[0].for_update_called is True, (
        "LAT-002: the conversation lock must cover first-time ConversationState creation"
    )
    assert session.tracking_queries[1].for_update_called is True, (
        "FOR UPDATE must still be attempted even if the state row ends up not existing"
    )


def test_ensure_state_row_raises_when_conversation_missing() -> None:
    session = _FakeSession(existing_conversation=None, existing_state=None)

    with pytest.raises(HTTPException, match="Conversation not found"):
        _ensure_state_row(session, "conv-missing")
