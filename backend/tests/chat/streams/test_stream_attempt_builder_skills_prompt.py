from app.chat.services.stream_attempt_builder import StreamAttemptBuilder
from app import prompts as prompt_module


def test_build_system_prompt_passes_db_skills_section(monkeypatch) -> None:
    captured = {}

    def _fake_prompt_builder(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return "BASE"

    monkeypatch.setattr(prompt_module, "build_openai_system_prompt", _fake_prompt_builder)

    builder = StreamAttemptBuilder()
    result = builder.build_system_prompt(
        user_name="User",
        current_date="2026-03-03",
        current_time="10:00",
        user_timezone="UTC",
        project_name=None,
        project_description=None,
        project_custom_instructions=None,
        project_files_summary=None,
        user_custom_instructions=None,
        skills_prompt_section="<skills>DB section</skills>",
    )

    assert result == "BASE"
    assert captured["skills_prompt_section"] == "<skills>DB section</skills>"
