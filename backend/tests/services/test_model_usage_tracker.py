from decimal import Decimal

from app.services import model_usage_tracker as tracker


def test_record_estimated_model_usage_returns_cost_and_normalizes_payload(monkeypatch) -> None:
    captured = {}

    def _capture(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return "evt_123"

    monkeypatch.setattr(tracker, "record_model_usage_event", _capture)

    cost = tracker.record_estimated_model_usage(
        provider="openai",
        model_name="gpt-4.1",
        operation_type="suggestion_generation",
        usage={
            "input_tokens": "1000",
            "output_tokens": 200,
            "total_tokens": 1200,
            "cache_creation_input_tokens": -2,
            "cache_read_input_tokens": 15,
            "duration_seconds": "3.5",
            "usage_metadata": "invalid-shape",
        },
        analytics_context={
            "db": "db-session",
            "user_id": "user-1",
            "conversation_id": "conversation-1",
            "project_id": "project-1",
        },
        latency_ms=-18,
    )

    assert isinstance(cost, Decimal)
    assert cost > 0
    assert captured["db"] == "db-session"
    assert captured["operation_type"] == "suggestion_generation"
    assert captured["user_id"] == "user-1"
    assert captured["conversation_id"] == "conversation-1"
    assert captured["project_id"] == "project-1"
    assert captured["input_tokens"] == 1000
    assert captured["output_tokens"] == 200
    assert captured["total_tokens"] == 1200
    assert captured["cache_creation_input_tokens"] == 0
    assert captured["cache_read_input_tokens"] == 15
    assert captured["latency_ms"] == 0
    assert captured["usage_metadata"] == {}
