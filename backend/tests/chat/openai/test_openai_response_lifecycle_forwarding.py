import asyncio
from typing import Any, Dict, List

from app.chat.openai_model import openai_model


class _FakeSession:
    async def close(self) -> None:
        return


class _FakeWebSocket:
    async def close(self) -> None:
        return


def test_unknown_response_events_are_forwarded_as_lifecycle_updates(monkeypatch) -> None:
    async def _run() -> None:
        async def _fake_open_ws():
            return _FakeSession(), _FakeWebSocket()

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            assert isinstance(payload.get("input"), list)
            yield {
                "type": "response.output_audio.transcript.done",
                "item_id": "audio_1",
                "transcript": "hello",
            }
            yield {"type": "response.completed", "response": {"id": "resp_capture_1", "output": []}}

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

        lifecycle_update = next(
            update
            for update in outputs
            if update.get("type") == "response.output_audio.transcript.done"
        )
        lifecycle_payload = lifecycle_update.get("data")
        assert isinstance(lifecycle_payload, dict)
        assert lifecycle_payload.get("item_id") == "audio_1"

        # Keep existing completion behavior: lifecycle completion event, raw
        # response snapshot for usage, then final.
        assert any(update.get("type") == "response.completed" for update in outputs)
        assert any(update.get("type") == "raw_response" for update in outputs)
        assert outputs[-1].get("type") == "final"

    asyncio.run(_run())
