import pytest

from app.chat import streaming as streaming_module
from app.chat.streaming import ChatStreamingManager


@pytest.mark.asyncio
async def test_cache_input_snapshot_if_present_writes_cache_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ChatStreamingManager()
    captured: dict[str, object] = {}
    log_events: list[str] = []

    async def fake_set_cached_input_items(conversation_id: str, input_items):  # type: ignore[no-untyped-def]
        captured["conversation_id"] = conversation_id
        captured["item_count"] = len(input_items)

    def fake_log_event(_logger, _level, event_name, _phase, **_kwargs):  # type: ignore[no-untyped-def]
        log_events.append(event_name)

    monkeypatch.setattr(streaming_module, "set_cached_input_items", fake_set_cached_input_items)
    monkeypatch.setattr(streaming_module, "log_event", fake_log_event)

    await manager._cache_input_snapshot_if_present(
        conversation_id="conv_1",
        update={"type": "input_items_snapshot", "content": [{"id": "item_a"}, {"id": "item_b"}]},
    )

    assert captured == {"conversation_id": "conv_1", "item_count": 2}
    assert "chat.stream.input_snapshot_cached" in log_events


@pytest.mark.asyncio
async def test_cache_input_snapshot_if_present_ignores_non_snapshot_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ChatStreamingManager()
    called = False

    async def fake_set_cached_input_items(_conversation_id: str, _input_items):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True

    monkeypatch.setattr(streaming_module, "set_cached_input_items", fake_set_cached_input_items)

    await manager._cache_input_snapshot_if_present(
        conversation_id="conv_1",
        update={"type": "message", "content": "hello"},
    )

    assert called is False


@pytest.mark.asyncio
async def test_cache_input_snapshot_if_present_logs_write_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ChatStreamingManager()
    log_events: list[str] = []

    async def fake_set_cached_input_items(_conversation_id: str, _input_items):  # type: ignore[no-untyped-def]
        raise RuntimeError("cache down")

    def fake_log_event(_logger, _level, event_name, _phase, **_kwargs):  # type: ignore[no-untyped-def]
        log_events.append(event_name)

    monkeypatch.setattr(streaming_module, "set_cached_input_items", fake_set_cached_input_items)
    monkeypatch.setattr(streaming_module, "log_event", fake_log_event)

    await manager._cache_input_snapshot_if_present(
        conversation_id="conv_1",
        update={"type": "input_items_snapshot", "content": [{"id": "item_a"}]},
    )

    assert "chat.stream.input_snapshot_cache_write_failed" in log_events
