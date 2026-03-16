from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.chat.services import run_runtime_service


def test_clamp_page_limit_enforces_bounds() -> None:
    assert run_runtime_service.clamp_page_limit(-10) == 1
    assert run_runtime_service.clamp_page_limit(0) == 1
    assert run_runtime_service.clamp_page_limit(42) == 42
    assert run_runtime_service.clamp_page_limit(999) == 300


def test_normalize_user_input_submission_with_answers() -> None:
    normalized = run_runtime_service.normalize_user_input_submission(
        {"answers": [{"question_id": "q1", "option_label": "Proceed"}], "custom_response": "   "},
        {
            "status": "pending",
            "request": {
                "title": "Choose",
                "prompt": "Pick a path",
                "questions": [{"id": "q1", "question": "Path?"}],
            },
        },
    )

    assert normalized["answers"] == [{"question_id": "q1", "option_label": "Proceed"}]
    assert normalized["custom_response"] == ""


class _QueryStub:
    def __init__(self, first_result):
        self._first_result = first_result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._first_result


class _SyncDbStub:
    def __init__(self, *, results):
        self._results = results
        self.commit_count = 0

    def query(self, model):
        if model in self._results:
            return _QueryStub(self._results[model])
        raise AssertionError(f"Unexpected query model: {model}")

    def commit(self):
        self.commit_count += 1


def test_record_run_interactive_submission_updates_runtime_projection_without_message_parts(monkeypatch) -> None:
    captured_projection = {}

    def _fake_apply_interactive_submission_projection(db_arg, **kwargs):
        captured_projection["db"] = db_arg
        captured_projection.update(kwargs)

    monkeypatch.setattr(
        run_runtime_service,
        "_apply_interactive_submission_projection",
        _fake_apply_interactive_submission_projection,
    )

    existing_run = SimpleNamespace(
        id="run_1",
        conversation_id="conv_1",
        user_message_id="user_msg_1",
        status="paused",
        finished_at=datetime.now(timezone.utc),
    )
    pending_input = SimpleNamespace(
        run_id="run_1",
        message_id="assistant_msg_1",
        tool_call_id="call_input_1",
        status="pending",
        resolved_at=None,
        request_jsonb={
            "tool_name": "request_user_input",
            "request": {
                "title": "Choose a scope",
                "questions": [{"id": "q1", "question": "Scope?"}],
            },
            "result": {
                "status": "pending",
                "request": {
                    "title": "Choose a scope",
                    "questions": [{"id": "q1", "question": "Scope?"}],
                },
            },
        },
    )
    tool_call = SimpleNamespace(
        status="running",
        tool_name="request_user_input",
        result_jsonb={},
        error_jsonb={},
        finished_at=None,
    )
    state = SimpleNamespace(
        awaiting_user_input=True,
        active_run_id=None,
        last_assistant_message_id=None,
        updated_at=None,
    )
    db = _SyncDbStub(
        results={
            run_runtime_service.ChatRun: existing_run,
            run_runtime_service.PendingUserInput: pending_input,
            run_runtime_service.ToolCall: tool_call,
            run_runtime_service.ConversationState: state,
        }
    )

    result = run_runtime_service.record_run_interactive_submission(
        db,  # type: ignore[arg-type]
        run_id="run_1",
        conversation_id="conv_1",
        requested_tool_call_id="call_input_1",
        submission_result={
            "answers": [{"question_id": "q1", "option_label": "Detailed risk outlook"}],
        },
        expected_tool_name="request_user_input",
    )

    assert db.commit_count == 1
    assert result["assistant_message_id"] == "assistant_msg_1"
    assert pending_input.status == "resolved"
    assert pending_input.request_jsonb["result"]["status"] == "completed"
    assert tool_call.status == "completed"
    assert state.awaiting_user_input is False
    assert state.active_run_id is None
    assert state.last_assistant_message_id == "assistant_msg_1"
    assert captured_projection["conversation_id"] == "conv_1"
    assert captured_projection["run_id"] == "run_1"
    assert captured_projection["assistant_message_id"] == "assistant_msg_1"
    assert captured_projection["tool_call_id"] == "call_input_1"
    assert captured_projection["tool_name"] == "request_user_input"
    assert existing_run.status == "paused"


