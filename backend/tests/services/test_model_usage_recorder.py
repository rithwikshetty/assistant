from app.services.admin import model_usage_recorder as recorder


def test_record_model_usage_event_returns_none_without_event_id() -> None:
    event_id = recorder.record_model_usage_event(
        source="non_chat",
        operation_type="title_generation",
        provider="openai",
        model_name="gpt-4.1-mini",
        dispatch_worker=False,
    )

    assert event_id is None


def test_record_model_usage_event_returns_normalized_event_id() -> None:
    event_id = recorder.record_model_usage_event(
        source="non_chat",
        operation_type="title_generation",
        provider="openai",
        model_name="gpt-4.1-mini",
        event_id=" usage-123 ",
        dispatch_worker=False,
    )

    assert event_id == "usage-123"


def test_dispatch_model_usage_outbox_worker_is_disabled_in_open_source_build() -> None:
    assert recorder.dispatch_model_usage_outbox_worker(force=True) is False
