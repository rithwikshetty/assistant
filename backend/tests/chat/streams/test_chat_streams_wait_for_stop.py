import json

import pytest

from app.services import chat_streams


class _FakeRedis:
    def __init__(self) -> None:
        self.hget_calls = 0
        self.xread_calls = 0
        self._hget_values = ["running", "completed"]
        self._xread_results = [
            [],
            [],
            [("events", [("1-1", {"data": json.dumps({"type": "done"})})])],
        ]

    async def hget(self, _key: str, _field: str):
        self.hget_calls += 1
        if self._hget_values:
            return self._hget_values.pop(0)
        return "completed"

    async def xread(self, _streams, block: int, count: int):  # noqa: ANN001
        del block, count
        self.xread_calls += 1
        if self._xread_results:
            return self._xread_results.pop(0)
        return []


@pytest.mark.asyncio
async def test_wait_for_stream_stop_reuses_recent_status(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(chat_streams, "get_async_redis", _get_fake_redis)

    status = await chat_streams.wait_for_stream_stop(conversation_id="conv-cache", timeout_seconds=2.0)

    assert status == "completed"
    assert fake.xread_calls == 3
    # Initial status read + terminal refresh; timeout checks reuse cached value.
    assert fake.hget_calls == 2
