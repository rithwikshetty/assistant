import asyncio
from typing import Any, Dict, List

from app.chat.openai_model import openai_model


class _FakeSession:
    async def close(self) -> None:
        return


class _FakeWebSocket:
    async def close(self) -> None:
        return


def test_reasoning_summary_part_events_emit_thinking_updates(monkeypatch) -> None:
    async def _run() -> None:
        async def _fake_open_ws():
            return _FakeSession(), _FakeWebSocket()

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            assert isinstance(payload.get("input"), list)
            yield {
                "type": "response.reasoning_summary_part.added",
                "item_id": "rs_1",
                "summary_index": 0,
                "part": {"type": "summary_text", "text": ""},
            }
            yield {
                "type": "response.reasoning_summary_part.done",
                "item_id": "rs_1",
                "summary_index": 0,
                "part": {"type": "summary_text", "text": "**Plan**\n\nCheck inputs before tool call."},
            }
            yield {"type": "response.output_text.delta", "delta": "Hello"}
            yield {"type": "response.completed", "response": {"id": "resp_1", "output": []}}

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

        types = [update.get("type") for update in outputs]
        assert "thinking_start" in types
        assert "thinking_delta" in types
        assert "thinking_end" in types
        assert types.count("thinking_end") == 1

        thinking_start = next(update for update in outputs if update.get("type") == "thinking_start")
        thinking_delta = next(update for update in outputs if update.get("type") == "thinking_delta")
        assert thinking_start.get("content", {}).get("title") == "Plan"
        assert "Check inputs before tool call." in str(thinking_delta.get("content", {}).get("text"))

        assert types[-1] == "final"

    asyncio.run(_run())


def test_reasoning_summary_done_events_do_not_duplicate_thinking_end(monkeypatch) -> None:
    async def _run() -> None:
        async def _fake_open_ws():
            return _FakeSession(), _FakeWebSocket()

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            assert isinstance(payload.get("input"), list)
            yield {
                "type": "response.reasoning_summary_part.done",
                "item_id": "rs_2",
                "summary_index": 0,
                "part": {"type": "summary_text", "text": "**Thinking**\n\nOne."},
            }
            yield {
                "type": "response.reasoning_summary_text.done",
                "item_id": "rs_2",
                "summary_index": 0,
            }
            yield {"type": "response.completed", "response": {"id": "resp_2", "output": []}}

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

        types = [update.get("type") for update in outputs]
        assert types.count("thinking_end") == 1

    asyncio.run(_run())
