from app.chat.services.stream_event_handler import StreamEventHandler
from app.chat.streaming_support import StreamState


def test_tool_arguments_are_tracked_without_streaming_tool_detail_events() -> None:
    handler = StreamEventHandler()
    state = StreamState()

    handler.handle(
        {
            "type": "tool_call",
            "name": "web_search",
            "call_id": "call_1",
        },
        state,
    )

    chunks = handler.handle(
        {
            "type": "tool_arguments",
            "name": "web_search",
            "call_id": "call_1",
            "content": {"query": "latest construction inflation"},
        },
        state,
    )

    assert chunks == []
    assert state.tool_markers[0]["arguments"] == {"query": "latest construction inflation"}


def test_tool_events_include_position_and_sequence_for_live_projection() -> None:
    handler = StreamEventHandler()
    state = StreamState(full_response="I'll check the market first. ")

    started = handler.handle(
        {
            "type": "tool_call",
            "name": "web_search",
            "call_id": "call_1",
        },
        state,
    )

    assert started == [
        {
            "type": "tool.started",
            "data": {
                "toolCallId": "call_1",
                "toolName": "web_search",
                "arguments": {},
                "statusLabel": "Using web_search",
                "position": len("I'll check the market first. "),
                "sequence": 1,
            },
        }
    ]

    completed = handler.handle(
        {
            "type": "tool_result",
            "name": "web_search",
            "call_id": "call_1",
            "content": {"status": "completed", "count": 2},
        },
        state,
    )

    assert completed[0] == {
        "type": "tool.completed",
        "data": {
            "toolCallId": "call_1",
            "toolName": "web_search",
            "result": {"status": "completed", "count": 2},
            "position": len("I'll check the market first. "),
            "sequence": 1,
        },
    }
