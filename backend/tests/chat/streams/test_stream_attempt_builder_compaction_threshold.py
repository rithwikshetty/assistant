from app.chat.services.stream_attempt_builder import StreamAttemptBuilder
from app.config.settings import settings


def test_openai_compact_trigger_tokens_injected_into_tool_context(monkeypatch) -> None:
    """prepare_attempt should inject openai_compact_trigger_tokens from settings."""
    monkeypatch.setattr(settings, "openai_compact_trigger_tokens", 180_000, raising=False)

    builder = StreamAttemptBuilder()

    # Minimal required arguments for prepare_attempt
    attempt = builder.prepare_attempt(
        provider_name="openai",
        effective_model="gpt-5.4",
        reasoning_effort="none",
        conversation_history=[],
        user_prompt="hello",
        current_message_attachments=None,
        tool_context={"provider": "openai"},
        is_admin=False,
        user_name="Test",
        current_date="2026-03-01",
        current_time="12:00",
        user_timezone="UTC",
        project_name=None,
        project_description=None,
        project_custom_instructions=None,
        project_files_summary=None,
        user_custom_instructions=None,
        resume_assistant_message_id=None,
        seed_response_text=None,
        seed_tool_markers=None,
        seed_reasoning_summaries=None,
        seed_compaction_markers=None,
        file_service=None,
    )

    tool_ctx = attempt.stream_kwargs.get("tool_context", {})
    assert tool_ctx.get("openai_compact_trigger_tokens") == 180_000


def test_openai_compact_trigger_not_injected_for_azure(monkeypatch) -> None:
    """Azure provider should NOT get openai_compact_trigger_tokens."""
    monkeypatch.setattr(settings, "openai_compact_trigger_tokens", 180_000, raising=False)

    builder = StreamAttemptBuilder()

    attempt = builder.prepare_attempt(
        provider_name="azure",
        effective_model="gpt-5.1",
        reasoning_effort="none",
        conversation_history=[],
        user_prompt="hello",
        current_message_attachments=None,
        tool_context={"provider": "azure"},
        is_admin=False,
        user_name="Test",
        current_date="2026-03-01",
        current_time="12:00",
        user_timezone="UTC",
        project_name=None,
        project_description=None,
        project_custom_instructions=None,
        project_files_summary=None,
        user_custom_instructions=None,
        resume_assistant_message_id=None,
        seed_response_text=None,
        seed_tool_markers=None,
        seed_reasoning_summaries=None,
        seed_compaction_markers=None,
        file_service=None,
    )

    tool_ctx = attempt.stream_kwargs.get("tool_context", {})
    assert "openai_compact_trigger_tokens" not in tool_ctx


def test_openai_compact_trigger_tokens_low_threshold_injected(monkeypatch) -> None:
    """Very low compaction thresholds should propagate unchanged for OpenAI runs."""
    monkeypatch.setattr(settings, "openai_compact_trigger_tokens", 16, raising=False)

    builder = StreamAttemptBuilder()

    attempt = builder.prepare_attempt(
        provider_name="openai",
        effective_model="gpt-5.4",
        reasoning_effort="none",
        conversation_history=[],
        user_prompt="force early compaction check",
        current_message_attachments=None,
        tool_context={"provider": "openai"},
        is_admin=False,
        user_name="Test",
        current_date="2026-03-01",
        current_time="12:00",
        user_timezone="UTC",
        project_name=None,
        project_description=None,
        project_custom_instructions=None,
        project_files_summary=None,
        user_custom_instructions=None,
        resume_assistant_message_id=None,
        seed_response_text=None,
        seed_tool_markers=None,
        seed_reasoning_summaries=None,
        seed_compaction_markers=None,
        file_service=None,
    )

    tool_ctx = attempt.stream_kwargs.get("tool_context", {})
    assert tool_ctx.get("openai_compact_trigger_tokens") == 16
