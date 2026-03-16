from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat.routes import runs


class FakeAsyncDb:
    def __init__(self) -> None:
        self.run_sync_calls = []

    async def run_sync(self, fn):  # type: ignore[no-untyped-def]
        self.run_sync_calls.append(fn)
        return None


def _build_client(fake_db: FakeAsyncDb) -> TestClient:
    app = FastAPI()
    app.include_router(runs.router, prefix="/conversations")

    async def _async_db_override():
        yield fake_db

    app.dependency_overrides[runs.get_current_user] = (
        lambda: SimpleNamespace(id="user-1", role="member", name="Test User", email="test@example.com")
    )
    app.dependency_overrides[runs.get_async_db] = _async_db_override
    return TestClient(app, raise_server_exceptions=False)


def test_cancel_run_ignores_terminal_runs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_db = FakeAsyncDb()
    client = _build_client(fake_db)

    async def _fake_require_accessible_run_async(_db, **_kwargs):  # type: ignore[no-untyped-def]
        return (
            SimpleNamespace(id="run-1", status="completed"),
            SimpleNamespace(id="conv-1"),
        )

    async def _unexpected_cancel(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("cancel service should not be called for terminal runs")

    monkeypatch.setattr(runs, "require_accessible_run_async", _fake_require_accessible_run_async)
    monkeypatch.setattr(runs, "cancel_conversation_stream", _unexpected_cancel)

    response = client.post("/conversations/runs/run-1/cancel")

    assert response.status_code == 200
    assert response.json() == {"run_id": "run-1", "status": "completed"}
    assert fake_db.run_sync_calls == []


def test_cancel_run_persists_only_when_cancel_service_did_not(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_db = FakeAsyncDb()
    client = _build_client(fake_db)
    captured = {}

    async def _fake_require_accessible_run_async(_db, **_kwargs):  # type: ignore[no-untyped-def]
        return (
            SimpleNamespace(id="run-2", status="running"),
            SimpleNamespace(id="conv-2"),
        )

    async def _fake_cancel_conversation_stream(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {"status": "cancelled", "persisted": False}

    monkeypatch.setattr(runs, "require_accessible_run_async", _fake_require_accessible_run_async)
    monkeypatch.setattr(runs, "cancel_conversation_stream", _fake_cancel_conversation_stream)

    response = client.post("/conversations/runs/run-2/cancel")

    assert response.status_code == 200
    assert response.json() == {"run_id": "run-2", "status": "cancelled"}
    assert captured == {
        "user": SimpleNamespace(id="user-1", role="member", name="Test User", email="test@example.com"),
        "conversation_id": "conv-2",
        "run_id": "run-2",
        "cancel_source": "api.cancel",
        "log_name": "chat.stream.cancel_requested",
    }
    assert fake_db.run_sync_calls == []


def test_cancel_run_normalizes_no_active_stream_to_cancelled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_db = FakeAsyncDb()
    client = _build_client(fake_db)

    async def _fake_require_accessible_run_async(_db, **_kwargs):  # type: ignore[no-untyped-def]
        return (
            SimpleNamespace(id="run-3", status="running"),
            SimpleNamespace(id="conv-3"),
        )

    async def _fake_cancel_conversation_stream(**_kwargs):  # type: ignore[no-untyped-def]
        return {"status": "no_active_stream", "persisted": False}

    monkeypatch.setattr(runs, "require_accessible_run_async", _fake_require_accessible_run_async)
    monkeypatch.setattr(runs, "cancel_conversation_stream", _fake_cancel_conversation_stream)

    response = client.post("/conversations/runs/run-3/cancel")

    assert response.status_code == 200
    assert response.json() == {"run_id": "run-3", "status": "cancelled"}
    assert fake_db.run_sync_calls == []
