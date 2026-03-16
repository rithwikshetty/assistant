import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List
from types import SimpleNamespace

from app.chat.openai_model import openai_model


class _FakeSession:
    async def close(self) -> None:
        return


class _FakeWebSocket:
    async def close(self) -> None:
        return


class _FakeAsyncSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


def test_extract_reasoning_replay_items_adds_empty_summary_when_missing() -> None:
    replay_items = openai_model._extract_reasoning_replay_items(  # type: ignore[attr-defined]
        {
            "output": [
                {
                    "type": "reasoning",
                    "encrypted_content": "enc_missing_summary",
                }
            ]
        }
    )

    assert replay_items == [
        {
            "type": "reasoning",
            "encrypted_content": "enc_missing_summary",
            "summary": [],
        }
    ]


def test_stateless_tool_loop_appends_cleaned_output_and_tool_results(monkeypatch) -> None:
    """In stateless mode, each turn should send full input_items with
    cleaned response output appended, not use previous_response_id."""

    async def _run() -> None:
        payloads: List[Dict[str, Any]] = []

        async def _fake_open_ws():
            return _FakeSession(), _FakeWebSocket()

        async def _fake_execute_tool(*, name: str, arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            assert name == "mock_tool"
            return {"ok": True}

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            payloads.append(payload)
            call_number = len(payloads)

            if call_number == 1:
                yield {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_1",
                        "name": "mock_tool",
                        "arguments": "{}",
                    },
                }
                yield {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_1",
                        "output": [
                            {
                                "type": "function_call",
                                "id": "item_1",
                                "call_id": "call_1",
                                "name": "mock_tool",
                                "arguments": "{}",
                                "status": "completed",
                            },
                            {
                                "type": "reasoning",
                                "encrypted_content": "enc_123",
                                "summary": [{"type": "summary_text", "text": "Used mock_tool"}],
                            },
                        ],
                    },
                }
                return

            if call_number == 2:
                yield {"type": "response.output_text.delta", "delta": "Done"}
                yield {"type": "response.completed", "response": {"id": "resp_2", "output": []}}
                return

            raise AssertionError(f"Unexpected websocket call: {call_number}")

        # Stub out token counting (no compaction needed for this test)
        async def _fake_count_tokens(*args, **kwargs):
            return 100

        monkeypatch.setattr(openai_model, "_open_openai_responses_websocket", _fake_open_ws)
        monkeypatch.setattr(openai_model, "_stream_openai_ws_turn", _fake_stream_ws_turn)
        monkeypatch.setattr(openai_model, "execute_tool", _fake_execute_tool)
        monkeypatch.setattr(openai_model, "_count_openai_input_tokens", _fake_count_tokens)

        tool_spec = {
            "type": "function",
            "name": "mock_tool",
            "description": "Mock tool for stateless tests",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        }

        updates: List[Dict[str, Any]] = []
        stream = openai_model.chat_stream(
            query="hi",
            conversation_history=[],
            tools=[tool_spec],
            tool_context={"provider": "openai", "openai_compact_trigger_tokens": 200_000},
        )
        async for update in stream:
            updates.append(update)

        assert len(payloads) == 2

        # No previous_response_id should be sent in stateless mode
        assert "previous_response_id" not in payloads[0]
        assert "previous_response_id" not in payloads[1]

        # No context_management should be sent
        assert "context_management" not in payloads[0]
        assert "context_management" not in payloads[1]

        # Second turn should contain the cleaned output + tool results
        turn2_input = payloads[1].get("input", [])
        # Should have: original user message + cleaned function_call + cleaned reasoning + function_call_output
        item_types = [item.get("type") for item in turn2_input if isinstance(item, dict)]
        assert "function_call" in item_types
        assert "function_call_output" in item_types

        # Cleaned function_call should NOT have 'status' or 'id' fields
        function_calls = [i for i in turn2_input if isinstance(i, dict) and i.get("type") == "function_call"]
        for fc in function_calls:
            assert "status" not in fc
            assert "id" not in fc

        assert updates[-1].get("type") == "final"

    asyncio.run(_run())


