import asyncio
from typing import Any, Dict, List

from app.chat.run_engine.engine import ChatRunEngine
from app.chat.run_engine.runtime_inputs import PreparedRunInputs
from app.chat.run_engine.state_machine import RunState


class _FakeStream:
    def __init__(self) -> None:
        self.status = "running"
        self.context = None
        self.run_id = "run_1"
        self.published: List[Dict[str, Any]] = []
        self.steps: List[str] = []

    async def publish(self, event: Dict[str, Any]) -> None:
        self.published.append(event)

    async def update_step(self, step: str) -> None:
        self.steps.append(step)

    async def check_cancel(self) -> bool:
        return False

    async def set_status(self, status: str) -> None:
        self.status = status

    async def touch(self) -> None:
        return


class _FakeStreamManager:
    def stream_response(self, **_kwargs):  # noqa: ANN003
        async def _gen():
            yield {"type": "error", "data": {"message": "provider failed"}}

        return _gen()


class _HangingStreamManager:
    def stream_response(self, **_kwargs):  # noqa: ANN003
        async def _gen():
            if False:  # pragma: no cover - keeps this as an async generator
                yield {}
            try:
                while True:
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                return

        return _gen()


class _CancelAfterPollsStream(_FakeStream):
    def __init__(self, *, cancel_after_polls: int) -> None:
        super().__init__()
        self._cancel_after_polls = max(1, cancel_after_polls)
        self._poll_count = 0

    async def check_cancel(self) -> bool:
        self._poll_count += 1
        return self._poll_count >= self._cancel_after_polls


def test_error_event_marks_run_failed_and_skips_completed_job(monkeypatch) -> None:
    async def _run() -> None:
        engine = ChatRunEngine(
            conversation_id="conv_1",
            user_id="user_1",
            user_message_id="msg_1",
        )
        fake_stream = _FakeStream()
        engine._stream = fake_stream  # pylint: disable=protected-access

        cleanup_calls: List[str] = []

        monkeypatch.setattr("app.chat.run_engine.engine.ChatStreamingManager", lambda: _FakeStreamManager())

        async def _fake_cleanup(conversation_id: str) -> None:
            cleanup_calls.append(conversation_id)

        monkeypatch.setattr("app.chat.run_engine.engine.schedule_cleanup", _fake_cleanup)

        async def _fake_heartbeat(self) -> None:  # noqa: ANN001
            return

        monkeypatch.setattr(ChatRunEngine, "_stream_heartbeat", _fake_heartbeat)

        prepared_inputs = PreparedRunInputs(
            raw_messages=[],
            user_prompt="hi",
            allowed_file_ids=set(),
            attachments_meta=[],
            is_admin=False,
            seed_response_text=None,
            seed_tool_markers=None,
            seed_reasoning_summaries=None,
        )

        await engine._run_stream_loop(prepared_inputs)  # pylint: disable=protected-access

        assert fake_stream.status == RunState.FAILED.value
        assert cleanup_calls == ["conv_1"]
        assert any(event.get("type") == "error" for event in fake_stream.published)
        assert not any(event.get("type") == "job_complete" for event in fake_stream.published)

    asyncio.run(_run())


def test_cancel_is_honored_while_waiting_for_next_provider_event(monkeypatch) -> None:
    async def _run() -> None:
        engine = ChatRunEngine(
            conversation_id="conv_2",
            user_id="user_2",
            user_message_id="msg_2",
        )
        fake_stream = _CancelAfterPollsStream(cancel_after_polls=2)
        engine._stream = fake_stream  # pylint: disable=protected-access

        cleanup_calls: List[str] = []

        monkeypatch.setattr("app.chat.run_engine.engine.ChatStreamingManager", lambda: _HangingStreamManager())
        monkeypatch.setattr("app.chat.run_engine.engine._STREAM_CANCEL_POLL_SECONDS", 0.01)

        async def _fake_cleanup(conversation_id: str) -> None:
            cleanup_calls.append(conversation_id)

        monkeypatch.setattr("app.chat.run_engine.engine.schedule_cleanup", _fake_cleanup)

        async def _fake_heartbeat(self) -> None:  # noqa: ANN001
            return

        monkeypatch.setattr(ChatRunEngine, "_stream_heartbeat", _fake_heartbeat)

        prepared_inputs = PreparedRunInputs(
            raw_messages=[],
            user_prompt="hi",
            allowed_file_ids=set(),
            attachments_meta=[],
            is_admin=False,
            seed_response_text=None,
            seed_tool_markers=None,
            seed_reasoning_summaries=None,
        )

        await asyncio.wait_for(
            engine._run_stream_loop(prepared_inputs),  # pylint: disable=protected-access
            timeout=1.0,
        )

        assert fake_stream.status == RunState.CANCELLED.value
        assert cleanup_calls == ["conv_2"]
        assert any(
            event.get("type") == "done"
            and isinstance(event.get("data"), dict)
            and event["data"].get("status") == "cancelled"
            for event in fake_stream.published
        )

    asyncio.run(_run())
