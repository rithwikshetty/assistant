from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

import pytest

from app.services import chat_streams


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self._ops: List[Tuple[str, str]] = []

    def hgetall(self, key: str) -> "_FakePipeline":
        self._ops.append(("hgetall", key))
        return self

    async def execute(self) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for op, key in self._ops:
            if op == "hgetall":
                out.append(self._redis.meta.get(key, {}))
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.meta: Dict[str, Dict[str, str]] = {}
        self.sets: Dict[str, Set[str]] = {}
        self.srem_calls: List[Tuple[str, Tuple[str, ...]]] = []

    async def smembers(self, key: str):  # noqa: ANN001
        return self.sets.get(key, set())

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    async def srem(self, key: str, *values: str) -> None:
        self.srem_calls.append((key, values))
        members = self.sets.get(key)
        if members is None:
            return
        for value in values:
            members.discard(value)


@pytest.mark.asyncio
async def test_get_active_streams_for_user_batches_meta_reads_and_stale_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    user_id = "user_123"
    user_streams_key = f"assist:user:streams:{user_id}"
    fake.sets[user_streams_key] = {"conv_a", "conv_b", "conv_c"}

    fake.meta["assist:stream:meta:conv_a"] = {
        "status": "running",
        "user_message_id": "msg_a",
        "run_id": "run_a",
        "started_at": "2026-03-01T00:00:00Z",
        "current_step": "Thinking",
    }
    fake.meta["assist:stream:meta:conv_b"] = {
        "status": "completed",
        "user_message_id": "msg_b",
        "run_id": "run_b",
    }
    # conv_c intentionally missing metadata -> stale

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    rows = await chat_streams.get_active_streams_for_user(user_id)

    assert rows == [
        {
            "conversation_id": "conv_a",
            "user_message_id": "msg_a",
            "run_id": "run_a",
            "started_at": "2026-03-01T00:00:00Z",
            "current_step": "Thinking",
        }
    ]
    assert len(fake.srem_calls) == 1
    srem_key, srem_values = fake.srem_calls[0]
    assert srem_key == user_streams_key
    assert set(srem_values) == {"conv_b", "conv_c"}
