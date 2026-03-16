import asyncio
import json
from typing import Any, Dict, List

import pytest

from app.services import chat_streams


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis

    def delete(self, _key: str):  # noqa: ANN001
        return self

    def hset(self, key: str, mapping: Dict[str, Any]):
        self._redis.meta[key] = {str(k): str(v) for k, v in mapping.items()}
        return self

    def expire(self, _key: str, _ttl: int):  # noqa: ANN001
        return self

    def sadd(self, key: str, value: str):
        self._redis.sets.setdefault(key, set()).add(value)
        return self

    def publish(self, channel: str, payload: str):
        self._redis.published.append((channel, payload))
        return self

    def srem(self, key: str, value: str):
        values = self._redis.sets.get(key)
        if values is not None:
            values.discard(value)
        return self

    async def execute(self):
        return []


class _FakeRedis:
    def __init__(self) -> None:
        self.meta: Dict[str, Dict[str, str]] = {}
        self.sets: Dict[str, set[str]] = {}
        self.published: List[tuple[str, str]] = []
        self.kv: Dict[str, str] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False):  # noqa: ANN001
        del ex
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True

    async def hgetall(self, key: str) -> Dict[str, str]:
        return self.meta.get(key, {})

    async def hget(self, key: str, field: str):  # noqa: ANN001
        return self.meta.get(key, {}).get(field)

    async def eval(self, _script: str, _numkeys: int, key: str, token: str):  # noqa: ANN001
        if self.kv.get(key) == token:
            del self.kv[key]
            return 1
        return 0

    async def srem(self, key: str, value: str) -> None:
        values = self.sets.get(key)
        if values is not None:
            values.discard(value)


@pytest.mark.asyncio
async def test_register_and_cleanup_publish_run_identity_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    task = asyncio.create_task(asyncio.sleep(0))
    stream = await chat_streams.register_stream(
        conversation_id="conv_lifecycle",
        user_id="user_1",
        user_message_id="msg_1",
        run_id="run_1",
        task=task,
    )
    stream.current_step = "Writing response"
    stream.status = "completed"

    await chat_streams.schedule_cleanup("conv_lifecycle", delay=5)

    if not task.done():
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    public_events = [
        json.loads(payload)
        for channel, payload in fake.published
        if not channel.startswith("assist:stream:registered:")
    ]

    assert len(public_events) == 2

    started_payload = public_events[0]
    assert started_payload["type"] == "stream_started"
    assert started_payload["conversation_id"] == "conv_lifecycle"
    assert started_payload["run_id"] == "run_1"
    assert started_payload["user_message_id"] == "msg_1"
    assert started_payload["status"] == "running"
    assert "current_step" in started_payload

    completed_payload = public_events[1]
    assert completed_payload["type"] == "stream_completed"
    assert completed_payload["conversation_id"] == "conv_lifecycle"
    assert completed_payload["run_id"] == "run_1"
    assert completed_payload["user_message_id"] == "msg_1"
    assert completed_payload["status"] == "completed"
    assert completed_payload["current_step"] == "Writing response"


@pytest.mark.asyncio
async def test_register_stream_rejects_active_stream_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    fake.meta["assist:stream:meta:conv_conflict"] = {"status": "running"}

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    task = asyncio.create_task(asyncio.sleep(0))
    with pytest.raises(chat_streams.StreamRegistrationConflictError):
        await chat_streams.register_stream(
            conversation_id="conv_conflict",
            user_id="user_1",
            user_message_id="msg_1",
            run_id="run_1",
            task=task,
        )

    if not task.done():
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
