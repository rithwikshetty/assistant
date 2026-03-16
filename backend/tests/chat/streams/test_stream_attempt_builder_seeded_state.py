from app.chat.services.stream_attempt_builder import StreamAttemptBuilder


def test_build_seeded_state_rehydrates_open_tool_index() -> None:
    state = StreamAttemptBuilder._build_seeded_state(
        seed_response_text="seed",
        seed_tool_markers=[
            {"name": "retrieval_web_search", "call_id": " call_open ", "seq": 2},
            {"name": "request_user_input", "call_id": "call_done", "seq": 3, "result": {"status": "completed"}},
        ],
        seed_reasoning_summaries=None,
        seed_compaction_markers=None,
    )

    assert state.full_response == "seed"
    assert state.tool_markers[0]["call_id"] == "call_open"
    assert state.tool_markers[1]["call_id"] == "call_done"
    assert state.open_tool_idx_by_call_id == {"call_open": 0}
