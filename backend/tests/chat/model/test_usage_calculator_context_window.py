from app.chat.usage_calculator import UsageCalculator


def test_create_conversation_usage_uses_total_tokens_for_remaining_context() -> None:
    calc = UsageCalculator()

    conversation_usage, _ = calc.create_conversation_usage(
        existing_metadata={},
        usage_payload={
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
        },
        context_window=500,
    )

    assert conversation_usage.get("max_context_tokens") == 500
    assert conversation_usage.get("remaining_context_tokens") == 340
    assert conversation_usage.get("current_context_tokens") == 160
    assert conversation_usage.get("peak_context_tokens") == 160


def test_create_conversation_usage_falls_back_to_input_tokens_when_total_missing() -> None:
    calc = UsageCalculator()

    conversation_usage, _ = calc.create_conversation_usage(
        existing_metadata={},
        usage_payload={
            "input_tokens": 90,
            "output_tokens": 0,
        },
        context_window=500,
    )

    assert conversation_usage.get("max_context_tokens") == 500
    assert conversation_usage.get("remaining_context_tokens") == 410
    assert conversation_usage.get("current_context_tokens") == 90
    assert conversation_usage.get("peak_context_tokens") == 90


def test_create_conversation_usage_tracks_peak_context_across_turns() -> None:
    calc = UsageCalculator()
    first_usage, metadata = calc.create_conversation_usage(
        existing_metadata={},
        usage_payload={
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
        },
        context_window=500,
    )
    assert first_usage.get("peak_context_tokens") == 160

    second_usage, _ = calc.create_conversation_usage(
        existing_metadata=metadata,
        usage_payload={
            "input_tokens": 70,
            "output_tokens": 5,
            "total_tokens": 75,
        },
        context_window=500,
    )
    assert second_usage.get("current_context_tokens") == 75
    assert second_usage.get("peak_context_tokens") == 160
