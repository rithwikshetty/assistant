from types import SimpleNamespace

from app.chat.services.event_history_builder import (
    _message_to_history_message,
    _suppress_superseded_assistant_partials,
)


def _event(*, seq: int, event_type: str, run_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(seq=seq, event_type=event_type, run_id=run_id)


def test_suppress_superseded_assistant_partials_drops_old_partials_after_final() -> None:
    events = [
        _event(seq=1, event_type="user_message", run_id="run_1"),
        _event(seq=2, event_type="assistant_message_partial", run_id="run_1"),
        _event(seq=3, event_type="assistant_message_partial", run_id="run_1"),
        _event(seq=4, event_type="assistant_message_final", run_id="run_1"),
    ]

    filtered = _suppress_superseded_assistant_partials(events)

    assert [event.seq for event in filtered] == [1, 4]
    assert [event.event_type for event in filtered] == ["user_message", "assistant_message_final"]


def test_suppress_superseded_assistant_partials_keeps_latest_partial_without_final() -> None:
    events = [
        _event(seq=10, event_type="assistant_message_partial", run_id="run_2"),
        _event(seq=11, event_type="assistant_message_partial", run_id="run_2"),
        _event(seq=12, event_type="user_message", run_id="run_2"),
    ]

    filtered = _suppress_superseded_assistant_partials(events)

    assert [event.seq for event in filtered] == [11, 12]
    assert [event.event_type for event in filtered] == ["assistant_message_partial", "user_message"]


def test_message_to_history_message_for_assistant_uses_text_and_status_only() -> None:
    message = SimpleNamespace(
        role="assistant",
        text="Final answer",
        status="completed",
    )
    parts = [
        SimpleNamespace(
            part_type="tool_call",
            phase="worklog",
            text=None,
            payload_jsonb={
                "toolName": "retrieval_project_files",
                "toolCallId": "call_1",
                "args": {"query": "Bid A"},
            },
        )
    ]

    history_message = _message_to_history_message(message, parts)  # type: ignore[arg-type]

    assert history_message == {
        "role": "assistant",
        "content": "Final answer",
        "metadata": {
            "status": "completed",
        },
    }
