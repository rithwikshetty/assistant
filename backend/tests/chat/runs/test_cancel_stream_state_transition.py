"""LAT-003: Verify persisted cancel clears active_run_id, snapshot, and awaiting_user_input."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict

import pytest


def _make_fake_run(run_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        status="paused",
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        finished_at=None,
    )


def _make_fake_state(conversation_id: str, active_run_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id=conversation_id,
        active_run_id=active_run_id,
        awaiting_user_input=True,
    )


def _build_fake_async_session(
    fake_run,
    fake_state,
    *,
    snapshot_run_id=None,
    on_snapshot_delete=None,
    queued_turns=None,
    queued_runs_by_id=None,
    queued_messages_by_id=None,
):
    """Build an AsyncSessionLocal replacement for cancel tests."""
    from app.database.models import (
        ChatRun as CR,
        ChatRunQueuedTurn as CRQT,
        ChatRunSnapshot as CRS,
        ConversationState as CS,
        Message as MSG,
    )

    queued_turns = list(queued_turns or [])
    queued_runs_by_id = dict(queued_runs_by_id or {})
    queued_messages_by_id = dict(queued_messages_by_id or {})

    class _FakeSyncQuery:
        def __init__(self, model_class):
            self._model_class = model_class
            self._filters: list[Any] = []

        def filter(self, *args, **kwargs):
            self._filters.extend(args)
            return self

        def first(self):
            if self._model_class is CS:
                return fake_state
            if self._model_class is CR:
                return fake_run
            if self._model_class is MSG:
                if not queued_messages_by_id:
                    return None
                return next(iter(queued_messages_by_id.values()))
            return None

        def all(self):
            if self._model_class is CRQT:
                return queued_turns
            if self._model_class is CR:
                return list(queued_runs_by_id.values())
            if self._model_class is MSG:
                return list(queued_messages_by_id.values())
            return []

        def delete(self, **kwargs):
            requested_run_id = None
            for clause in self._filters:
                left = getattr(clause, "left", None)
                right = getattr(clause, "right", None)
                if "run_id" not in str(left):
                    continue
                requested_run_id = getattr(right, "value", None)
                break
            should_delete = (
                self._model_class is CRS
                and requested_run_id is not None
                and str(requested_run_id) == str(snapshot_run_id)
            )
            if should_delete and on_snapshot_delete is not None:
                on_snapshot_delete()

    class _FakeSyncSession:
        def query(self, model_class):
            return _FakeSyncQuery(model_class)

    class _FakeAsyncSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def scalar(self, query):
            return fake_run

        async def run_sync(self, fn):
            fn(_FakeSyncSession())

        async def commit(self):
            pass

    return _FakeAsyncSession


@pytest.mark.asyncio
async def test_persisted_cancel_clears_active_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a run is cancelled without an active Redis stream, the
    persisted cancel path must clear ConversationState.active_run_id,
    awaiting_user_input, and the ChatRunSnapshot.
    """
    from app.chat.services import cancel_stream_service

    cancelled_run_id = "run-abc"
    conversation_id = "conv-123"

    fake_run = _make_fake_run(cancelled_run_id)
    fake_state = _make_fake_state(conversation_id, cancelled_run_id)
    snapshot_deleted = False

    def _on_snapshot_delete():
        nonlocal snapshot_deleted
        snapshot_deleted = True

    FakeSession = _build_fake_async_session(
        fake_run,
        fake_state,
        snapshot_run_id=cancelled_run_id,
        on_snapshot_delete=_on_snapshot_delete,
    )

    async def _fake_authz(*args, **kwargs):
        pass

    async def _fake_stream_status(conv_id):
        return "not_found"

    monkeypatch.setattr(cancel_stream_service, "require_conversation_owner_async", _fake_authz)
    monkeypatch.setattr(cancel_stream_service, "get_stream_status", _fake_stream_status)
    monkeypatch.setattr(cancel_stream_service, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(cancel_stream_service, "append_event_sync", lambda *args, **kwargs: None)

    user = SimpleNamespace(id="user-1")
    result = await cancel_stream_service.cancel_conversation_stream(
        user=user,
        conversation_id=conversation_id,
        cancel_source="test",
        log_name="test.cancel",
    )

    assert result["status"] == "cancelled"
    assert result["persisted"] is True

    # Run status should be cancelled
    assert fake_run.status == "cancelled"
    assert fake_run.finished_at is not None

    # LAT-003: active_run_id must be cleared
    assert fake_state.active_run_id is None, (
        "LAT-003: active_run_id must be cleared when the cancelled run matches"
    )
    assert fake_state.awaiting_user_input is False, (
        "LAT-003: awaiting_user_input must be cleared on cancel"
    )
    assert snapshot_deleted is True, (
        "LAT-003: ChatRunSnapshot must be deleted on persisted cancel"
    )


@pytest.mark.asyncio
async def test_persisted_cancel_preserves_active_run_id_when_different(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancelling an older run must not clear state or snapshot for another active run."""
    from app.chat.services import cancel_stream_service

    cancelled_run_id = "run-old"
    different_active_run = "run-new"

    fake_run = _make_fake_run(cancelled_run_id)
    fake_state = _make_fake_state("conv-1", different_active_run)
    snapshot_deleted = False

    def _on_snapshot_delete():
        nonlocal snapshot_deleted
        snapshot_deleted = True

    FakeSession = _build_fake_async_session(
        fake_run,
        fake_state,
        snapshot_run_id=different_active_run,
        on_snapshot_delete=_on_snapshot_delete,
    )

    async def _fake_authz(*args, **kwargs):
        pass

    async def _fake_stream_status(conv_id):
        return "not_found"

    monkeypatch.setattr(cancel_stream_service, "require_conversation_owner_async", _fake_authz)
    monkeypatch.setattr(cancel_stream_service, "get_stream_status", _fake_stream_status)
    monkeypatch.setattr(cancel_stream_service, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(cancel_stream_service, "append_event_sync", lambda *args, **kwargs: None)

    user = SimpleNamespace(id="user-1")
    await cancel_stream_service.cancel_conversation_stream(
        user=user,
        conversation_id="conv-1",
        cancel_source="test",
        log_name="test.cancel",
    )

    # active_run_id should be preserved since it points to a different run
    assert fake_state.active_run_id == different_active_run, (
        "active_run_id pointing to a different run must not be cleared"
    )
    assert fake_state.awaiting_user_input is True, (
        "awaiting_user_input must be preserved when another run remains active"
    )
    assert snapshot_deleted is False, (
        "Cancelling a non-active run must not delete the current run snapshot"
    )


@pytest.mark.asyncio
async def test_running_cancel_clears_queued_turns_and_hides_queued_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.chat.services import cancel_stream_service

    cancelled_run_id = "run-live"
    conversation_id = "conv-live"
    queued_run = SimpleNamespace(id="run-queued", status="queued", finished_at=None)
    queued_message = SimpleNamespace(
        id="msg-queued",
        status="completed",
        completed_at=None,
    )
    queued_turn = SimpleNamespace(
        run_id="run-queued",
        user_message_id="msg-queued",
        status="queued",
    )

    fake_run = _make_fake_run(cancelled_run_id)
    fake_run.status = "running"
    fake_state = _make_fake_state(conversation_id, cancelled_run_id)
    request_cancel_calls: list[str] = []

    FakeSession = _build_fake_async_session(
        fake_run,
        fake_state,
        queued_turns=[queued_turn],
        queued_runs_by_id={"run-queued": queued_run},
        queued_messages_by_id={"msg-queued": queued_message},
    )

    async def _fake_authz(*args, **kwargs):
        pass

    async def _fake_stream_status(conv_id):
        return "running"

    async def _fake_request_cancel(conv_id):
        request_cancel_calls.append(conv_id)

    monkeypatch.setattr(cancel_stream_service, "require_conversation_owner_async", _fake_authz)
    monkeypatch.setattr(cancel_stream_service, "get_stream_status", _fake_stream_status)
    monkeypatch.setattr(cancel_stream_service, "request_cancel", _fake_request_cancel)
    monkeypatch.setattr(cancel_stream_service, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(cancel_stream_service, "append_event_sync", lambda *args, **kwargs: None)

    user = SimpleNamespace(id="user-1")
    result = await cancel_stream_service.cancel_conversation_stream(
        user=user,
        conversation_id=conversation_id,
        cancel_source="test",
        log_name="test.cancel",
    )

    assert result["status"] == "cancelled"
    assert result["persisted"] is True
    assert request_cancel_calls == [conversation_id]
    assert queued_turn.status == "cancelled"
    assert queued_run.status == "cancelled"
    assert queued_run.finished_at is not None
    assert queued_message.status == "cancelled"
    assert queued_message.completed_at is not None
