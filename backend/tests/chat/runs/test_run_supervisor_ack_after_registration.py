"""LAT-001: Verify queue acknowledgement is deferred until after stream registration."""

from __future__ import annotations
from typing import List

import pytest


@pytest.mark.asyncio
async def test_on_registered_called_after_registration_before_task_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """on_registered fires between register_stream + snapshot and the task body."""
    from app.chat.services import stream_runner

    call_order: List[str] = []

    async def _fake_register_stream(*args, **kwargs):
        call_order.append("register_stream")

    async def _fake_persist_snapshot(**kwargs):
        call_order.append("persist_snapshot")

    async def _fake_run_chat_direct(*args, **kwargs):
        call_order.append("run_chat_direct")

    async def _fake_on_registered():
        call_order.append("on_registered")

    monkeypatch.setattr(stream_runner, "register_stream", _fake_register_stream)
    monkeypatch.setattr(stream_runner, "_persist_initial_running_snapshot", _fake_persist_snapshot)
    monkeypatch.setattr("app.chat.tasks.run_chat_direct", _fake_run_chat_direct)

    await stream_runner.launch_chat_stream_and_wait(
        conversation_id="conv-1",
        user_id="user-1",
        user_message_id="msg-1",
        run_id="run-1",
        on_registered=_fake_on_registered,
    )

    assert "register_stream" in call_order
    assert "persist_snapshot" in call_order
    assert "on_registered" in call_order

    # on_registered must come AFTER registration and snapshot
    reg_idx = call_order.index("register_stream")
    snap_idx = call_order.index("persist_snapshot")
    ack_idx = call_order.index("on_registered")
    assert reg_idx < ack_idx, "on_registered must fire after register_stream"
    assert snap_idx < ack_idx, "on_registered must fire after persist_snapshot"


@pytest.mark.asyncio
async def test_on_registered_not_called_when_snapshot_persist_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot failure must fail closed before queue acknowledgement."""
    from app.chat.services import stream_runner

    on_registered_called = False
    cleanup_called = False

    async def _fake_register_stream(*args, **kwargs):
        return None

    async def _failing_snapshot(**kwargs):
        raise RuntimeError("snapshot exploded")

    async def _fake_on_registered():
        nonlocal on_registered_called
        on_registered_called = True

    async def _fake_schedule_cleanup(conversation_id: str, delay=None):
        nonlocal cleanup_called
        del conversation_id, delay
        cleanup_called = True

    monkeypatch.setattr(stream_runner, "register_stream", _fake_register_stream)
    monkeypatch.setattr(stream_runner, "_persist_initial_running_snapshot", _failing_snapshot)
    monkeypatch.setattr(stream_runner, "schedule_cleanup", _fake_schedule_cleanup)
    monkeypatch.setattr(stream_runner, "get_local_stream", lambda conversation_id: None)

    with pytest.raises(RuntimeError, match="snapshot exploded"):
        await stream_runner.launch_chat_stream_and_wait(
            conversation_id="conv-1",
            user_id="user-1",
            user_message_id="msg-1",
            run_id="run-1",
            on_registered=_fake_on_registered,
        )

    assert on_registered_called is False
    assert cleanup_called is True


@pytest.mark.asyncio
async def test_on_registered_not_called_when_registration_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """If register_stream raises, on_registered must NOT be called."""
    from app.chat.services import stream_runner

    on_registered_called = False

    async def _failing_register(*args, **kwargs):
        raise RuntimeError("registration exploded")

    async def _fake_on_registered():
        nonlocal on_registered_called
        on_registered_called = True

    monkeypatch.setattr(stream_runner, "register_stream", _failing_register)

    with pytest.raises(RuntimeError, match="registration exploded"):
        await stream_runner.launch_chat_stream_and_wait(
            conversation_id="conv-1",
            user_id="user-1",
            user_message_id="msg-1",
            run_id="run-1",
            on_registered=_fake_on_registered,
        )

    assert not on_registered_called, "on_registered must not be called when registration fails"


@pytest.mark.asyncio
async def test_on_registered_none_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passing on_registered=None (the default) must not crash."""
    from app.chat.services import stream_runner

    async def _fake_register_stream(*args, **kwargs):
        pass

    async def _fake_persist_snapshot(**kwargs):
        pass

    monkeypatch.setattr(stream_runner, "register_stream", _fake_register_stream)
    monkeypatch.setattr(stream_runner, "_persist_initial_running_snapshot", _fake_persist_snapshot)
    monkeypatch.setattr(
        "app.chat.tasks.run_chat_direct",
        lambda *args, **kwargs: _fake_persist_snapshot(),
    )

    # Should not raise
    await stream_runner.launch_chat_stream_and_wait(
        conversation_id="conv-1",
        user_id="user-1",
        user_message_id="msg-1",
        run_id="run-1",
        on_registered=None,
    )
