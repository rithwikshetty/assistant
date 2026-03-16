from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.chat.services import event_store_service


class _FailOnQuerySession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_calls = 0

    def query(self, model):  # type: ignore[no-untyped-def]
        raise AssertionError(f"Unexpected query for {model!r}")

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_calls += 1


def test_append_event_sync_uses_prefetched_conversation_without_reread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FailOnQuerySession()
    conversation = SimpleNamespace(id="conv-1")
    state = SimpleNamespace()
    message = SimpleNamespace(
        id="msg-1",
        role="user",
        status="completed",
        text="Hello",
        created_at=None,
    )
    projection_args: dict[str, object] = {}

    monkeypatch.setattr(event_store_service, "_ensure_state_row", lambda sync_db, conversation_id: state)
    monkeypatch.setattr(
        event_store_service,
        "_map_event_to_message",
        lambda **kwargs: (message, None),
    )
    monkeypatch.setattr(
        event_store_service,
        "_apply_projection",
        lambda **kwargs: projection_args.update(kwargs),
    )

    result = event_store_service.append_event_sync(
        session,
        conversation_id="conv-1",
        event_type="user_message",
        actor="user",
        payload={"text": "Hello"},
        conversation=conversation,
    )

    assert result is message
    assert session.flush_calls == 1
    assert projection_args["conversation"] is conversation
    assert projection_args["state"] is state


def test_append_event_sync_rejects_mismatched_prefetched_conversation() -> None:
    with pytest.raises(ValueError, match="Provided conversation does not match conversation_id"):
        event_store_service.append_event_sync(
            _FailOnQuerySession(),
            conversation_id="conv-1",
            event_type="user_message",
            actor="user",
            payload={"text": "Hello"},
            conversation=SimpleNamespace(id="conv-2"),
        )
