import asyncio

import pytest

from app.chat.services import stream_runner
from app.services.chat_streams import StreamRegistrationConflictError


@pytest.mark.asyncio
async def test_launch_chat_stream_starts_worker_only_after_register(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    async def _fake_run_chat_direct(  # type: ignore[no-untyped-def]
        conversation_id,
        user_id,
        user_message_id,
        *,
        resume_assistant_message_id=None,
    ):
        del conversation_id, user_id, user_message_id, resume_assistant_message_id
        events.append("run_started")

    async def _fake_register_stream(  # type: ignore[no-untyped-def]
        conversation_id,
        user_id,
        user_message_id,
        run_id,
        task,
        context=None,
        current_step=None,
    ):
        del conversation_id, user_id, user_message_id, run_id, context
        assert current_step == "Starting"
        events.append("register_started")
        await asyncio.sleep(0)
        assert "run_started" not in events
        assert task.done() is False
        events.append("register_finished")
        return None

    async def _fake_persist_initial_running_snapshot(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["status_label"] == "Starting"
        events.append("snapshot_persisted")

    monkeypatch.setattr("app.chat.tasks.run_chat_direct", _fake_run_chat_direct)
    monkeypatch.setattr(stream_runner, "register_stream", _fake_register_stream)
    monkeypatch.setattr(
        stream_runner,
        "_persist_initial_running_snapshot",
        _fake_persist_initial_running_snapshot,
    )

    await stream_runner.launch_chat_stream(
        conversation_id="conv_1",
        user_id="user_1",
        user_message_id="msg_1",
        run_id="run_1",
    )
    await asyncio.sleep(0)

    assert events == ["register_started", "register_finished", "snapshot_persisted", "run_started"]


@pytest.mark.asyncio
async def test_launch_chat_stream_cancels_task_on_register_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = {"run": 0}

    async def _fake_run_chat_direct(  # type: ignore[no-untyped-def]
        conversation_id,
        user_id,
        user_message_id,
        *,
        resume_assistant_message_id=None,
    ):
        del conversation_id, user_id, user_message_id, resume_assistant_message_id
        call_count["run"] += 1

    async def _conflicting_register_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise StreamRegistrationConflictError("already running")

    monkeypatch.setattr("app.chat.tasks.run_chat_direct", _fake_run_chat_direct)
    monkeypatch.setattr(stream_runner, "register_stream", _conflicting_register_stream)

    with pytest.raises(StreamRegistrationConflictError):
        await stream_runner.launch_chat_stream(
            conversation_id="conv_1",
            user_id="user_1",
            user_message_id="msg_1",
            run_id="run_1",
        )
    await asyncio.sleep(0)

    assert call_count["run"] == 0


@pytest.mark.asyncio
async def test_launch_chat_stream_marks_resume_starts_as_resuming(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    async def _fake_run_chat_direct(  # type: ignore[no-untyped-def]
        conversation_id,
        user_id,
        user_message_id,
        *,
        resume_assistant_message_id=None,
    ):
        del conversation_id, user_id, user_message_id
        captured["resume_assistant_message_id"] = resume_assistant_message_id

    async def _fake_register_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args
        captured["current_step"] = kwargs.get("current_step")
        return None

    async def _fake_persist_initial_running_snapshot(**kwargs):  # type: ignore[no-untyped-def]
        captured["persisted_current_step"] = kwargs.get("status_label")
        captured["assistant_message_id"] = kwargs.get("assistant_message_id")

    monkeypatch.setattr("app.chat.tasks.run_chat_direct", _fake_run_chat_direct)
    monkeypatch.setattr(stream_runner, "register_stream", _fake_register_stream)
    monkeypatch.setattr(
        stream_runner,
        "_persist_initial_running_snapshot",
        _fake_persist_initial_running_snapshot,
    )

    await stream_runner.launch_chat_stream(
        conversation_id="conv_1",
        user_id="user_1",
        user_message_id="msg_1",
        run_id="run_1",
        resume_assistant_message_id="assist_1",
    )
    await asyncio.sleep(0)

    assert captured == {
        "current_step": "Resuming",
        "persisted_current_step": "Resuming",
        "assistant_message_id": "assist_1",
        "resume_assistant_message_id": "assist_1",
    }
