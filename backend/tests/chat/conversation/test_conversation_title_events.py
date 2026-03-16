from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.chat.services import conversation_service


class _FakeMessageQuery:
    def __init__(self, message: object | None) -> None:
        self._message = message

    def filter(self, *args, **kwargs):
        _ = (args, kwargs)
        return self

    def order_by(self, *args, **kwargs):
        _ = (args, kwargs)
        return self

    def first(self):
        return self._message


class _FakeDB:
    def __init__(self, first_message: object | None = None) -> None:
        self._first_message = first_message
        self.commit_calls = 0
        self.refresh_calls = 0

    def query(self, *args, **kwargs):
        _ = (args, kwargs)
        return _FakeMessageQuery(self._first_message)

    def commit(self) -> None:
        self.commit_calls += 1

    def refresh(self, obj: object) -> None:
        _ = obj
        self.refresh_calls += 1


class _AsyncFakeDB:
    def __init__(self, first_message: object | None = None) -> None:
        self._first_message = first_message
        self.commit_calls = 0
        self.refresh_calls = 0

    async def scalar(self, _statement):  # type: ignore[no-untyped-def]
        return self._first_message

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, obj: object) -> None:
        _ = obj
        self.refresh_calls += 1


@pytest.mark.asyncio
async def test_ensure_conversation_title_publishes_user_event_when_generated(monkeypatch) -> None:
    published: list[tuple[str, dict[str, object]]] = []

    async def fake_generate_title(first_user_text: str, analytics_context: dict[str, object] | None = None) -> str:
        _ = (first_user_text, analytics_context)
        return "Generated title"

    async def fake_publish_user_event(user_id: str, payload: dict[str, object]) -> None:
        published.append((user_id, payload))

    monkeypatch.setattr(conversation_service, "generate_title", fake_generate_title)
    monkeypatch.setattr(conversation_service, "publish_user_event", fake_publish_user_event)

    now = datetime.now(timezone.utc)
    conversation = SimpleNamespace(
        id="conv_1",
        title="New Chat",
        user_id="user_1",
        project_id=None,
        updated_at=now,
    )
    db = _FakeDB(first_message=SimpleNamespace(text="hello world"))

    title, generated = await conversation_service.ensure_conversation_title(conversation, db)

    assert title == "Generated title"
    assert generated is True
    assert db.commit_calls == 1
    assert db.refresh_calls == 1
    assert published == [
        (
            "user_1",
            {
                "type": "conversation_title_updated",
                "conversation_id": "conv_1",
                "title": "Generated title",
                "updated_at": conversation_service.format_utc_z(now),
                "source": "generated",
            },
        )
    ]


@pytest.mark.asyncio
async def test_ensure_conversation_title_skips_publish_when_title_already_exists(monkeypatch) -> None:
    async def fail_generate_title(*args, **kwargs):  # pragma: no cover - should not be reached
        _ = (args, kwargs)
        raise AssertionError("generate_title should not run for existing titles")

    async def fail_publish_user_event(*args, **kwargs):  # pragma: no cover - should not be reached
        _ = (args, kwargs)
        raise AssertionError("publish_user_event should not run for existing titles")

    monkeypatch.setattr(conversation_service, "generate_title", fail_generate_title)
    monkeypatch.setattr(conversation_service, "publish_user_event", fail_publish_user_event)

    now = datetime.now(timezone.utc)
    conversation = SimpleNamespace(
        id="conv_1",
        title="Already named",
        user_id="user_1",
        project_id=None,
        updated_at=now,
    )

    title, generated = await conversation_service.ensure_conversation_title(conversation, _FakeDB())

    assert title == "Already named"
    assert generated is False


@pytest.mark.asyncio
async def test_ensure_conversation_title_async_publishes_user_event_when_generated(monkeypatch) -> None:
    published: list[tuple[str, dict[str, object]]] = []

    async def fake_generate_title(first_user_text: str, analytics_context: dict[str, object] | None = None) -> str:
        _ = (first_user_text, analytics_context)
        return "Generated title"

    async def fake_publish_user_event(user_id: str, payload: dict[str, object]) -> None:
        published.append((user_id, payload))

    monkeypatch.setattr(conversation_service, "generate_title", fake_generate_title)
    monkeypatch.setattr(conversation_service, "publish_user_event", fake_publish_user_event)

    now = datetime.now(timezone.utc)
    conversation = SimpleNamespace(
        id="conv_async",
        title="New Chat",
        user_id="user_async",
        project_id=None,
        updated_at=now,
    )
    db = _AsyncFakeDB(first_message=SimpleNamespace(text="hello async world"))

    title, generated = await conversation_service.ensure_conversation_title_async(conversation, db)

    assert title == "Generated title"
    assert generated is True
    assert db.commit_calls == 1
    assert db.refresh_calls == 1
    assert published == [
        (
            "user_async",
            {
                "type": "conversation_title_updated",
                "conversation_id": "conv_async",
                "title": "Generated title",
                "updated_at": conversation_service.format_utc_z(now),
                "source": "generated",
            },
        )
    ]


@pytest.mark.asyncio
async def test_ensure_conversation_title_async_skips_publish_when_title_already_exists(monkeypatch) -> None:
    async def fail_generate_title(*args, **kwargs):  # pragma: no cover - should not be reached
        _ = (args, kwargs)
        raise AssertionError("generate_title should not run for existing titles")

    async def fail_publish_user_event(*args, **kwargs):  # pragma: no cover - should not be reached
        _ = (args, kwargs)
        raise AssertionError("publish_user_event should not run for existing titles")

    monkeypatch.setattr(conversation_service, "generate_title", fail_generate_title)
    monkeypatch.setattr(conversation_service, "publish_user_event", fail_publish_user_event)

    now = datetime.now(timezone.utc)
    conversation = SimpleNamespace(
        id="conv_async",
        title="Already named",
        user_id="user_async",
        project_id=None,
        updated_at=now,
    )

    title, generated = await conversation_service.ensure_conversation_title_async(
        conversation,
        _AsyncFakeDB(),
    )

    assert title == "Already named"
    assert generated is False
