import pytest

from app.chat.services import input_items_cache


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):  # noqa: ANN001
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int):  # noqa: ANN001
        self.values[key] = value
        self.ttls[key] = int(ex)


@pytest.mark.asyncio
async def test_set_and_get_cached_input_items_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(input_items_cache, "get_async_redis", _get_fake_redis)
    monkeypatch.setattr(input_items_cache.settings, "redis_stream_initial_ttl", 1200)

    input_items = [
        {"role": "user", "content": "hi"},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hello"}]},
    ]
    await input_items_cache.set_cached_input_items("conv_1", input_items)
    loaded = await input_items_cache.get_cached_input_items("conv_1")

    assert loaded == input_items
    assert fake.ttls.get("chat:input_items:conv_1") == 1200


@pytest.mark.asyncio
async def test_get_cached_input_items_returns_none_for_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()

    async def _get_fake_redis() -> _FakeRedis:
        return fake

    monkeypatch.setattr(input_items_cache, "get_async_redis", _get_fake_redis)

    loaded = await input_items_cache.get_cached_input_items("conv_missing")
    assert loaded is None

