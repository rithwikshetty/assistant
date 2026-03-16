from types import SimpleNamespace

import pytest

from app.chat.streaming import ChatStreamingManager
from app.chat.streaming_support import StreamState


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):  # type: ignore[no-untyped-def]
        return self._result


class _FakeSession:
    def __init__(self, *, run, message=None):
        self._run = run
        self._message = message

    def query(self, model):  # type: ignore[no-untyped-def]
        if getattr(model, "__name__", "") == "ChatRun":
            return _FakeQuery(self._run)
        if getattr(model, "__name__", "") == "Message":
            return _FakeQuery(self._message)
        raise AssertionError(f"Unexpected query model: {getattr(model, '__name__', model)}")


def test_persist_live_runtime_projection_sync_updates_runtime_snapshot(monkeypatch) -> None:
    manager = ChatStreamingManager()
    state = StreamState(
        full_response="Partial answer",
        current_step="Thinking",
        tool_markers=[
            {
                "call_id": "call_1",
                "name": "web_search",
                "seq": 1,
                "query": "latest tender pricing",
                "result": {"status": "running"},
            }
        ],
    )
    run = SimpleNamespace(id="run_1")
    message = SimpleNamespace(id="assist_1")
    captured: dict[str, object] = {}

    def fake_sync_run_activity_items(**kwargs):  # type: ignore[no-untyped-def]
        captured["activity_kwargs"] = kwargs
        return None

    def fake_upsert_run_snapshot(**kwargs):  # type: ignore[no-untyped-def]
        captured["snapshot_kwargs"] = kwargs
        return None

    monkeypatch.setattr(
        "app.chat.streaming_persistence.sync_run_activity_items",
        fake_sync_run_activity_items,
    )
    monkeypatch.setattr(
        "app.chat.streaming_persistence.upsert_run_snapshot",
        fake_upsert_run_snapshot,
    )

    manager._persist_live_runtime_projection_sync(
        db=_FakeSession(run=run, message=message),  # type: ignore[arg-type]
        conversation_id="conv_1",
        user_message_id="msg_1",
        state=state,
        assistant_message_id="assist_1",
        stream_event_id=11,
    )

    activity_kwargs = captured["activity_kwargs"]
    snapshot_kwargs = captured["snapshot_kwargs"]
    assert isinstance(activity_kwargs, dict)
    assert isinstance(snapshot_kwargs, dict)
    assert activity_kwargs["conversation_id"] == "conv_1"
    assert activity_kwargs["run_id"] == "run_1"
    assert activity_kwargs["assistant_message_id"] == "assist_1"
    assert isinstance(activity_kwargs["activity_items"], list)
    assert snapshot_kwargs["conversation_id"] == "conv_1"
    assert snapshot_kwargs["run_id"] == "run_1"
    assert snapshot_kwargs["run_message_id"] == "msg_1"
    assert snapshot_kwargs["assistant_message_id"] == "assist_1"
    assert snapshot_kwargs["status"] == "running"
    assert snapshot_kwargs["status_label"] == "Thinking"
    assert snapshot_kwargs["draft_text"] == "Partial answer"
    assert snapshot_kwargs["seq"] == 11
    assert snapshot_kwargs["usage"] == {}


def test_persist_live_runtime_projection_sync_ignores_unknown_assistant_message_id(monkeypatch) -> None:
    manager = ChatStreamingManager()
    state = StreamState(
        full_response="Partial answer",
        current_step="Thinking",
    )
    run = SimpleNamespace(id="run_1")
    captured: dict[str, object] = {}

    def fake_sync_run_activity_items(**kwargs):  # type: ignore[no-untyped-def]
        captured["activity_kwargs"] = kwargs
        return None

    def fake_upsert_run_snapshot(**kwargs):  # type: ignore[no-untyped-def]
        captured["snapshot_kwargs"] = kwargs
        return None

    monkeypatch.setattr(
        "app.chat.streaming_persistence.sync_run_activity_items",
        fake_sync_run_activity_items,
    )
    monkeypatch.setattr(
        "app.chat.streaming_persistence.upsert_run_snapshot",
        fake_upsert_run_snapshot,
    )

    manager._persist_live_runtime_projection_sync(
        db=_FakeSession(run=run, message=None),  # type: ignore[arg-type]
        conversation_id="conv_1",
        user_message_id="msg_1",
        state=state,
        assistant_message_id="assist_missing",
        stream_event_id=4,
    )

    activity_kwargs = captured["activity_kwargs"]
    snapshot_kwargs = captured["snapshot_kwargs"]
    assert isinstance(activity_kwargs, dict)
    assert isinstance(snapshot_kwargs, dict)
    assert activity_kwargs["assistant_message_id"] is None
    assert snapshot_kwargs["assistant_message_id"] is None


@pytest.mark.asyncio
async def test_checkpoint_partial_state_does_not_return_speculative_message_id(monkeypatch) -> None:
    manager = ChatStreamingManager()
    state = StreamState(full_response="Partial answer")

    async def fake_finalize_state(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return "speculative_assistant_id", []

    monkeypatch.setattr(manager, "_finalize_state", fake_finalize_state)

    checkpoint_message_id = await manager._checkpoint_partial_state(
        conversation_id="conv_1",
        user_message_id="msg_1",
        state=state,
        usage_calculator=SimpleNamespace(),  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-test",
        start_time=None,  # type: ignore[arg-type]
        assistant_message_id=None,
        checkpoint_stream_event_id=9,
    )

    assert checkpoint_message_id is None
