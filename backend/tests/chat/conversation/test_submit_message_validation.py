import pytest
from fastapi import HTTPException

from app.chat.services.submit_runtime_service import (
    _build_existing_run_reuse_response,
    _build_stream_context,
    normalize_message_content,
)
from app.database.models import ChatRun, User


def test_normalize_message_content_trims_valid_content() -> None:
    assert normalize_message_content("  hello world  ") == "hello world"


def test_normalize_message_content_rejects_blank_content() -> None:
    with pytest.raises(HTTPException) as exc:
        normalize_message_content("   \n\t   ")
    assert exc.value.status_code == 400
    assert exc.value.detail == "Message content is required"


def test_build_existing_run_reuse_response_maps_existing_run_fields() -> None:
    existing_run = ChatRun(
        id="run_123",
        conversation_id="conv_123",
        user_message_id="event_123",
        status="paused",
    )

    payload = _build_existing_run_reuse_response(
        existing_run=existing_run,
    )

    assert payload == {
        "user_message_id": "event_123",
        "status": "queued",
        "run_id": "run_123",
        "queue_position": 0,
        "reuse_only": True,
    }


def test_build_stream_context_includes_prefetched_metadata() -> None:
    current_user = User(
        id="user_123",
        email="user@example.com",
        name="Rithwik",
        user_tier="power",
        model_override="gpt-5",
    )

    stream_ctx = _build_stream_context(
        user_content="hello",
        attachments_meta=[{"id": "file_1"}],
        is_admin=False,
        is_new_conversation=True,
        current_user=current_user,
        effective_timezone="America/New_York",
        project_ctx={"project_name": "Alpha"},
        submit_started=123.45,
        submit_trace_id="trace_123",
    )

    assert stream_ctx.user_content == "hello"
    assert stream_ctx.attachments_meta == [{"id": "file_1"}]
    assert stream_ctx.is_new_conversation is True
    assert stream_ctx.prefetched_context is not None
    assert stream_ctx.prefetched_context["user"]["id"] == "user_123"
    assert stream_ctx.prefetched_context["user"]["timezone"] == "America/New_York"
    assert "azure_id_token" not in stream_ctx.prefetched_context["user"]
    assert stream_ctx.prefetched_context["conversation_context"] == {"project_name": "Alpha"}
    assert stream_ctx.prefetched_context["timing"]["trace_id"] == "trace_123"
