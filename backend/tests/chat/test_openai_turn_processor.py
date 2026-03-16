from app.chat.openai_model.turn_processor import OpenAIStreamTurnProcessor


def _processor(**overrides):
    return OpenAIStreamTurnProcessor(
        provider_name=overrides.get("provider_name", "openai"),
        model=overrides.get("model", "gpt-5.4"),
        logger=overrides.get("logger"),
        use_openai_websocket=overrides.get("use_openai_websocket", True),
        seen_uncaptured_event_types=overrides.get("seen_uncaptured_event_types", set()),
        extract_text_from_response_payload=overrides.get(
            "extract_text_from_response_payload", lambda payload: payload.get("text", "") if isinstance(payload, dict) else ""
        ),
        extract_reasoning_replay_items=overrides.get(
            "extract_reasoning_replay_items", lambda payload: payload.get("replay", []) if isinstance(payload, dict) else []
        ),
        extract_reasoning_summary_part_text=overrides.get(
            "extract_reasoning_summary_part_text", lambda part: part.get("text", "") if isinstance(part, dict) else ""
        ),
        merge_reasoning_summary_text=overrides.get(
            "merge_reasoning_summary_text",
            lambda *, existing, incoming, treat_as_snapshot: (existing + incoming, incoming),
        ),
        extract_reasoning_title=overrides.get("extract_reasoning_title", lambda text: "Thinking" if text is not None else None),
    )


def test_processor_retries_on_websocket_connection_limit_reached() -> None:
    processor = _processor()

    decision = processor.process_event(
        {
            "type": "response.failed",
            "response": {"error": {"code": "websocket_connection_limit_reached", "message": "limit"}},
        }
    )

    assert decision.break_turn is True
    assert decision.terminate_stream is False
    assert processor.retry_with_full_context is True
    assert processor.reconnect_websocket is True


def test_processor_keeps_first_tool_call_and_updates_replayed_arguments() -> None:
    processor = _processor()

    first = processor.process_event(
        {
            "type": "response.output_item.added",
            "item": {
                "type": "function_call",
                "id": "item_1",
                "call_id": "call_1",
                "name": "retrieval_web_search",
                "arguments": '{"query":"steel"}',
            },
        }
    )
    assert [evt.get("type") for evt in first.emitted_events] == ["tool_call", "response.output_item.added"]

    replay = processor.process_event(
        {
            "type": "response.output_item.added",
            "item": {
                "type": "function_call",
                "id": "item_1",
                "call_id": "call_1",
                "name": "retrieval_web_search",
                "arguments": '{"query":"steel rates"}',
            },
        }
    )
    assert [evt.get("type") for evt in replay.emitted_events] == ["response.output_item.added"]
    assert len(processor.tool_calls) == 1
    assert processor.tool_calls[0]["arguments"] == '{"query":"steel rates"}'


def test_processor_emits_raw_response_and_updates_response_tracking() -> None:
    processor = _processor(
        extract_text_from_response_payload=lambda payload: payload.get("synthetic_text", ""),
        extract_reasoning_replay_items=lambda payload: payload.get("replay", []),
    )

    decision = processor.process_event(
        {
            "type": "response.completed",
            "response": {
                "id": "resp_123",
                "synthetic_text": "done text",
                "replay": [{"type": "reasoning", "encrypted_content": "abc", "summary": []}],
            },
        }
    )

    event_types = [evt.get("type") for evt in decision.emitted_events]
    assert event_types == ["response_complete", "response.completed", "raw_response"]
    assert processor.latest_response_id == "resp_123"
    assert processor.latest_response_reasoning_items == [
        {"type": "reasoning", "encrypted_content": "abc", "summary": []}
    ]