def test_openai_websocket_dedupes_duplicate_tool_call_added_events(monkeypatch) -> None:
    async def _run() -> None:
        execute_calls = 0

        async def _fake_open_ws():
            return _FakeSession(), _FakeWebSocket()

        async def _fake_execute_tool(*, name: str, arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal execute_calls
            execute_calls += 1
            assert name == "mock_tool"
            assert isinstance(arguments, dict)
            assert isinstance(context, dict)
            return {"ok": True}

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            _ = payload

            call_number = getattr(_fake_stream_ws_turn, "_call_number", 0) + 1
            setattr(_fake_stream_ws_turn, "_call_number", call_number)

            if call_number == 1:
                event = {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_1",
                        "name": "mock_tool",
                        "arguments": "{}",
                    },
                }
                yield event
                yield event
                yield {"type": "response.completed", "response": {"id": "resp_dup_1", "output": []}}
                return

            if call_number == 2:
                yield {"type": "response.output_text.delta", "delta": "Done"}
                yield {"type": "response.completed", "response": {"id": "resp_dup_2", "output": []}}
                return

            raise AssertionError(f"Unexpected websocket call: {call_number}")

        async def _fake_count_tokens(*args, **kwargs):
            return 100

        monkeypatch.setattr(openai_model, "_open_openai_responses_websocket", _fake_open_ws)
        monkeypatch.setattr(openai_model, "_stream_openai_ws_turn", _fake_stream_ws_turn)
        monkeypatch.setattr(openai_model, "execute_tool", _fake_execute_tool)
        monkeypatch.setattr(openai_model, "_count_openai_input_tokens", _fake_count_tokens)

        tool_spec = {
            "type": "function",
            "name": "mock_tool",
            "description": "Mock tool for dedupe tests",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        }

        updates: List[Dict[str, Any]] = []
        stream = openai_model.chat_stream(
            query="hi",
            conversation_history=[],
            tools=[tool_spec],
            tool_context={"provider": "openai", "openai_compact_trigger_tokens": 200_000},
        )
        async for update in stream:
            updates.append(update)

        tool_call_updates = [u for u in updates if u.get("type") == "tool_call"]
        assert len(tool_call_updates) == 1
        assert execute_calls == 1
        assert updates[-1].get("type") == "final"

    asyncio.run(_run())


def test_tool_loop_hands_off_to_queued_turn_after_tool_result(monkeypatch) -> None:
    async def _run() -> None:
        payloads: List[Dict[str, Any]] = []

        async def _fake_open_ws():
            return _FakeSession(), _FakeWebSocket()

        async def _fake_execute_tool(*, name: str, arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
            assert name == "mock_tool"
            return {"ok": True}

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            payloads.append(payload)
            yield {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": "item_1",
                    "call_id": "call_1",
                    "name": "mock_tool",
                    "arguments": "{}",
                },
            }
            yield {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "output": [
                        {
                            "type": "function_call",
                            "id": "item_1",
                            "call_id": "call_1",
                            "name": "mock_tool",
                            "arguments": "{}",
                            "status": "completed",
                        }
                    ],
                },
            }

        async def _fake_count_tokens(*args, **kwargs):
            return 100

        async def _fake_peek_handoff(*, db, conversation_id: str, blocked_by_run_id: str):  # noqa: ANN001
            assert db is not None
            assert conversation_id == "conv_1"
            assert blocked_by_run_id == "run_active"
            return SimpleNamespace(
                run_id="run_next",
                user_message_id="msg_next",
                created_at=datetime(2026, 3, 13, 0, 0, 5, tzinfo=timezone.utc),
            )

        monkeypatch.setattr(openai_model, "_open_openai_responses_websocket", _fake_open_ws)
        monkeypatch.setattr(openai_model, "_stream_openai_ws_turn", _fake_stream_ws_turn)
        monkeypatch.setattr(openai_model, "execute_tool", _fake_execute_tool)
        monkeypatch.setattr(openai_model, "_count_openai_input_tokens", _fake_count_tokens)
        monkeypatch.setattr(openai_model, "peek_queued_turn_handoff", _fake_peek_handoff)
        monkeypatch.setattr(openai_model, "AsyncSessionLocal", lambda: _FakeAsyncSession())

        tool_spec = {
            "type": "function",
            "name": "mock_tool",
            "description": "Mock tool for queue handoff tests",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        }

        updates: List[Dict[str, Any]] = []
        stream = openai_model.chat_stream(
            query="hi",
            conversation_history=[],
            tools=[tool_spec],
            tool_context={
                "provider": "openai",
                "conversation_id": "conv_1",
                "active_run_id": "run_active",
                "openai_compact_trigger_tokens": 200_000,
            },
        )
        async for update in stream:
            updates.append(update)

        assert len(payloads) == 1
        assert any(update.get("type") == "tool_result" for update in updates)
        assert updates[-1] == {
            "type": "queued_turn_handoff",
            "data": {
                "run_id": "run_next",
                "user_message_id": "msg_next",
                "created_at": "2026-03-13T00:00:05+00:00",
            },
        }

    asyncio.run(_run())


