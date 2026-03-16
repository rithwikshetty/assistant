from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.chat.services.stream_finalizer import StreamFinalizer
from app.chat.streaming_support import FinalizationOptions, StreamState
from app.chat.usage_calculator import RawUsageSummary


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):  # type: ignore[no-untyped-def]
        return self._result

    def all(self):  # type: ignore[no-untyped-def]
        if isinstance(self._result, list):
            return self._result
        return []

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return 0

    def update(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return 0


class _FakeSession:
    def __init__(self, *, conversation, run):
        self._conversation = conversation
        self._run = run
        self.added = []

    def query(self, model):  # type: ignore[no-untyped-def]
        model_name = getattr(model, "__name__", "")
        if model_name == "Conversation":
            return _FakeQuery(self._conversation)
        if model_name == "ChatRun":
            return _FakeQuery(self._run)
        if model_name in {
            "Message",
            "MessagePart",
            "ToolCall",
            "PendingUserInput",
            "ConversationState",
            "ChatRunSnapshot",
            "AnalyticsOutbox",
        }:
            return _FakeQuery(None)
        if model_name == "ChatRunActivity":
            return _FakeQuery([])
        raise AssertionError(f"Unexpected query model: {model_name}")

    def add(self, _obj):  # type: ignore[no-untyped-def]
        self.added.append(_obj)
        return None

    def flush(self):  # type: ignore[no-untyped-def]
        return None

    def commit(self):  # type: ignore[no-untyped-def]
        return None


class _NoUsageCalculator:
    def summarize(self, raw_responses, provider):  # type: ignore[no-untyped-def]
        del raw_responses, provider
        return RawUsageSummary(
            total_input=0,
            total_output=0,
            context_input=None,
            context_output=None,
            context_total=None,
            base_input=None,
            cache_creation_input=None,
            cache_read_input=None,
            reasoning_output=None,
            saw_usage=False,
        )

    def build_usage_payload(self, summary, context_window):  # type: ignore[no-untyped-def]
        del summary, context_window
        return {}

    def create_conversation_usage(self, conversation_metadata, usage_payload, context_window):  # type: ignore[no-untyped-def]
        del usage_payload, context_window
        return {}, conversation_metadata

    def resolve_context_window(self, model_name):  # type: ignore[no-untyped-def]
        del model_name
        return None


class _CheckpointGuardUsageCalculator:
    def summarize(self, raw_responses, provider):  # type: ignore[no-untyped-def]
        del raw_responses, provider
        raise AssertionError("checkpoint finalization should skip usage summarization")

    def build_usage_payload(self, summary, context_window):  # type: ignore[no-untyped-def]
        del summary, context_window
        raise AssertionError("checkpoint finalization should skip usage payload building")

    def create_conversation_usage(self, conversation_metadata, usage_payload, context_window):  # type: ignore[no-untyped-def]
        del conversation_metadata, usage_payload, context_window
        raise AssertionError("checkpoint finalization should skip conversation usage aggregation")

    def resolve_context_window(self, model_name):  # type: ignore[no-untyped-def]
        del model_name
        return 200_000


def test_finalize_response_maps_awaiting_input_to_paused_run_status() -> None:
    now = datetime.now(timezone.utc)
    finalizer = StreamFinalizer()

    conversation = SimpleNamespace(
        id="conv_awaiting",
        user_id="user_awaiting",
        conversation_metadata={},
        updated_at=now,
    )
    run = SimpleNamespace(
        id="run_awaiting",
        status="running",
        finished_at=None,
        started_at=now - timedelta(seconds=2),
    )
    db = _FakeSession(conversation=conversation, run=run)

    _, done_events = finalizer.finalize_response(
        db=db,  # type: ignore[arg-type]
        conversation_id="conv_awaiting",
        user_message_id="user_evt_awaiting",
        state=StreamState(full_response="Need your input"),
        usage_calculator=_NoUsageCalculator(),  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=now - timedelta(seconds=1),
        cancelled=False,
        opts=FinalizationOptions(message_status="awaiting_input", include_done_chunk=True),
    )

    assert run.status == "paused"
    assert run.finished_at is None

    assistant_messages = [item for item in db.added if getattr(item, "role", None) == "assistant"]
    assert assistant_messages
    assert assistant_messages[-1].status == "awaiting_input"

    assert done_events and done_events[0]["type"] == "done"
    done_data = done_events[0].get("data", {})
    assert done_data.get("status") == "paused"
    assert done_data.get("conversationId") == "conv_awaiting"
    assert done_data.get("runId") == "run_awaiting"
    assert done_data.get("runMessageId") == "user_evt_awaiting"
    assert done_data.get("assistantMessageId") is not None
    assert "messageId" not in done_data
    assert done_data.get("pendingRequests") == []


def test_finalize_response_done_payload_normalizes_pending_requests() -> None:
    now = datetime.now(timezone.utc)
    finalizer = StreamFinalizer()

    conversation = SimpleNamespace(
        id="conv_pending",
        user_id="user_pending",
        conversation_metadata={},
        updated_at=now,
    )
    run = SimpleNamespace(
        id="run_pending",
        status="running",
        finished_at=None,
        started_at=now - timedelta(seconds=2),
    )
    db = _FakeSession(conversation=conversation, run=run)

    _, done_events = finalizer.finalize_response(
        db=db,  # type: ignore[arg-type]
        conversation_id="conv_pending",
        user_message_id="user_evt_pending",
        state=StreamState(full_response="Need your input"),
        usage_calculator=_NoUsageCalculator(),  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=now - timedelta(seconds=1),
        cancelled=False,
        opts=FinalizationOptions(
            message_status="awaiting_input",
            include_done_chunk=True,
                done_pending_requests=[
                    {
                        "callId": "call_1",
                        "toolName": "request_user_input",
                        "request": {
                            "tool": "request_user_input",
                            "title": "Approve scope",
                            "prompt": "Choose one option.",
                            "questions": [
                                {
                                    "id": "scope",
                                    "question": "Approve?",
                                    "options": [
                                        {"label": "Yes", "description": "Proceed now."},
                                        {"label": "No", "description": "Stop and revise."},
                                    ],
                                }
                            ],
                        },
                        "result": {
                            "status": "pending",
                            "interaction_type": "user_input",
                            "request": {
                                "tool": "request_user_input",
                                "title": "Approve scope",
                                "prompt": "Choose one option.",
                                "questions": [
                                    {
                                        "id": "scope",
                                        "question": "Approve?",
                                        "options": [
                                            {"label": "Yes", "description": "Proceed now."},
                                            {"label": "No", "description": "Stop and revise."},
                                        ],
                                    }
                                ],
                            },
                        },
                    }
                ],
            ),
    )

    assert done_events and done_events[0]["type"] == "done"
    done_data = done_events[0].get("data", {})
    assert done_data.get("status") == "paused"
    assert done_data.get("pendingRequests") == [
        {
            "callId": "call_1",
            "toolName": "request_user_input",
            "request": {
                "tool": "request_user_input",
                "title": "Approve scope",
                "prompt": "Choose one option.",
                "questions": [
                    {
                        "id": "scope",
                        "question": "Approve?",
                        "options": [
                            {"label": "Yes", "description": "Proceed now."},
                            {"label": "No", "description": "Stop and revise."},
                        ],
                    }
                ],
            },
            "result": {
                "status": "pending",
                "interaction_type": "user_input",
                "request": {
                    "tool": "request_user_input",
                    "title": "Approve scope",
                    "prompt": "Choose one option.",
                    "questions": [
                        {
                            "id": "scope",
                            "question": "Approve?",
                            "options": [
                                {"label": "Yes", "description": "Proceed now."},
                                {"label": "No", "description": "Stop and revise."},
                            ],
                        }
                    ],
                },
            },
        }
    ]


def test_finalize_response_checkpoint_mode_skips_outbox_dispatch_and_cost(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    finalizer = StreamFinalizer()
    del monkeypatch

    conversation = SimpleNamespace(
        id="conv_checkpoint",
        user_id="user_checkpoint",
        conversation_metadata={},
        updated_at=now,
    )
    run = SimpleNamespace(
        id="run_checkpoint",
        status="running",
        finished_at=None,
        started_at=now - timedelta(seconds=2),
    )
    db = _FakeSession(conversation=conversation, run=run)

    _, done_events = finalizer.finalize_response(
        db=db,  # type: ignore[arg-type]
        conversation_id="conv_checkpoint",
        user_message_id="user_evt_checkpoint",
        state=StreamState(full_response="Checkpoint message"),
        usage_calculator=_CheckpointGuardUsageCalculator(),  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=now - timedelta(seconds=1),
        cancelled=False,
        opts=FinalizationOptions(
            message_status="completed",
            include_done_chunk=True,
            checkpoint_mode=True,
            checkpoint_stream_event_id=11,
        ),
    )

    outbox_rows = [row for row in db.added if getattr(row, "event_type", None) == "assistant.turn.finalized"]
    assert outbox_rows == []
    assert run.finished_at is None

    done_data = done_events[0].get("data", {}) if done_events else {}
    assert done_data.get("status") == "completed"
    assert "costUsd" not in done_data


def test_finalize_response_checkpoint_mode_skips_assistant_turn_writes(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    finalizer = StreamFinalizer()
    write_counts = {
        "tool_calls": 0,
        "pending": 0,
    }

    monkeypatch.setattr(
        finalizer,
        "_persist_tool_calls",
        lambda **_kwargs: write_counts.__setitem__("tool_calls", write_counts["tool_calls"] + 1),
    )
    monkeypatch.setattr(
        finalizer,
        "_persist_pending_user_inputs",
        lambda **_kwargs: write_counts.__setitem__("pending", write_counts["pending"] + 1),
    )
    assistant_upserts = {"count": 0}
    monkeypatch.setattr(
        finalizer,
        "_upsert_assistant_message",
        lambda **_kwargs: assistant_upserts.__setitem__("count", assistant_upserts["count"] + 1),
    )

    conversation = SimpleNamespace(
        id="conv_checkpoint_writes",
        user_id="user_checkpoint_writes",
        conversation_metadata={},
        updated_at=now,
    )
    run = SimpleNamespace(
        id="run_checkpoint_writes",
        status="running",
        finished_at=None,
        started_at=now - timedelta(seconds=2),
    )
    db = _FakeSession(conversation=conversation, run=run)

    finalizer.finalize_response(
        db=db,  # type: ignore[arg-type]
        conversation_id="conv_checkpoint_writes",
        user_message_id="user_evt_checkpoint_writes",
        state=StreamState(
            full_response="Checkpoint",
            tool_markers=[
                {
                    "name": "web_search",
                    "call_id": "call_1",
                    "pos": 0,
                    "seq": 1,
                    "result": {"status": "ok", "result": {"items": []}},
                }
            ],
        ),
        usage_calculator=_CheckpointGuardUsageCalculator(),  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=now - timedelta(seconds=1),
        cancelled=False,
        opts=FinalizationOptions(
            message_status="completed",
            include_done_chunk=False,
            checkpoint_mode=True,
        ),
    )

    assert write_counts["tool_calls"] == 0
    assert write_counts["pending"] == 0
    assert assistant_upserts["count"] == 0
    assert [row for row in db.added if getattr(row, "role", None) == "assistant"] == []


def test_finalize_response_checkpoint_mode_text_only_skips_structured_projection_writes(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    finalizer = StreamFinalizer()
    write_counts = {
        "tool_calls": 0,
        "pending": 0,
    }

    monkeypatch.setattr(
        finalizer,
        "_persist_tool_calls",
        lambda **_kwargs: write_counts.__setitem__("tool_calls", write_counts["tool_calls"] + 1),
    )
    monkeypatch.setattr(
        finalizer,
        "_persist_pending_user_inputs",
        lambda **_kwargs: write_counts.__setitem__("pending", write_counts["pending"] + 1),
    )
    assistant_upserts = {"count": 0}
    monkeypatch.setattr(
        finalizer,
        "_upsert_assistant_message",
        lambda **_kwargs: assistant_upserts.__setitem__("count", assistant_upserts["count"] + 1),
    )

    conversation = SimpleNamespace(
        id="conv_checkpoint_text_only",
        user_id="user_checkpoint_text_only",
        conversation_metadata={},
        updated_at=now,
    )
    run = SimpleNamespace(
        id="run_checkpoint_text_only",
        status="running",
        finished_at=None,
        started_at=now - timedelta(seconds=2),
    )
    db = _FakeSession(conversation=conversation, run=run)

    finalizer.finalize_response(
        db=db,  # type: ignore[arg-type]
        conversation_id="conv_checkpoint_text_only",
        user_message_id="user_evt_checkpoint_text_only",
        state=StreamState(full_response="Checkpoint"),
        usage_calculator=_CheckpointGuardUsageCalculator(),  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=now - timedelta(seconds=1),
        cancelled=False,
        opts=FinalizationOptions(
            message_status="completed",
            include_done_chunk=False,
            checkpoint_mode=True,
        ),
    )

    assert write_counts["tool_calls"] == 0
    assert write_counts["pending"] == 0
    assert assistant_upserts["count"] == 0
