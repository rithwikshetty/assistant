import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest
import redis

from app.services import chat_streams


class _FakeRedis:
    def __init__(
        self,
        *,
        entries: List[Tuple[str, Any]],
        index: Optional[Dict[str, str]] = None,
        meta: Optional[Dict[str, str]] = None,
        xread_results: Optional[List[Any]] = None,
        status_sequence: Optional[List[str]] = None,
        pubsub_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._entries = entries
        self._index = index or {}
        self._meta = meta or {}
        self._xread_results = xread_results or []
        self._status_sequence = list(status_sequence or [])
        self._pubsub_messages = list(pubsub_messages or [])
        self.xrange_calls: List[Tuple[str, str]] = []
        self.xread_calls: List[Dict[str, Any]] = []
        self.hget_calls = 0
        self.hgetall_calls = 0
        self.pubsub_subscriptions: List[str] = []

    async def hget(self, key: str, field: str):  # noqa: ANN001
        self.hget_calls += 1
        if "event-id-index" in key:
            return self._index.get(field)
        if "stream:meta" in key:
            if field == "status" and self._status_sequence:
                return self._status_sequence.pop(0)
            return self._meta.get(field)
        return None

    async def hgetall(self, key: str):  # noqa: ANN001
        if "stream:meta" in key:
            self.hgetall_calls += 1
            return dict(self._meta)
        return {}

    async def xrange(self, key: str, min: str = "-", max: str = "+"):  # noqa: ANN001,A002
        self.xrange_calls.append((min, max))
        def _entry_payload(payload: Any) -> str:
            if isinstance(payload, str):
                return payload
            return json.dumps(payload)

        if min in {"-", "0-0"}:
            return [(entry_id, {"data": _entry_payload(payload)}) for entry_id, payload in self._entries]

        if min.startswith("("):
            floor = min[1:]
            return [
                (entry_id, {"data": _entry_payload(payload)})
                for entry_id, payload in self._entries
                if entry_id > floor
            ]
        return []

    async def xread(self, streams: Dict[str, str], block: int, count: int):  # noqa: ANN001
        self.xread_calls.append({"streams": streams, "block": block, "count": count})
        if self._xread_results:
            result = self._xread_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return []

    def pubsub(self):  # noqa: ANN001
        return _FakePubSub(self)


class _FakePubSub:
    def __init__(self, redis_client: _FakeRedis) -> None:
        self._redis_client = redis_client

    async def subscribe(self, channel: str) -> None:
        self._redis_client.pubsub_subscriptions.append(channel)

    async def get_message(self, ignore_subscribe_messages: bool, timeout: float):  # noqa: ANN001
        _ = ignore_subscribe_messages
        _ = timeout
        if not self._redis_client._pubsub_messages:
            return None
        payload = self._redis_client._pubsub_messages.pop(0)
        return {
            "type": "message",
            "data": json.dumps(payload),
        }

    async def unsubscribe(self, channel: str) -> None:
        _ = channel

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_subscribe_stream_events_replays_from_indexed_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis(
        entries=[
            ("1-1", {"id": 1, "type": "runtime_update", "data": {"statusLabel": "Thinking"}}),
            ("1-5", {"id": 5, "type": "runtime_update", "data": {"statusLabel": "Searching"}}),
            ("1-6", {"id": 6, "type": "runtime_update", "data": {"statusLabel": "Generating response"}}),
            ("1-7", {"id": 7, "type": "done", "data": {}}),
        ],
        index={"5": "1-5"},
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events("conv_1", since_stream_event_id=5):
        events.append(event)

    assert [event["id"] for event in events] == [6, 7]
    assert fake.xrange_calls[0][0] == "(1-5"


@pytest.mark.asyncio
async def test_subscribe_stream_events_accepts_bytes_indexed_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis(
        entries=[
            ("1-5", {"id": 5, "type": "runtime_update", "data": {"statusLabel": "Searching"}}),
            ("1-6", {"id": 6, "type": "runtime_update", "data": {"statusLabel": "Generating response"}}),
            ("1-7", {"id": 7, "type": "done", "data": {}}),
        ],
        index={"5": b"1-5"},
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events("conv_bytes", since_stream_event_id=5):
        events.append(event)

    assert [event["id"] for event in events] == [6, 7]
    assert fake.xrange_calls[0][0] == "(1-5"


@pytest.mark.asyncio
async def test_subscribe_stream_events_emits_replay_gap_when_cursor_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis(
        entries=[],
        index={},
        meta={"last_stream_event_id": "10", "status": "running"},
        xread_results=[
            [("events", [("2-1", {"data": json.dumps({"id": 11, "type": "done", "data": {}})})])]
        ],
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events("conv_2", since_stream_event_id=5):
        events.append(event)

    assert events[0]["type"] == "replay_gap"
    assert events[1]["type"] == "done"
    # No historical replay when cursor is unavailable.
    assert fake.xrange_calls == []
    assert fake.xread_calls[0]["streams"] == {"assist:stream:events:conv_2": "$"}
    assert fake.hgetall_calls == 1


@pytest.mark.asyncio
async def test_subscribe_stream_events_drains_terminal_stream_from_start_when_cursor_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis(
        entries=[
            ("1-5", {"id": 5, "type": "runtime_update", "data": {"statusLabel": "Searching"}}),
            ("1-6", {"id": 6, "type": "runtime_update", "data": {"statusLabel": "Generating response"}}),
            ("1-7", {"id": 7, "type": "done", "data": {}}),
        ],
        index={},
        meta={"last_stream_event_id": "7", "status": "completed"},
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events("conv_terminal", since_stream_event_id=5):
        events.append(event)

    assert [event["type"] for event in events] == ["replay_gap", "runtime_update", "done"]
    assert fake.xrange_calls == [("0-0", "+")]
    assert fake.xread_calls == []


@pytest.mark.asyncio
async def test_subscribe_stream_events_does_not_emit_replay_gap_without_forward_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis(
        entries=[],
        index={},
        meta={"last_stream_event_id": "5", "status": "running"},
        xread_results=[
            [("events", [("2-1", {"data": json.dumps({"id": 6, "type": "done", "data": {}})})])]
        ],
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events("conv_3", since_stream_event_id=5):
        events.append(event)

    assert [event["type"] for event in events] == ["done"]
    assert fake.xrange_calls == []
    assert fake.xread_calls[0]["streams"] == {"assist:stream:events:conv_3": "$"}


@pytest.mark.asyncio
async def test_subscribe_stream_events_skips_malformed_json_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis(
        entries=[
            ("1-1", "not-json"),
            ("1-2", {"id": 2, "type": "runtime_update", "data": {"statusLabel": "Generating response"}}),
            ("1-3", {"id": 3, "type": "done", "data": {}}),
        ],
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events("conv_bad", since_stream_event_id=0):
        events.append(event)

    assert [event["type"] for event in events] == ["runtime_update", "done"]


@pytest.mark.asyncio
async def test_subscribe_stream_events_recovers_from_live_redis_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis(
        entries=[],
        index={},
        meta={"last_stream_event_id": "1", "status": "running"},
        xread_results=[
            redis.exceptions.TimeoutError("Timeout reading from socket"),
            [("events", [("2-1", {"data": json.dumps({"id": 2, "type": "done", "data": {}})})])],
        ],
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events("conv_timeout", since_stream_event_id=1):
        events.append(event)

    assert [event["type"] for event in events] == ["done"]
    assert len(fake.xread_calls) == 2


@pytest.mark.asyncio
async def test_subscribe_stream_events_filters_other_run_message_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis(
        entries=[
            ("1-1", {"id": 1, "type": "runtime_update", "data": {"statusLabel": "Thinking", "runMessageId": "msg_old"}}),
            ("1-2", {"id": 2, "type": "runtime_update", "data": {"statusLabel": "Searching", "runMessageId": "msg_new"}}),
            ("1-3", {"id": 3, "type": "done", "data": {"runMessageId": "msg_new"}}),
        ],
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events(
        "conv_filter",
        since_stream_event_id=0,
        requested_run_message_id="msg_new",
    ):
        events.append(event)

    assert [event["id"] for event in events] == [2, 3]


@pytest.mark.asyncio
async def test_subscribe_stream_events_filters_terminal_drain_by_requested_run_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis(
        entries=[
            ("1-1", {"id": 1, "type": "runtime_update", "data": {"statusLabel": "Thinking", "runMessageId": "msg_old"}}),
            ("1-2", {"id": 2, "type": "runtime_update", "data": {"statusLabel": "Searching", "runMessageId": "msg_new"}}),
            ("1-3", {"id": 3, "type": "done", "data": {"runMessageId": "msg_new"}}),
        ],
        index={},
        meta={"last_stream_event_id": "3", "status": "completed"},
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events(
        "conv_terminal_filter",
        since_stream_event_id=1,
        requested_run_message_id="msg_new",
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["replay_gap", "runtime_update", "done"]
    assert [event["id"] for event in events[1:]] == [2, 3]


@pytest.mark.asyncio
async def test_subscribe_stream_events_advances_live_cursor_when_foreign_run_events_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events_key = "assist:stream:events:conv_live_filter"
    fake = _FakeRedis(
        entries=[],
        meta={"status": "running"},
        xread_results=[
            [(events_key, [("1-1", {"data": json.dumps({"id": 1, "type": "runtime_update", "data": {"runMessageId": "msg_old"}})})])],
            [(events_key, [("1-2", {"data": json.dumps({"id": 2, "type": "done", "data": {"runMessageId": "msg_new"}})})])],
        ],
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events(
        "conv_live_filter",
        since_stream_event_id=0,
        requested_run_message_id="msg_new",
    ):
        events.append(event)

    assert [event["id"] for event in events] == [2]
    assert fake.xread_calls[0]["streams"] == {events_key: "0-0"}
    assert fake.xread_calls[1]["streams"] == {events_key: "1-1"}


@pytest.mark.asyncio
async def test_subscribe_stream_events_uses_status_hget_on_timeout_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis(
        entries=[],
        meta={},
        xread_results=[[]],
        status_sequence=["running", "completed"],
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events("conv_status_poll", since_stream_event_id=0):
        events.append(event)

    assert events == []
    # Pre-live status check + timeout status refresh use HGET status.
    assert fake.hget_calls >= 2
    # Timeout path should not force a full metadata hash load.
    assert fake.hgetall_calls == 0


@pytest.mark.asyncio
async def test_subscribe_stream_events_allows_collaborator_reader_when_owner_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis(
        entries=[
            ("1-1", {"id": 1, "type": "runtime_update", "data": {"statusLabel": "Thinking"}}),
            ("1-2", {"id": 2, "type": "done", "data": {}}),
        ],
        meta={"user_id": "owner_user", "status": "completed"},
    )

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    events = []
    async for event in chat_streams.subscribe_stream_events(
        "conv_shared",
        since_stream_event_id=0,
        user_id="collaborator_user",
    ):
        events.append(event)

    assert [event["id"] for event in events] == [1, 2]


@pytest.mark.asyncio
async def test_wait_for_stream_registration_uses_conversation_scoped_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis(
        entries=[],
        pubsub_messages=[
            {
                "type": "stream_registered",
                "conversation_id": "conv_shared",
            }
        ],
    )
    meta_reads = 0

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    async def _fake_get_stream_meta(conversation_id: str):  # noqa: ANN001
        nonlocal meta_reads
        meta_reads += 1
        if meta_reads == 1:
            return None
        return {
            "user_id": "owner_user",
            "user_message_id": "msg_1",
            "status": "running",
        }

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)
    monkeypatch.setattr(chat_streams, "get_stream_meta", _fake_get_stream_meta)

    meta = await chat_streams.wait_for_stream_registration(
        conversation_id="conv_shared",
        user_id="collaborator_user",
        timeout_seconds=0.5,
    )

    assert meta == {
        "user_id": "owner_user",
        "user_message_id": "msg_1",
        "status": "running",
    }
    assert fake.pubsub_subscriptions == ["assist:stream:registered:conv_shared"]
