from app.chat.usage_calculator import UsageCalculator


def test_usage_calculator_extracts_reasoning_tokens_from_output_details() -> None:
    calc = UsageCalculator()
    summary = calc.summarize(
        [
            {
                "id": "resp_1",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 12,
                    "output_tokens_details": {"reasoning_tokens": 7},
                },
            },
            {
                "id": "resp_2",
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 8,
                    "reasoning_tokens": 3,
                },
            },
        ],
        provider="openai",
    )

    assert summary.total_input == 15
    assert summary.total_output == 20
    assert summary.reasoning_output == 10


def test_usage_calculator_deduplicates_reasoning_tokens_for_same_response_id() -> None:
    calc = UsageCalculator()
    summary = calc.summarize(
        [
            {
                "id": "resp_same",
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 13,
                    "output_tokens_details": {"reasoning_tokens": 9},
                },
            },
            {
                # Duplicate response snapshot for the same id should not double count.
                "id": "resp_same",
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 13,
                    "output_tokens_details": {"reasoning_tokens": 9},
                },
            },
        ],
        provider="openai",
    )

    assert summary.total_input == 11
    assert summary.total_output == 13
    assert summary.reasoning_output == 9


def test_usage_calculator_does_not_double_count_cached_tokens() -> None:
    calc = UsageCalculator()
    summary = calc.summarize(
        [
            {
                "id": "resp_1",
                "usage": {
                    "input_tokens": 16097,
                    "output_tokens": 1079,
                    "input_tokens_details": {"cached_tokens": 10240},
                },
            },
            {
                "id": "resp_2",
                "usage": {
                    "input_tokens": 9949,
                    "output_tokens": 396,
                    "input_tokens_details": {"cached_tokens": 6912},
                },
            },
        ],
        provider="openai",
    )

    # OpenAI input_tokens already includes cached tokens.
    assert summary.total_input == 26046
    assert summary.total_output == 1475
