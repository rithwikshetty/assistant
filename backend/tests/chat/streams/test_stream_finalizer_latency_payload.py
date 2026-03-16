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


class _StubUsageCalculator:
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


def test_finalize_response_persists_latency_fields_for_terminal_messages() -> None:
    finalizer = StreamFinalizer()

    conversation = SimpleNamespace(
        id="conv_1",
        user_id="user_1",
        conversation_metadata={},
        updated_at=datetime.now(timezone.utc),
    )
    run = SimpleNamespace(
        id="run_1",
        status="running",
        finished_at=None,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
    )
    db = _FakeSession(conversation=conversation, run=run)

    state = StreamState(full_response="Done")
    usage_calculator = _StubUsageCalculator()
    start_time = datetime.now(timezone.utc) - timedelta(seconds=2)
    _, done_events = finalizer.finalize_response(
        db=db,  # type: ignore[arg-type]
        conversation_id="conv_1",
        user_message_id="user_evt_1",
        state=state,
        usage_calculator=usage_calculator,  # type: ignore[arg-type]
        provider_name="openai",
        effective_model="gpt-5",
        start_time=start_time,
        cancelled=True,
        opts=FinalizationOptions(
            message_status="cancelled",
            include_done_chunk=True,
        ),
    )

    assistant_messages = [
        item for item in db.added
        if getattr(item, "role", None) == "assistant"
    ]
    assert assistant_messages, "expected assistant message to be inserted"

    assistant_message = assistant_messages[-1]
    assert assistant_message.status == "cancelled"
    assert isinstance(assistant_message.response_latency_ms, int)
    assert assistant_message.response_latency_ms >= 1000
    assert assistant_message.finish_reason == "cancelled"
    assert done_events and done_events[0]["type"] == "done"
