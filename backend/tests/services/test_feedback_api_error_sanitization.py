from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import feedback as feedback_api


class _Query:
    def options(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):
        return None


class _DB:
    def query(self, _model):
        return _Query()


def _build_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(feedback_api.router)
    app.dependency_overrides[feedback_api.get_current_user] = lambda: SimpleNamespace(id="user-1", role="member")
    app.dependency_overrides[feedback_api.get_db] = lambda: _DB()
    return TestClient(app, raise_server_exceptions=False)


def test_submit_bug_masks_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)

    def _raise(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("internal bug details")

    monkeypatch.setattr(feedback_api.service, "create_bug_report", _raise)

    response = client.post(
        "/feedback/bug",
        json={"title": "Broken flow", "description": "Steps", "severity": "high"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to submit bug report"


def test_submit_message_feedback_masks_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)

    def _raise(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("leaked stack trace")

    monkeypatch.setattr(feedback_api.service, "upsert_message_feedback", _raise)

    response = client.post(
        "/feedback/message",
        json={"message_id": "message-1", "rating": "up", "time_saved_minutes": 10},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to submit message feedback"


def test_submit_message_feedback_preserves_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)

    def _raise(**_kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("Message not found")

    monkeypatch.setattr(feedback_api.service, "upsert_message_feedback", _raise)

    response = client.post(
        "/feedback/message",
        json={"message_id": "message-1", "rating": "up", "time_saved_minutes": 10},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Message not found"


def test_delete_message_feedback_masks_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)

    def _raise(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("db connection string leaked")

    monkeypatch.setattr(feedback_api.service, "delete_message_feedback", _raise)

    response = client.delete("/feedback/message/message-1")

    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to delete message feedback"
