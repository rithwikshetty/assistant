from types import SimpleNamespace

from app.chat.services.timeline_service import project_timeline_item


def test_project_timeline_item_uses_assistant_text_without_part_projection() -> None:
    row = SimpleNamespace(
        message=SimpleNamespace(
            id="msg_1",
            run_id="run_1",
            role="assistant",
            status="completed",
            text="Final answer",
            model_provider=None,
            model_name=None,
            finish_reason=None,
            response_latency_ms=None,
            cost_usd=None,
            created_at=None,
        ),
        parts=[
            SimpleNamespace(
                part_type="tool_call",
                phase="worklog",
                text=None,
                payload_jsonb={
                    "toolName": "retrieval_project_files",
                    "toolCallId": "call_1",
                    "args": {"query": "Hospital Bid"},
                },
            ),
            SimpleNamespace(
                part_type="user_input_response",
                phase="worklog",
                text=None,
                payload_jsonb={
                    "toolName": "request_user_input",
                    "toolCallId": "call_1",
                    "result": {"status": "completed", "answers": [{"question_id": "q1", "option_label": "Proceed"}]},
                },
            ),
        ],
        activity_items=[],
        seq=1,
    )

    projected = project_timeline_item(row)  # type: ignore[arg-type]

    assert projected is not None
    assert projected["text"] == "Final answer"
