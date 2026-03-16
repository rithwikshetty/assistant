from app.chat.services.stream_event_handler import StreamEventHandler
from app.chat.streaming_support import StreamState


def test_reasoning_delta_is_persisted_but_not_streamed() -> None:
    handler = StreamEventHandler()
    state = StreamState()

    start_chunks = handler.handle(
        {"type": "thinking_start", "content": {"id": "reasoning_1", "title": "Thinking"}},
        state,
    )
    assert start_chunks == [
        {
            "type": "run.status",
            "data": {"statusLabel": "Thinking"},
        }
    ]

    delta_chunks = handler.handle(
        {"type": "thinking_delta", "content": {"id": "reasoning_1", "text": "Internal chain-of-thought"}},
        state,
    )
    assert delta_chunks == []
    assert state.thinking_buffers["thinking_1"] == "Internal chain-of-thought"

    end_chunks = handler.handle(
        {"type": "thinking_end", "content": {"id": "reasoning_1"}},
        state,
    )
    assert end_chunks == [
        {
            "type": "run.status",
            "data": {"statusLabel": "Thinking"},
        }
    ]

    assert len(state.reasoning_summaries) == 1
    assert state.reasoning_summaries[0]["raw_text"] == "Internal chain-of-thought"


def test_thinking_start_uses_reasoning_title_for_current_step() -> None:
    handler = StreamEventHandler()
    state = StreamState()

    handler.handle(
        {"type": "thinking_start", "content": {"id": "reasoning_1", "title": "Analysing project data"}},
        state,
    )

    assert state.current_step == "Analysing project data"
