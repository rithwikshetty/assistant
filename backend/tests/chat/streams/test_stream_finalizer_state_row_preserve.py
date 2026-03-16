from datetime import datetime, timezone
from types import SimpleNamespace

from app.chat.services.stream_finalizer import StreamFinalizer
from app.chat.streaming_support import StreamState


def test_update_state_row_preserves_existing_cumulative_when_missing_from_payload(monkeypatch) -> None:
    finalizer = StreamFinalizer()
    state_row = SimpleNamespace(
        last_assistant_message_id=None,
        awaiting_user_input=False,
        active_run_id=None,
        input_tokens=900,
        output_tokens=100,
        total_tokens=1_000,
        max_context_tokens=1_050_000,
        remaining_context_tokens=1_049_000,
        cumulative_input_tokens=5_000,
        cumulative_output_tokens=700,
        cumulative_total_tokens=5_700,
        updated_at=None,
    )

    monkeypatch.setattr(finalizer, "_ensure_state_row", lambda **kwargs: state_row)

    updated = finalizer._update_state_row(
        db=object(),  # type: ignore[arg-type]
        conversation_id="conv_1",
        run=None,
        run_status="completed",
        conversation_usage_payload={
            "input_tokens": 250,
            "output_tokens": 0,
            "total_tokens": 250,
            "max_context_tokens": 1_050_000,
            "remaining_context_tokens": 1_049_750,
        },
        usage_calculator=SimpleNamespace(),  # type: ignore[arg-type]
        model_for_context="gpt-5.4",
        working_state=StreamState(full_response="Done", live_input_tokens=250),
        now=datetime.now(timezone.utc),
        assistant_message_id="assistant_1",
    )

    assert updated.input_tokens == 250
    assert updated.total_tokens == 250
    assert updated.cumulative_input_tokens == 5_000
    assert updated.cumulative_output_tokens == 700
    assert updated.cumulative_total_tokens == 5_700
