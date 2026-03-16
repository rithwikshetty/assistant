from app.chat.streaming import ChatStreamingManager
from app.chat.streaming_support import StreamState


def test_persistence_signature_changes_for_semantic_runtime_state() -> None:
    manager = ChatStreamingManager()
    state = StreamState(full_response="hello")

    base_signature = manager._persistence_signature(state)

    state.tool_markers.append({"call_id": "call_1", "name": "search"})
    tool_signature = manager._persistence_signature(state)
    assert tool_signature != base_signature

    state.tool_markers[0]["query"] = "find docs"
    query_signature = manager._persistence_signature(state)
    assert query_signature != tool_signature

    state.pending_input_payload = {"pendingRequests": [{"id": "req_1"}]}
    pending_signature = manager._persistence_signature(state)
    assert pending_signature != query_signature


def test_live_runtime_projection_persists_for_text_only_growth() -> None:
    manager = ChatStreamingManager()
    state = StreamState(full_response="hello")

    base_signature = manager._persistence_signature(state)

    state.full_response = "hello world"

    assert manager._should_persist_live_runtime_projection(
        state=state,
        last_signature=base_signature,
        last_text_len=len("hello"),
    )


def test_live_runtime_projection_skips_unchanged_runtime_state() -> None:
    manager = ChatStreamingManager()
    state = StreamState(full_response="hello")

    base_signature = manager._persistence_signature(state)

    assert not manager._should_persist_live_runtime_projection(
        state=state,
        last_signature=base_signature,
        last_text_len=len("hello"),
    )
