from datetime import datetime, timezone
from types import SimpleNamespace

from app.chat.services.timeline_service import project_timeline_item


def _row(*, message_id: str, role: str, status: str):
    return SimpleNamespace(
        message=SimpleNamespace(
            id=message_id,
            run_id="run_1",
            role=role,
            status=status,
            text="hello",
            model_provider=None,
            model_name=None,
            finish_reason=None,
            response_latency_ms=None,
            cost_usd=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        parts=[],
        activity_items=[],
        seq=1,
    )


def test_project_timeline_item_skips_partial_assistant_rows() -> None:
    row = _row(message_id="assist_partial", role="assistant", status="streaming")

    assert project_timeline_item(row) is None


def test_project_timeline_item_keeps_terminal_assistant_rows() -> None:
    row = _row(message_id="assist_done", role="assistant", status="completed")

    projected = project_timeline_item(row)

    assert projected is not None
    assert projected["id"] == "assist_done"
    assert projected["type"] == "assistant_message_final"


def test_project_timeline_item_skips_cancelled_user_rows() -> None:
    row = _row(message_id="user_cancelled", role="user", status="cancelled")

    assert project_timeline_item(row) is None


def test_project_timeline_item_keeps_user_request_id_in_payload() -> None:
    row = _row(message_id="user_1", role="user", status="completed")
    row.parts = [
        SimpleNamespace(
            part_type="metadata",
            payload_jsonb={
                "request_id": "req_1",
                "attachments": [{"id": "file_1"}],
            },
        )
    ]

    projected = project_timeline_item(row)

    assert projected is not None
    assert projected["type"] == "user_message"
    assert projected["payload"]["request_id"] == "req_1"
    assert projected["payload"]["attachments"] == [{"id": "file_1"}]
