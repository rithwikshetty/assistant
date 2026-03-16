from datetime import datetime, timezone
from types import SimpleNamespace

from app.chat.services.conversation_service import build_conversation_response


class _NoQueryDB:
    def query(self, *args, **kwargs):  # pragma: no cover - this should never be hit in these unit tests
        _ = (args, kwargs)
        raise AssertionError("Unexpected query() call")


def _conversation(**overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "id": "conv_123",
        "title": "Conversation",
        "created_at": now,
        "updated_at": now,
        "last_message_at": now,
        "project_id": None,
        "parent_conversation_id": None,
        "branch_from_message_id": None,
        "archived": False,
        "archived_at": None,
        "archived_by": None,
        "is_pinned": False,
        "pinned_at": None,
        "user_id": "user_123",
        "conversation_metadata": {},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _state(**overrides):
    payload = {
        "awaiting_user_input": False,
        "input_tokens": 640,
        "output_tokens": 120,
        "total_tokens": 760,
        "max_context_tokens": 128000,
        "remaining_context_tokens": 127240,
        "cumulative_input_tokens": 2048,
        "cumulative_output_tokens": 512,
        "cumulative_total_tokens": 2560,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_build_conversation_response_includes_context_usage_from_state() -> None:
    response = build_conversation_response(
        conversation=_conversation(),
        db=_NoQueryDB(),
        current_user=SimpleNamespace(id="user_123", role="user"),
        message_count=3,
        assistant_message_count=1,
        awaiting_user_input=None,
        conversation_state=_state(awaiting_user_input=True),
        owner_info=("Owner", "owner@example.com"),
        skip_feedback_check=True,
    )

    assert response.awaiting_user_input is True
    assert response.context_usage is not None
    assert response.context_usage.input_tokens == 640
    assert response.context_usage.total_tokens == 760
    assert response.context_usage.current_context_tokens == 760
    assert response.context_usage.peak_context_tokens == 760
    assert response.context_usage.max_context_tokens == 128000


def test_build_conversation_response_omits_context_usage_when_state_has_no_usage() -> None:
    response = build_conversation_response(
        conversation=_conversation(),
        db=_NoQueryDB(),
        current_user=SimpleNamespace(id="user_123", role="user"),
        message_count=1,
        assistant_message_count=0,
        awaiting_user_input=None,
        conversation_state=_state(
            awaiting_user_input=False,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            max_context_tokens=None,
            remaining_context_tokens=None,
            cumulative_input_tokens=None,
            cumulative_output_tokens=None,
            cumulative_total_tokens=None,
        ),
        owner_info=("Owner", "owner@example.com"),
        skip_feedback_check=True,
    )

    assert response.awaiting_user_input is False
    assert response.context_usage is None


def test_build_conversation_response_reconstructs_current_context_after_compaction() -> None:
    response = build_conversation_response(
        conversation=_conversation(),
        db=_NoQueryDB(),
        current_user=SimpleNamespace(id="user_123", role="user"),
        message_count=4,
        assistant_message_count=2,
        awaiting_user_input=False,
        conversation_state=_state(
            input_tokens=1000,
            output_tokens=120,
            total_tokens=1000,
            max_context_tokens=1200,
            remaining_context_tokens=900,
            cumulative_input_tokens=5000,
            cumulative_output_tokens=900,
            cumulative_total_tokens=5900,
        ),
        owner_info=("Owner", "owner@example.com"),
        skip_feedback_check=True,
    )

    assert response.context_usage is not None
    assert response.context_usage.current_context_tokens == 300
    # Peak can remain higher than current after compaction.
    assert response.context_usage.peak_context_tokens == 1000


def test_build_conversation_response_clamps_current_when_state_is_inconsistent() -> None:
    response = build_conversation_response(
        conversation=_conversation(),
        db=_NoQueryDB(),
        current_user=SimpleNamespace(id="user_123", role="user"),
        message_count=2,
        assistant_message_count=1,
        awaiting_user_input=False,
        conversation_state=_state(
            input_tokens=2400,
            output_tokens=100,
            total_tokens=2500,
            max_context_tokens=1200,
            remaining_context_tokens=None,
            cumulative_input_tokens=7000,
            cumulative_output_tokens=1400,
            cumulative_total_tokens=8400,
        ),
        owner_info=("Owner", "owner@example.com"),
        skip_feedback_check=True,
    )

    assert response.context_usage is not None
    # Should never exceed max_context_tokens, even with stale/odd persisted totals.
    assert response.context_usage.current_context_tokens == 1200
    assert response.context_usage.peak_context_tokens == 1200


def test_build_conversation_response_includes_low_compaction_trigger(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.chat.services.conversation_service.settings.openai_compact_trigger_tokens",
        16,
        raising=False,
    )
    response = build_conversation_response(
        conversation=_conversation(),
        db=_NoQueryDB(),
        current_user=SimpleNamespace(id="user_123", role="user"),
        message_count=3,
        assistant_message_count=1,
        awaiting_user_input=False,
        conversation_state=_state(
            input_tokens=220,
            output_tokens=40,
            total_tokens=260,
            max_context_tokens=1000,
            remaining_context_tokens=740,
            cumulative_input_tokens=400,
            cumulative_output_tokens=100,
            cumulative_total_tokens=500,
        ),
        owner_info=("Owner", "owner@example.com"),
        skip_feedback_check=True,
    )

    assert response.context_usage is not None
    assert response.context_usage.compact_trigger_tokens == 16


def test_build_conversation_response_respects_precomputed_feedback_count() -> None:
    response = build_conversation_response(
        conversation=_conversation(
            conversation_metadata={
                "feedback": {
                    "messages_per_cycle": 5,
                },
            },
        ),
        db=_NoQueryDB(),
        current_user=SimpleNamespace(id="user_123", role="user"),
        message_count=10,
        assistant_message_count=5,
        feedback_count=1,
        awaiting_user_input=False,
        conversation_state=_state(),
        owner_info=("Owner", "owner@example.com"),
    )

    assert response.requires_feedback is False
