from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat.routes import runs


class FakeAsyncDb:
    async def run_sync(self, fn):  # type: ignore[no-untyped-def]
        return fn(SimpleNamespace())

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
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


def test_submit_run_user_input_enqueues_when_running_stream_meta_points_to_another_run(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_db = FakeAsyncDb()
    client = _build_client(fake_db)
    captured = {}

    async def _fake_require_accessible_run_async(_db, **_kwargs):  # type: ignore[no-untyped-def]
        return (
            SimpleNamespace(id="run-1", status="paused"),
            SimpleNamespace(id="conv-1"),
        )

    def _fake_record_run_user_input_submission(_sync_db, **_kwargs):  # type: ignore[no-untyped-def]
        return {
            "run_id": "run-new",
            "user_message_id": "msg-new",
            "assistant_message_id": "assist-new",
            "tool_call_id": "call-1",
        }

    async def _fake_get_stream_meta(_conversation_id: str):  # type: ignore[no-untyped-def]
        return {
            "status": "running",
            "run_id": "run-old",
            "user_message_id": "msg-old",
        }

    async def _fake_enqueue_run_command(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return "1-1"

    monkeypatch.setattr(runs, "require_accessible_run_async", _fake_require_accessible_run_async)
    monkeypatch.setattr(runs, "record_run_user_input_submission", _fake_record_run_user_input_submission)
    monkeypatch.setattr(runs, "get_stream_meta", _fake_get_stream_meta)
    monkeypatch.setattr(runs, "enqueue_run_command", _fake_enqueue_run_command)

    response = client.post(
        "/conversations/runs/run-1/user-input",
        json={"result": {"answers": [{"question_id": "q1", "option_label": "Proceed"}]}},
    )

    assert response.status_code == 200
    assert captured == {
        "conversation_id": "conv-1",
        "run_id": "run-new",
        "user_id": "user-1",
        "user_message_id": "msg-new",
        "resume_assistant_message_id": "assist-new",
    }


def test_submit_run_user_input_reverts_when_resume_enqueue_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_db = FakeAsyncDb()
    client = _build_client(fake_db)
    reverted = {}

    async def _fake_require_accessible_run_async(_db, **_kwargs):  # type: ignore[no-untyped-def]
        return (
            SimpleNamespace(id="run-1", status="paused"),
            SimpleNamespace(id="conv-1"),
        )

    def _fake_record_run_user_input_submission(_sync_db, **_kwargs):  # type: ignore[no-untyped-def]
        return {
            "run_id": "run-new",
            "user_message_id": "msg-new",
            "assistant_message_id": "assist-new",
            "tool_call_id": "call-1",
        }

    async def _fake_get_stream_meta(_conversation_id: str):  # type: ignore[no-untyped-def]
        return None

    async def _failing_enqueue_run_command(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("redis down")

    def _fake_restore_interactive_submission_pending(_sync_db, **kwargs):  # type: ignore[no-untyped-def]
        reverted.update(kwargs)

    monkeypatch.setattr(runs, "require_accessible_run_async", _fake_require_accessible_run_async)
    monkeypatch.setattr(runs, "record_run_user_input_submission", _fake_record_run_user_input_submission)
    monkeypatch.setattr(runs, "get_stream_meta", _fake_get_stream_meta)
    monkeypatch.setattr(runs, "enqueue_run_command", _failing_enqueue_run_command)
    monkeypatch.setattr(runs, "restore_interactive_submission_pending", _fake_restore_interactive_submission_pending)

    response = client.post(
        "/conversations/runs/run-1/user-input",
        json={"result": {"answers": [{"question_id": "q1", "option_label": "Proceed"}]}},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Failed to resume run. Please try again."}
    assert reverted == {
        "run_id": "run-new",
        "conversation_id": "conv-1",
        "tool_call_id": "call-1",
        "assistant_message_id": "assist-new",
    }
