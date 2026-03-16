from types import SimpleNamespace
from unittest.mock import MagicMock

from app.chat.services import run_snapshot_service
from app.chat.services.run_snapshot_service import (
    build_conversation_runtime_response,
    clear_run_snapshot,
    list_pending_requests,
    prepare_run_snapshot_for_resume,
)


def test_clear_run_snapshot_uses_bulk_delete_without_nulling_run_id() -> None:
    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_db = MagicMock()
    fake_db.query.return_value = fake_query

    clear_run_snapshot(db=fake_db, conversation_id="conv_1")

    fake_db.query.assert_called_once()
    fake_query.filter.assert_called_once()
    fake_query.delete.assert_called_once_with(synchronize_session=False)
    fake_db.flush.assert_called_once()


def test_prepare_run_snapshot_for_resume_preserves_draft_and_usage() -> None:
    snapshot = SimpleNamespace(
        run_id="run_1",
        run_message_id="user_msg_1",
        assistant_message_id="assistant_msg_1",
        status="paused",
        seq=42,
        status_label="Waiting for your input",
        draft_text="Existing partial answer",
        usage_jsonb={"output_tokens": 123},
    )
    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.first.return_value = snapshot
    fake_db = MagicMock()
    fake_db.query.return_value = fake_query

    resumed = prepare_run_snapshot_for_resume(
        db=fake_db,
        conversation_id="conv_1",
        run_id="run_1",
        run_message_id="user_msg_1",
        assistant_message_id="assistant_msg_1",
        status_label="Resuming",
    )

    assert resumed is True
    assert snapshot.status == "running"
    assert snapshot.seq == 0
    assert snapshot.status_label == "Resuming"
    assert snapshot.draft_text == "Existing partial answer"
    assert snapshot.usage_jsonb == {"output_tokens": 123}
    fake_db.flush.assert_called_once()


def test_build_conversation_runtime_response_includes_live_partial_assistant_message(monkeypatch) -> None:
    snapshot = SimpleNamespace(
        run_id="run_1",
        run_message_id="user_msg_1",
        assistant_message_id="assistant_msg_1",
        status="running",
        seq=42,
        status_label="Thinking",
        draft_text="Partial answer",
        usage_jsonb={"output_tokens": 123},
    )
    assistant_message = SimpleNamespace(
        id="assistant_msg_1",
        run_id="run_1",
        role="assistant",
        status="streaming",
        text="Partial answer",
        model_provider=None,
        model_name=None,
        finish_reason=None,
        response_latency_ms=None,
        cost_usd=None,
        created_at=None,
    )

    snapshot_query = MagicMock()
    snapshot_query.filter.return_value = snapshot_query
    snapshot_query.first.return_value = snapshot

    message_query = MagicMock()
    message_query.filter.return_value = message_query
    message_query.first.return_value = assistant_message

    pending_query = MagicMock()
    pending_query.filter.return_value = pending_query
    pending_query.order_by.return_value = pending_query
    pending_query.all.return_value = []

    fake_db = MagicMock()
    fake_db.query.side_effect = [snapshot_query, pending_query, message_query]

    monkeypatch.setattr(run_snapshot_service, "list_queued_turns", lambda **_kwargs: [])
    monkeypatch.setattr(
        run_snapshot_service,
        "list_run_activity_items",
        lambda **_kwargs: [
            {
                "id": "activity_1",
                "run_id": "run_1",
                "item_key": "tool:call_1",
                "kind": "tool",
                "status": "running",
                "title": "Web search",
                "summary": None,
                "sequence": 1,
                "payload": {"tool_call_id": "call_1"},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )

    payload = build_conversation_runtime_response(
        db=fake_db,
        conversation_id="conv_1",
    )

    assert payload["resume_since_stream_event_id"] == 42
    assert payload["activity_cursor"] == 42
    assert payload["live_message"] == {
        "id": "assistant_msg_1",
        "seq": 0,
        "run_id": "run_1",
        "type": "assistant_message_partial",
        "actor": "assistant",
        "created_at": "",
        "role": "assistant",
        "text": "Partial answer",
        "activity_items": payload["activity_items"],
        "payload": {
            "text": "Partial answer",
            "status": "streaming",
            "model_provider": None,
            "model_name": None,
            "finish_reason": None,
        },
    }


def test_list_pending_requests_reads_authoritative_pending_input_rows() -> None:
    row = SimpleNamespace(
        tool_call_id="call_1",
        request_jsonb={
            "tool_name": "request_user_input",
            "request": {
                "tool": "request_user_input",
                "title": "Choose",
                "prompt": "Pick one",
                "questions": [
                    {
                        "id": "q1",
                        "question": "Proceed?",
                        "options": [
                            {"label": "Yes", "description": "Continue"},
                            {"label": "No", "description": "Stop"},
                        ],
                    }
                ],
            },
            "result": {"status": "pending"},
        },
    )
    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = fake_query
    fake_query.all.return_value = [row]
    fake_db = MagicMock()
    fake_db.query.return_value = fake_query

    pending_requests = list_pending_requests(db=fake_db, run_id="run_1")

    assert pending_requests == [
        {
            "call_id": "call_1",
            "tool_name": "request_user_input",
            "request": {
                "tool": "request_user_input",
                "title": "Choose",
                "prompt": "Pick one",
                "questions": [
                    {
                        "id": "q1",
                        "question": "Proceed?",
                        "options": [
                            {"label": "Yes", "description": "Continue"},
                            {"label": "No", "description": "Stop"},
                        ],
                    }
                ],
            },
            "result": {
                "status": "pending",
                "request": {
                    "tool": "request_user_input",
                    "title": "Choose",
                    "prompt": "Pick one",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "Proceed?",
                            "options": [
                                {"label": "Yes", "description": "Continue"},
                                {"label": "No", "description": "Stop"},
                            ],
                        }
                    ],
                },
            },
        }
    ]
