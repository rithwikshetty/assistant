from datetime import datetime, timezone

import pytest

from app.chat.streaming import ChatStreamingManager
from app.chat.streaming_support import StreamState


@pytest.mark.asyncio
async def test_finalize_if_stream_output_marks_fallback_status_when_no_done_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ChatStreamingManager()
    captured_finalize_kwargs = {}
    captured_status_updates = []

    async def fake_finalize_state(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal captured_finalize_kwargs
        captured_finalize_kwargs = dict(kwargs)
        return "assistant_evt_1", []

    async def fake_mark_message_status(message_id: str, status: str) -> None:
        captured_status_updates.append((message_id, status))

    monkeypatch.setattr(manager, "_finalize_state", fake_finalize_state)
    monkeypatch.setattr(manager, "_mark_message_status", fake_mark_message_status)

    persisted_id, done_events = await manager._finalize_if_stream_output(
        conversation_id="conv_1",
        user_message_id="user_evt_1",
        state=StreamState(full_response="partial"),
        usage_calculator=None,  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=datetime.now(timezone.utc),
        assistant_message_id=None,
        message_status="failed",
        warning_event_name="chat.stream.persist_failed_state_unhandled",
        include_done_chunk=False,
        update_user_message_status=True,
        fallback_user_message_status="failed",
    )

    assert persisted_id == "assistant_evt_1"
    assert done_events == []
    assert captured_finalize_kwargs["message_status"] == "failed"
    assert captured_finalize_kwargs["include_done_chunk"] is False
    assert captured_status_updates == [("user_evt_1", "failed")]


@pytest.mark.asyncio
async def test_finalize_if_stream_output_skips_fallback_when_done_event_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ChatStreamingManager()
    captured_status_updates = []

    async def fake_finalize_state(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return "assistant_evt_2", [{"type": "done", "data": {"status": "cancelled"}}]

    async def fake_mark_message_status(message_id: str, status: str) -> None:
        captured_status_updates.append((message_id, status))

    monkeypatch.setattr(manager, "_finalize_state", fake_finalize_state)
    monkeypatch.setattr(manager, "_mark_message_status", fake_mark_message_status)

    persisted_id, done_events = await manager._finalize_if_stream_output(
        conversation_id="conv_2",
        user_message_id="user_evt_2",
        state=StreamState(full_response="partial"),
        usage_calculator=None,  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=datetime.now(timezone.utc),
        assistant_message_id="assistant_evt_1",
        message_status="cancelled",
        warning_event_name="chat.stream.persist_cancelled_state_failed",
        fallback_user_message_status="cancelled",
    )

    assert persisted_id == "assistant_evt_2"
    assert done_events == [{"type": "done", "data": {"status": "cancelled"}}]
    assert captured_status_updates == []


@pytest.mark.asyncio
async def test_finalize_if_stream_output_marks_fallback_when_no_stream_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ChatStreamingManager()
    captured_status_updates = []

    async def fake_mark_message_status(message_id: str, status: str) -> None:
        captured_status_updates.append((message_id, status))

    monkeypatch.setattr(manager, "_mark_message_status", fake_mark_message_status)

    persisted_id, done_events = await manager._finalize_if_stream_output(
        conversation_id="conv_3",
        user_message_id="user_evt_3",
        state=StreamState(full_response=""),
        usage_calculator=None,  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=datetime.now(timezone.utc),
        assistant_message_id=None,
        message_status="failed",
        fallback_user_message_status="failed",
    )

    assert persisted_id is None
    assert done_events == []
    assert captured_status_updates == [("user_evt_3", "failed")]
