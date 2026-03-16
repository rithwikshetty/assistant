from app.services.usage_service import _format_process_label, _sort_model_usage_rows


def test_format_process_label_uses_known_mapping() -> None:
    assert _format_process_label("project_search_query_embedding") == "Project search embedding"
    assert _format_process_label("retrieval_spons_synthesis") == "Spon's retrieval synthesis"


def test_format_process_label_humanizes_unknown_operation() -> None:
    assert _format_process_label("custom_quality_check") == "Custom Quality Check"


def test_format_process_label_defaults_when_missing() -> None:
    assert _format_process_label("") == "Unknown operation"
    assert _format_process_label(None) == "Unknown operation"


def test_sort_model_usage_rows_orders_by_usage_then_model_name() -> None:
    rows = [
        {"model": "openai/gpt-4.1", "message_count": 5},
        {"model": "openai/gpt-4.1-mini", "message_count": 10},
        {"model": "google/gemini", "message_count": 10},
    ]

    ordered = _sort_model_usage_rows(rows)

    assert [row["model"] for row in ordered] == [
        "google/gemini",
        "openai/gpt-4.1-mini",
        "openai/gpt-4.1",
    ]
