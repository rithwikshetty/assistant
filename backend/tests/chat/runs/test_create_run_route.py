from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat.routes import runs


async def _async_db_override():
    yield SimpleNamespace()


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(runs.router, prefix="/conversations")
    app.dependency_overrides[runs.get_current_user] = (
        lambda: SimpleNamespace(id="user-1", role="member", name="Test User", email="test@example.com")
    )
    app.dependency_overrides[runs.get_async_db] = _async_db_override
    return TestClient(app, raise_server_exceptions=False)


def test_create_run_requires_text() -> None:
    client = _build_client()

    response = client.post("/conversations/conv-1/runs", json={"text": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "text is required"


def test_create_run_returns_compact_response(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _build_client()
    captured: dict[str, object] = {}

    async def _fake_submit_existing_conversation(conversation_id, message, **kwargs):  # type: ignore[no-untyped-def]
        captured["conversation_id"] = conversation_id
        captured["message"] = message
        captured.update(kwargs)
        return {
            "run_id": "run-1",
            "user_message_id": "msg-1",
            "status": "queued",
            "queue_position": 2,
        }

    monkeypatch.setattr(runs, "submit_existing_conversation", _fake_submit_existing_conversation)

    response = client.post(
        "/conversations/conv-1/runs",
        json={
            "text": "Continue working",
            "request_id": "req-1",
            "attachment_ids": ["file-1"],
        },
        headers={
            "X-User-Timezone": "Australia/Melbourne",
            "X-User-Locale": "en-AU",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "user_message_id": "msg-1",
        "status": "queued",
        "queue_position": 2,
    }

    message = captured["message"]
    assert getattr(message, "content") == "Continue working"
    assert getattr(message, "request_id") == "req-1"
    assert getattr(message, "attachments") == ["file-1"]
    assert captured["conversation_id"] == "conv-1"
    assert captured["user_timezone"] == "Australia/Melbourne"
    assert captured["user_locale"] == "en-AU"
    assert captured["submit_trace_id"] == "req-1"
