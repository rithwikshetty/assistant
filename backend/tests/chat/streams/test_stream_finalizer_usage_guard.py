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
        return [] if self._result is None else [self._result]

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
            "AnalyticsOutbox",
            "ChatRunSnapshot",
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


class _GuardedNoUsageCalculator:
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
        raise AssertionError("build_usage_payload should not be called when saw_usage is False")

    def create_conversation_usage(self, conversation_metadata, usage_payload, context_window):  # type: ignore[no-untyped-def]
        del conversation_metadata, usage_payload, context_window
        raise AssertionError("create_conversation_usage should not be called when saw_usage is False")

    def resolve_context_window(self, model_name):  # type: ignore[no-untyped-def]
        del model_name
        return 1_050_000


class _LiveMergeUsageCalculator:
    def summarize(self, raw_responses, provider):  # type: ignore[no-untyped-def]
        del raw_responses, provider
        return RawUsageSummary(
            total_input=120,
            total_output=12,
            context_input=120,
            context_output=12,
            context_total=132,
            base_input=120,
            cache_creation_input=0,
            cache_read_input=0,
            reasoning_output=0,
            saw_usage=True,
        )

    def build_usage_payload(self, summary, context_window):  # type: ignore[no-untyped-def]
        del summary, context_window
        return {
            "input_tokens": 120,
            "output_tokens": 12,
            "total_tokens": 132,
            "aggregated_input_tokens": 120,
            "aggregated_output_tokens": 12,
            "aggregated_total_tokens": 132,
        }

    def create_conversation_usage(self, conversation_metadata, usage_payload, context_window):  # type: ignore[no-untyped-def]
        del conversation_metadata, usage_payload, context_window
        return {
            "input_tokens": 500,
            "output_tokens": 50,
            "total_tokens": 550,
            "max_context_tokens": 1_050_000,
            "remaining_context_tokens": 1_049_450,
            "cumulative_input_tokens": 3_200,
            "cumulative_output_tokens": 500,
            "cumulative_total_tokens": 3_700,
        }, {"usage": {"input_tokens": 500}}

    def resolve_context_window(self, model_name):  # type: ignore[no-untyped-def]
        del model_name
        return 1_050_000


def test_finalize_response_skips_usage_payload_when_provider_usage_missing() -> None:
    finalizer = StreamFinalizer()
    now = datetime.now(timezone.utc)

    conversation = SimpleNamespace(
        id="conv_guard",
        user_id="user_guard",
        conversation_metadata={},
        updated_at=now,
    )
    run = SimpleNamespace(
        id="run_guard",
        status="running",
        finished_at=None,
        started_at=now - timedelta(seconds=2),
    )
    db = _FakeSession(conversation=conversation, run=run)

    state = StreamState(full_response="Done")
    usage_calculator = _GuardedNoUsageCalculator()
    _, done_events = finalizer.finalize_response(
        db=db,  # type: ignore[arg-type]
        conversation_id="conv_guard",
        user_message_id="user_evt_guard",
        state=state,
        usage_calculator=usage_calculator,  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=now - timedelta(seconds=2),
        cancelled=False,
        opts=FinalizationOptions(
            message_status="completed",
            include_done_chunk=True,
        ),
    )

    assert done_events and done_events[0]["type"] == "done"
    done_data = done_events[0].get("data") if isinstance(done_events[0], dict) else {}
    if isinstance(done_data, dict):
        assert "usage" not in done_data
        assert "conversationUsage" not in done_data


def test_finalize_response_merges_live_usage_without_losing_cumulative_fields() -> None:
    finalizer = StreamFinalizer()
    now = datetime.now(timezone.utc)

    conversation = SimpleNamespace(
        id="conv_live_merge",
        user_id="user_live_merge",
        conversation_metadata={},
        updated_at=now,
    )
    run = SimpleNamespace(
        id="run_live_merge",
        status="running",
        finished_at=None,
        started_at=now - timedelta(seconds=2),
    )
    db = _FakeSession(conversation=conversation, run=run)

    state = StreamState(full_response="Done", live_input_tokens=200)
    _, done_events = finalizer.finalize_response(
        db=db,  # type: ignore[arg-type]
        conversation_id="conv_live_merge",
        user_message_id="user_evt_live_merge",
        state=state,
        usage_calculator=_LiveMergeUsageCalculator(),  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5.4",
        start_time=now - timedelta(seconds=2),
        cancelled=False,
        opts=FinalizationOptions(
            message_status="completed",
            include_done_chunk=True,
        ),
    )

    assert done_events and done_events[0]["type"] == "done"
    done_data = done_events[0].get("data") if isinstance(done_events[0], dict) else {}
    assert isinstance(done_data, dict)
    conversation_usage = done_data.get("conversationUsage")
    assert isinstance(conversation_usage, dict)
    assert conversation_usage.get("input_tokens") == 200
    assert conversation_usage.get("output_tokens") == 0
    assert conversation_usage.get("total_tokens") == 200
    assert conversation_usage.get("remaining_context_tokens") == 1_049_800
    assert conversation_usage.get("max_context_tokens") == 1_050_000
    assert conversation_usage.get("cumulative_input_tokens") == 3_200
    assert conversation_usage.get("cumulative_output_tokens") == 500
    assert conversation_usage.get("cumulative_total_tokens") == 3_700
