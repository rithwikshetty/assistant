import asyncio
from types import SimpleNamespace

from app.chat.tools import code_execution


def test_fix_code_with_llm_uses_openai_and_strips_markdown_fences(monkeypatch) -> None:
    async def _run() -> None:
        captured = {}

        class _FakeResponses:
            async def create(self, **kwargs):
                captured["kwargs"] = kwargs
                return SimpleNamespace(output_text="```python\nprint('fixed')\n```")

        class _FakeAsyncOpenAI:
            def __init__(self, *, api_key):
                captured["api_key"] = api_key
                self.responses = _FakeResponses()

        monkeypatch.setattr(code_execution.settings, "openai_api_key", "test-openai-key", raising=False)
        monkeypatch.setattr(code_execution, "AsyncOpenAI", _FakeAsyncOpenAI)

        fixed = await code_execution._fix_code_with_llm(
            "print('broken')",
            "Traceback: name 'x' is not defined",
            1,
        )

        assert fixed == "print('fixed')"
        assert captured["api_key"] == "test-openai-key"
        assert captured["kwargs"]["model"] == code_execution.FIX_MODEL
        assert captured["kwargs"]["store"] is False
        assert "## Code" in captured["kwargs"]["input"]
        assert "## Error (attempt 1)" in captured["kwargs"]["input"]

    asyncio.run(_run())


def test_fix_code_with_llm_returns_none_when_openai_key_missing(monkeypatch) -> None:
    async def _run() -> None:
        client_called = False

        class _FakeAsyncOpenAI:
            def __init__(self, *, api_key):
                nonlocal client_called
                client_called = True
                self.responses = object()

        monkeypatch.setattr(code_execution.settings, "openai_api_key", "", raising=False)
        monkeypatch.setattr(code_execution, "AsyncOpenAI", _FakeAsyncOpenAI)

        fixed = await code_execution._fix_code_with_llm(
            "print('broken')",
            "Traceback: failure",
            1,
        )

        assert fixed is None
        assert client_called is False

    asyncio.run(_run())
