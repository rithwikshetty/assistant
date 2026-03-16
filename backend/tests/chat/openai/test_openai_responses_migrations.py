import asyncio
from typing import Any, Dict

from app.chat import title_generator
from app.chat.services import suggestion_service
from app.services.admin import sector_classification_service


class _FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text

    def model_dump(self) -> Dict[str, Any]:
        return {"output_text": self.output_text}


def test_generate_title_uses_responses_api(monkeypatch) -> None:
    async def _run() -> None:
        captured: Dict[str, Any] = {}

        class _FakeResponses:
            async def create(self, **kwargs: Any) -> _FakeResponse:
                captured.update(kwargs)
                return _FakeResponse('{"title":"analyse cost breakdown"}')

        class _FakeClient:
            def __init__(self, **_: Any) -> None:
                self.responses = _FakeResponses()

        monkeypatch.setattr(title_generator, "AsyncOpenAI", _FakeClient)
        monkeypatch.setattr(title_generator, "_openai_async_client", None)
        monkeypatch.setattr(title_generator, "_openai_async_client_api_key", None)
        monkeypatch.setattr(title_generator.settings, "openai_api_key", "test-key")
        monkeypatch.setattr(title_generator.settings, "title_generation_model", "gpt-4.1-nano")
        monkeypatch.setattr(title_generator.settings, "title_generation_max_tokens", 48)

        result = await title_generator.generate_title("please analyse this estimate")
        assert result == "Analyse cost breakdown"
        assert captured["store"] is False
        assert captured["max_output_tokens"] == 48
        assert captured["text"]["format"]["type"] == "json_schema"
        assert "response_format" not in captured
        assert "max_tokens" not in captured

    asyncio.run(_run())


def test_generate_suggestions_uses_responses_api(monkeypatch) -> None:
    async def _run() -> None:
        captured: Dict[str, Any] = {}

        class _FakeResponses:
            async def create(self, **kwargs: Any) -> _FakeResponse:
                captured.update(kwargs)
                return _FakeResponse(
                    '{"suggestions":["Use Option A","Can we compare alternatives?","What are the risks?"]}'
                )

        class _FakeClient:
            def __init__(self, **_: Any) -> None:
                self.responses = _FakeResponses()

        monkeypatch.setattr(suggestion_service, "AsyncOpenAI", _FakeClient)
        monkeypatch.setattr(suggestion_service.settings, "openai_api_key", "test-key")

        history = [
            {"role": "assistant", "content": "Choose one of 1A, 1B, or 1C."},
            {"role": "user", "content": [{"type": "text", "text": "1A"}]},
        ]

        result = await suggestion_service.generate_suggestions(
            conversation_history=history,
            project_context="Station Upgrade",
        )

        assert result == ["Use Option A", "Can we compare alternatives?", "What are the risks?"]
        assert captured["store"] is False
        assert captured["max_output_tokens"] == 300
        assert captured["text"]["format"]["type"] == "json_schema"
        assert "Project: Station Upgrade" in captured["instructions"]
        assert captured["input"] == [
            {"role": "assistant", "content": "Choose one of 1A, 1B, or 1C."},
            {"role": "user", "content": "1A"},
        ]
        assert "response_format" not in captured
        assert "max_tokens" not in captured

    asyncio.run(_run())


def test_sector_classification_uses_responses_api(monkeypatch) -> None:
    captured: Dict[str, Any] = {}
    analytics_captured: Dict[str, Any] = {}

    class _FakeResponses:
        def create(self, **kwargs: Any) -> _FakeResponse:
            captured.update(kwargs)
            return _FakeResponse('{"sector":"Education","confidence":0.92}')

    class _FakeClient:
        def __init__(self, **_: Any) -> None:
            self.responses = _FakeResponses()

    monkeypatch.setattr(sector_classification_service, "OpenAI", _FakeClient)
    monkeypatch.setattr(sector_classification_service.settings, "openai_api_key", "test-key")

    def _capture_usage(**kwargs: Any) -> None:
        analytics_captured.update(kwargs)

    monkeypatch.setattr(sector_classification_service, "record_estimated_model_usage", _capture_usage)

    context = sector_classification_service.ConversationSectorContext(
        conversation_id="conv_1",
        user_id="user_1",
        project_id="project_1",
        title="School expansion estimate",
        project_name="North Campus",
        project_category="Education",
        first_user_message="Need a budget estimate for classrooms.",
        recent_user_messages=["Need a budget estimate for classrooms."],
        user_message_count=1,
    )

    sector, confidence = sector_classification_service.classify_sector_with_model(context)
    assert sector == "Education"
    assert confidence == 0.92
    assert captured["store"] is False
    assert captured["max_output_tokens"] == 160
    assert captured["text"]["format"]["type"] == "json_schema"
    assert analytics_captured["operation_type"] == "sector_classification"
    assert analytics_captured["analytics_context"] == {
        "user_id": "user_1",
        "conversation_id": "conv_1",
        "project_id": "project_1",
    }
    assert "response_format" not in captured
    assert "max_tokens" not in captured
