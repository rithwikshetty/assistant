import asyncio
from typing import Any, Dict, List

from app.chat.openai_model import openai_model


class _FakeSession:
    async def close(self) -> None:
        return


class _FakeWebSocket:
    async def close(self) -> None:
        return


def test_openai_websocket_partial_output_does_not_retry_full_context(monkeypatch) -> None:
    async def _run() -> None:
        open_calls: List[int] = []

        async def _fake_open_ws():
            open_calls.append(1)
            return _FakeSession(), _FakeWebSocket()

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            assert isinstance(payload.get("input"), list)
            yield {"type": "response.output_text.delta", "delta": "Hello"}
            raise RuntimeError("socket dropped")

        monkeypatch.setattr(openai_model, "_open_openai_responses_websocket", _fake_open_ws)
        monkeypatch.setattr(openai_model, "_stream_openai_ws_turn", _fake_stream_ws_turn)

        outputs: List[Dict[str, Any]] = []
        stream = openai_model.chat_stream(
            query="hi",
            conversation_history=[],
            tools=[],
            tool_context={"provider": "openai"},
        )
        async for update in stream:
            outputs.append(update)

        assert [update.get("type") for update in outputs] == ["response", "error", "final"]
        assert outputs[1].get("content", {}).get("code") == "OPENAI_STREAM_EXCEPTION"
        assert open_calls == [1]

    asyncio.run(_run())
