from app.config.settings import Settings


def test_chat_reasoning_effort_defaults_to_medium() -> None:
    settings = Settings()
    assert settings.chat_reasoning_effort == "medium"


def test_chat_reasoning_effort_rejects_invalid_values() -> None:
    settings = Settings(chat_reasoning_effort="unsupported")
    assert settings.chat_reasoning_effort == "medium"