def test_mark_interactive_submission_resuming_marks_snapshot_running() -> None:
    snapshot = SimpleNamespace(
        conversation_id="conv_1",
        run_id="run_1",
        assistant_message_id="assistant_msg_1",
        status="paused",
        seq=14,
        status_label="Waiting for your input",
    )
    db = _SyncDbStub(
        results={
            run_runtime_service.ChatRunSnapshot: snapshot,
        }
    )

    run_runtime_service.mark_interactive_submission_resuming(
        sync_db=db,  # type: ignore[arg-type]
        conversation_id="conv_1",
        run_id="run_1",
        assistant_message_id="assistant_msg_1",
    )

    assert snapshot.assistant_message_id == "assistant_msg_1"
    assert snapshot.status == "running"
    assert snapshot.seq == 0
    assert snapshot.status_label == "Resuming"


def test_restore_interactive_submission_pending_restores_paused_state() -> None:
    captured_activity_items = {}

    def _fake_list_run_activity_items(*, db, run_id):  # type: ignore[no-untyped-def]
        _ = db, run_id
        return []

    def _fake_sync_run_activity_items(*, db, conversation_id, run_id, assistant_message_id, activity_items):  # type: ignore[no-untyped-def]
        _ = db
        captured_activity_items.update(
            {
                "conversation_id": conversation_id,
                "run_id": run_id,
                "assistant_message_id": assistant_message_id,
                "activity_items": activity_items,
            }
        )

    original_list = run_runtime_service.list_run_activity_items
    original_sync = run_runtime_service.sync_run_activity_items
    run_runtime_service.list_run_activity_items = _fake_list_run_activity_items
    run_runtime_service.sync_run_activity_items = _fake_sync_run_activity_items
    try:
        existing_run = SimpleNamespace(
            id="run_1",
            conversation_id="conv_1",
            status="paused",
            finished_at=None,
        )
        pending_input = SimpleNamespace(
            run_id="run_1",
            message_id="assistant_msg_1",
            tool_call_id="call_input_1",
            status="resolved",
            resolved_at=datetime.now(timezone.utc),
            request_jsonb={
                "tool_name": "request_user_input",
                "request": {
                    "title": "Choose a scope",
                    "questions": [{"id": "q1", "question": "Scope?"}],
                },
                "result": {
                    "status": "completed",
                    "answers": [{"question_id": "q1", "option_label": "Proceed"}],
                },
            },
        )
        tool_call = SimpleNamespace(
            status="completed",
            tool_name="request_user_input",
            result_jsonb={"status": "completed"},
            error_jsonb={},
            finished_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
        state = SimpleNamespace(
            awaiting_user_input=False,
            active_run_id=None,
            last_assistant_message_id=None,
            updated_at=None,
        )
        db = _SyncDbStub(
            results={
                run_runtime_service.ChatRun: existing_run,
                run_runtime_service.PendingUserInput: pending_input,
                run_runtime_service.ToolCall: tool_call,
                run_runtime_service.ConversationState: state,
            }
        )

        run_runtime_service.restore_interactive_submission_pending(
            db,  # type: ignore[arg-type]
            run_id="run_1",
            conversation_id="conv_1",
            tool_call_id="call_input_1",
            assistant_message_id="assistant_msg_1",
        )

        assert pending_input.status == "pending"
        assert pending_input.resolved_at is None
        assert pending_input.request_jsonb["result"]["status"] == "pending"
        assert tool_call.status == "running"
        assert tool_call.result_jsonb == {}
        assert tool_call.finished_at is None
        assert existing_run.status == "paused"
        assert state.awaiting_user_input is True
        assert state.active_run_id == "run_1"
        assert state.last_assistant_message_id == "assistant_msg_1"
        assert captured_activity_items["run_id"] == "run_1"
        assert captured_activity_items["assistant_message_id"] == "assistant_msg_1"
        assert captured_activity_items["activity_items"][0]["status"] == "running"
    finally:
        run_runtime_service.list_run_activity_items = original_list
        run_runtime_service.sync_run_activity_items = original_sync


def test_record_message_tool_call_submission_resumes_pending_interactive_tool(monkeypatch) -> None:
    captured = {}

    def _fake_record_run_interactive_submission(sync_db, **kwargs):
        _ = sync_db
        captured.update(kwargs)
        return {
            "run_id": kwargs["run_id"],
            "user_message_id": "user_msg_1",
            "assistant_message_id": kwargs.get("assistant_message_id") or "assistant_msg_1",
            "tool_name": "request_user_input",
        }

    monkeypatch.setattr(
        run_runtime_service,
        "record_run_interactive_submission",
        _fake_record_run_interactive_submission,
    )

    db = _SyncDbStub(
        results={
            run_runtime_service.Message: SimpleNamespace(
                id="assistant_msg_1",
                conversation_id="conv_1",
                role="assistant",
                run_id="run_1",
            ),
            run_runtime_service.PendingUserInput: SimpleNamespace(
                run_id="run_1",
                tool_call_id="call_input_2",
                status="pending",
            ),
        },
    )

    result = run_runtime_service.record_message_tool_call_submission(
        db,  # type: ignore[arg-type]
        conversation_id="conv_1",
        message_id="assistant_msg_1",
        tool_call_id="call_input_2",
        submission_result={"answers": [{"question_id": "q1", "option_label": "Proceed"}]},
    )

    assert result["resumed"] is True
    assert result["run_id"] == "run_1"
    assert captured["run_id"] == "run_1"
    assert captured["conversation_id"] == "conv_1"
    assert captured["requested_tool_call_id"] == "call_input_2"
    assert captured["assistant_message_id"] == "assistant_msg_1"


def test_record_message_tool_call_submission_updates_runtime_projection_without_message_parts(monkeypatch) -> None:
    captured_projection = {}

    def _fake_apply_interactive_submission_projection(db_arg, **kwargs):
        captured_projection["db"] = db_arg
        captured_projection.update(kwargs)

    monkeypatch.setattr(
        run_runtime_service,
        "_apply_interactive_submission_projection",
        _fake_apply_interactive_submission_projection,
    )

    tool_row = SimpleNamespace(
        status="running",
        tool_name="request_user_input",
        result_jsonb={},
        error_jsonb={"message": "stale"},
        finished_at=None,
    )
    db = _SyncDbStub(
        results={
            run_runtime_service.Message: SimpleNamespace(
                id="assistant_msg_2",
                conversation_id="conv_2",
                role="assistant",
                run_id="run_2",
            ),
            run_runtime_service.PendingUserInput: None,
            run_runtime_service.ToolCall: tool_row,
        },
    )

    result = run_runtime_service.record_message_tool_call_submission(
        db,  # type: ignore[arg-type]
        conversation_id="conv_2",
        message_id="assistant_msg_2",
        tool_call_id="call_input_3",
        submission_result={
            "status": "completed",
            "answers": [{"question_id": "q1", "option_label": "Proceed"}],
        },
    )

    assert result == {
        "run_id": "run_2",
        "user_message_id": None,
        "assistant_message_id": "assistant_msg_2",
        "tool_name": "request_user_input",
        "resumed": False,
    }
    assert db.commit_count == 1
    assert tool_row.status == "completed"
    assert tool_row.result_jsonb == {
        "status": "completed",
        "answers": [{"question_id": "q1", "option_label": "Proceed"}],
    }
    assert tool_row.error_jsonb == {}
    assert tool_row.finished_at is not None
    assert captured_projection == {
        "db": db,
        "conversation_id": "conv_2",
        "run_id": "run_2",
        "assistant_message_id": "assistant_msg_2",
        "tool_call_id": "call_input_3",
        "tool_name": "request_user_input",
        "request_payload": None,
        "result_payload": {
            "status": "completed",
            "answers": [{"question_id": "q1", "option_label": "Proceed"}],
        },
    }
