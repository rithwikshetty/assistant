from datetime import datetime, timezone
from types import SimpleNamespace

from app.chat.services.timeline_service import project_timeline_item


def test_project_timeline_item_includes_activity_items_for_final_assistant_rows() -> None:
    row = SimpleNamespace(
        message=SimpleNamespace(
            id="assist_done",
            run_id="run_1",
            role="assistant",
            status="completed",
            text="Final answer",
            model_provider=None,
            model_name=None,
            finish_reason=None,
            response_latency_ms=1250,
            cost_usd=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        parts=[],
        activity_items=[
            {
                "id": "activity_1",
                "run_id": "run_1",
                "item_key": "tool:call_1",
                "kind": "tool",
                "status": "completed",
                "title": "Web Search",
                "summary": "iran gulf shipping",
                "sequence": 3,
                "payload": {
                    "tool_call_id": "call_1",
                    "tool_name": "web_search",
                    "query": "iran gulf shipping",
                    "result": {"status": "completed"},
                },
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
        ],
        seq=1,
    )

    projected = project_timeline_item(row)

    assert projected is not None
    assert projected["id"] == "assist_done"
    assert projected["activity_items"] == row.activity_items
