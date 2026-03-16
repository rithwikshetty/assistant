from app.chat.streaming_support import StreamState


def test_register_tool_call_dedupes_replayed_call_id() -> None:
    state = StreamState()

    first = state.register_tool_call(
        name="retrieval_web_search",
        call_id="call_dup",
        position=0,
        sequence=1,
        arguments={"query": "first"},
    )
    second = state.register_tool_call(
        name="retrieval_web_search",
        call_id="call_dup",
        position=12,
        sequence=2,
        arguments={"query": "second"},
    )

    assert first == "call_dup"
    assert second == "call_dup"
    assert len(state.tool_markers) == 1
    assert state.open_tool_idx_by_call_id == {"call_dup": 0}
    assert state.tool_markers[0].get("arguments") == {"query": "first"}


def test_register_tool_call_does_not_reopen_completed_marker() -> None:
    state = StreamState()

    state.register_tool_call(
        name="request_user_input",
        call_id="call_done",
        position=0,
        sequence=1,
    )
    state.record_tool_result(
        call_id="call_done",
        name="request_user_input",
        payload={"status": "completed", "answers": []},
    )

    state.register_tool_call(
        name="request_user_input",
        call_id="call_done",
        position=8,
        sequence=2,
    )

    assert len(state.tool_markers) == 1
    assert "result" in state.tool_markers[0]
    assert "call_done" not in state.open_tool_idx_by_call_id
