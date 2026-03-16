from app.chat.services.run_activity_service import build_run_activity_items_from_stream_state
from app.chat.streaming_support import StreamState


def test_build_run_activity_items_mirrors_interactive_request_payload() -> None:
    state = StreamState(
        tool_markers=[
            {
                "name": "request_user_input",
                "call_id": "call_1",
                "seq": 2,
                "result": {
                    "status": "pending",
                    "interaction_type": "user_input",
                    "request": {
                        "tool": "request_user_input",
                        "title": "Need context",
                        "prompt": "Pick one",
                        "questions": [
                            {
                                "id": "q1",
                                "question": "Priority?",
                                "options": [
                                    {"label": "Fast", "description": "Move quickly with a lean answer"},
                                    {"label": "Deep", "description": "Spend longer for a fuller analysis"},
                                ],
                            }
                        ],
                    },
                },
            }
        ]
    )

    items = build_run_activity_items_from_stream_state(
        run_id="run_1",
        state=state,
    )

    assert len(items) == 1
    assert items[0]["payload"]["request"] == {
        "tool": "request_user_input",
        "title": "Need context",
        "prompt": "Pick one",
        "questions": [
            {
                "id": "q1",
                "question": "Priority?",
                "options": [
                    {"label": "Fast", "description": "Move quickly with a lean answer"},
                    {"label": "Deep", "description": "Spend longer for a fuller analysis"},
                ],
            }
        ],
    }
    assert items[0]["payload"]["result"]["request"] == items[0]["payload"]["request"]