def test_resume_continuation_uses_latest_history_not_stale_compacted_items(monkeypatch) -> None:
    async def _run() -> None:
        payloads: List[Dict[str, Any]] = []

        async def _fake_open_ws():
            return _FakeSession(), _FakeWebSocket()

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            payloads.append(payload)
            yield {"type": "response.output_text.delta", "delta": "Resumed"}
            yield {"type": "response.completed", "response": {"id": "resp_resume", "output": []}}

        async def _fake_count_tokens(*args, **kwargs):
            return 100

        monkeypatch.setattr(openai_model, "_open_openai_responses_websocket", _fake_open_ws)
        monkeypatch.setattr(openai_model, "_stream_openai_ws_turn", _fake_stream_ws_turn)
        monkeypatch.setattr(openai_model, "_count_openai_input_tokens", _fake_count_tokens)

        stale_snapshot_items = [
            {
                "type": "message",
                "role": "user",
                "content": "stale compacted snapshot should not be used",
            }
        ]
        resume_continuation = [
            {
                "type": "function_call",
                "name": "mock_tool",
                "call_id": "resume_call_1",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "resume_call_1",
                "output": "{\"ok\": true}",
            },
        ]

        updates: List[Dict[str, Any]] = []
        stream = openai_model.chat_stream(
            query="",
            conversation_history=[{"role": "user", "content": "fresh follow-up prompt for resume"}],
            tools=[],
            tool_context={
                "provider": "openai",
                "openai_compact_trigger_tokens": 200_000,
                "stored_input_items": stale_snapshot_items,
            },
            resume_continuation=resume_continuation,
        )
        async for update in stream:
            updates.append(update)

        assert len(payloads) == 1
        sent_input = payloads[0].get("input", [])
        assert any(
            isinstance(item, dict)
            and item.get("role") == "user"
            and item.get("content") == "fresh follow-up prompt for resume"
            for item in sent_input
        )
        assert not any(
            isinstance(item, dict)
            and "stale compacted snapshot should not be used" in str(item.get("content"))
            for item in sent_input
        )
        assert any(
            isinstance(item, dict)
            and item.get("type") == "function_call"
            and item.get("call_id") == "resume_call_1"
            for item in sent_input
        )
        assert updates[-1].get("type") == "final"

    asyncio.run(_run())


def test_no_tool_turn_emits_post_response_live_context_usage(monkeypatch) -> None:
    async def _run() -> None:
        payloads: List[Dict[str, Any]] = []
        token_counts = [6000, 6420]

        async def _fake_open_ws():
            return _FakeSession(), _FakeWebSocket()

        async def _fake_stream_ws_turn(*, ws, payload: Dict[str, Any]):  # noqa: ANN001
            assert ws is not None
            payloads.append(payload)
            yield {"type": "response.output_text.delta", "delta": "Done"}
            yield {
                "type": "response.completed",
                "response": {
                    "id": "resp_final_usage",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Done"}],
                        }
                    ],
                },
            }

        async def _fake_count_tokens(*args, **kwargs):  # noqa: ANN001
            del args, kwargs
            assert token_counts, "unexpected extra token count call"
            return token_counts.pop(0)

        monkeypatch.setattr(openai_model, "_open_openai_responses_websocket", _fake_open_ws)
        monkeypatch.setattr(openai_model, "_stream_openai_ws_turn", _fake_stream_ws_turn)
        monkeypatch.setattr(openai_model, "_count_openai_input_tokens", _fake_count_tokens)

        updates: List[Dict[str, Any]] = []
        stream = openai_model.chat_stream(
            query="hi",
            conversation_history=[],
            tools=[],
            tool_context={"provider": "openai", "openai_compact_trigger_tokens": 200_000},
        )
        async for update in stream:
            updates.append(update)

        live_usage = [u for u in updates if u.get("type") == "live_context_usage"]
        assert [u.get("data", {}).get("input_tokens") for u in live_usage] == [6000, 6420]
        snapshots = [u for u in updates if u.get("type") == "input_items_snapshot"]
        assert len(snapshots) == 1
        snapshot_items = snapshots[0].get("content")
        assert isinstance(snapshot_items, list)
        assert any(
            isinstance(item, dict)
            and item.get("role") == "assistant"
            for item in snapshot_items
        )
        assert updates[-1].get("type") == "final"
        assert len(payloads) == 1
        assert token_counts == []

    asyncio.run(_run())
