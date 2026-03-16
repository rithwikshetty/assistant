from app.chat.services.stream_event_handler import StreamEventHandler, is_openai_lifecycle_event
from app.chat.streaming_support import StreamState


def test_is_openai_lifecycle_event_handles_known_and_unknown_response_events() -> None:
    assert is_openai_lifecycle_event("response.created") is True
    assert is_openai_lifecycle_event("response.completed") is True
    assert is_openai_lifecycle_event("response.some_future_event") is True

    # Deltas are intentionally excluded from lifecycle tracking to avoid noisy
    # high-frequency state churn.
    assert is_openai_lifecycle_event("response.output_text.delta") is False
    assert is_openai_lifecycle_event("response.function_call_arguments.delta") is False
    assert is_openai_lifecycle_event("response.reasoning_summary_text.delta") is False

    assert is_openai_lifecycle_event("error") is False
    assert is_openai_lifecycle_event(None) is False


def test_handler_tracks_unknown_non_delta_response_event_without_streaming_it_to_clients() -> None:
    handler = StreamEventHandler()
    state = StreamState()

    chunks = handler.handle(
        {
            "type": "response.output_audio.transcript.done",
            "data": {"item_id": "audio_1"},
        },
        state,
    )

    assert chunks == [
        {
            "type": "run.status",
            "data": {"statusLabel": "Thinking"},
        }
    ]

    assert state.latest_response_lifecycle is not None
    assert state.latest_response_lifecycle["type"] == "response.output_audio.transcript.done"
    assert state.response_lifecycle_events[-1]["type"] == "response.output_audio.transcript.done"

    assert StreamEventHandler.is_checkpoint_relevant_event("response.output_audio.transcript.done") is False
    assert StreamEventHandler.is_live_usage_relevant_event("response.output_audio.transcript.done") is True


def test_handler_keeps_live_context_usage_server_side_only() -> None:
    handler = StreamEventHandler()
    state = StreamState()

    chunks = handler.handle(
        {
            "type": "live_context_usage",
            "data": {
                "input_tokens": 321,
                "total_tokens": 654,
            },
        },
        state,
    )

    assert chunks == []
    assert state.live_input_tokens == 321


def test_handler_keeps_streamed_content_server_side_until_runtime_projection_updates() -> None:
    handler = StreamEventHandler()
    state = StreamState()

    chunks = handler.handle({"type": "message", "content": "Hello world"}, state)

    assert chunks == [
        {
            "type": "content.delta",
            "data": {
                "delta": "Hello world",
                "statusLabel": "Generating response",
            },
        }
    ]
    assert state.full_response == "Hello world"
    assert state.current_step == "Generating response"


def test_generic_lifecycle_events_do_not_overwrite_custom_thinking_title() -> None:
    handler = StreamEventHandler()
    state = StreamState()

    handler.handle(
        {"type": "thinking_start", "content": {"id": "reasoning_1", "title": "Analysing project data"}},
        state,
    )

    handler.handle(
        {
            "type": "response.output_audio.transcript.done",
            "data": {"item_id": "audio_1"},
        },
        state,
    )

    assert state.current_step == "Analysing project data"


def test_generic_lifecycle_events_promote_generating_response_to_thinking() -> None:
    handler = StreamEventHandler()
    state = StreamState(current_step="Generating response")

    chunks = handler.handle(
        {
            "type": "response.created",
            "data": {"id": "resp_1"},
        },
        state,
    )

    assert chunks == [
        {
            "type": "run.status",
            "data": {"statusLabel": "Thinking"},
        }
    ]
    assert state.current_step == "Thinking"
