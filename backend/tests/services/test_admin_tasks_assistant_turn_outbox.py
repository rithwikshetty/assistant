from datetime import datetime, timezone
from types import SimpleNamespace

from app.chat.services.assistant_turn_analytics import AssistantTurnAnalyticsService
from app.services.admin import tasks as admin_tasks

MESSAGE_ID = "11111111-1111-1111-1111-111111111111"
CONVERSATION_ID = "22222222-2222-2222-2222-222222222222"
RUN_ID = "33333333-3333-3333-3333-333333333333"


class _QueryStub:
    def __init__(self, *, all_result=None, first_result=None):
        self._all_result = all_result
        self._first_result = first_result
        self.for_update_calls = []

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def limit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def with_for_update(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.for_update_calls.append({"args": args, "kwargs": kwargs})
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._all_result or [])

    def first(self):  # type: ignore[no-untyped-def]
        return self._first_result


class _DBStub:
    def __init__(self, *, outbox_rows, message, conversation, run):
        self._outbox_rows = outbox_rows
        self._message = message
        self._conversation = conversation
        self._run = run
        self.flush_count = 0
        self.outbox_query = None

    def query(self, model):  # type: ignore[no-untyped-def]
        model_name = getattr(model, "__name__", "")
        if model_name == "AnalyticsOutbox":
            self.outbox_query = _QueryStub(all_result=self._outbox_rows)
            return self.outbox_query
        if model_name == "Message":
            rows = [self._message] if self._message is not None else []
            return _QueryStub(all_result=rows, first_result=self._message)
        if model_name == "Conversation":
            rows = [self._conversation] if self._conversation is not None else []
            return _QueryStub(all_result=rows, first_result=self._conversation)
        if model_name == "ChatRun":
            rows = [self._run] if self._run is not None else []
            return _QueryStub(all_result=rows, first_result=self._run)
        raise AssertionError(f"Unexpected query model: {model_name}")

    class _NestedTransaction:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

    def begin_nested(self):  # type: ignore[no-untyped-def]
        return self._NestedTransaction()

    def flush(self):  # type: ignore[no-untyped-def]
        self.flush_count += 1


def test_process_assistant_turn_outbox_batch_sync_processes_rows(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        payload_jsonb={
            "message_id": MESSAGE_ID,
            "conversation_id": CONVERSATION_ID,
            "run_id": RUN_ID,
            "usage": {"input_tokens": 12},
        },
        processed_at=None,
        retry_count=0,
        error=None,
        created_at=datetime.now(timezone.utc),
        id=1,
    )
    message = SimpleNamespace(id=MESSAGE_ID, conversation_id=CONVERSATION_ID, run_id=RUN_ID)
    conversation = SimpleNamespace(id=CONVERSATION_ID, user_id="user_1")
    run = SimpleNamespace(id=RUN_ID)
    db = _DBStub(
        outbox_rows=[outbox_row],
        message=message,
        conversation=conversation,
        run=run,
    )

    calls = []

    def _record_rollup(self, *, db, conversation, message, run, usage_payload):  # type: ignore[no-untyped-def]
        calls.append(
            {
                "db": db,
                "conversation": conversation,
                "message": message,
                "run": run,
                "usage_payload": usage_payload,
            }
        )

    monkeypatch.setattr(AssistantTurnAnalyticsService, "sync_rollups", _record_rollup)

    result = admin_tasks._process_assistant_turn_outbox_batch_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=25,
    )

    assert result == {"scanned": 1, "processed": 1, "errors": 0}
    assert outbox_row.processed_at is not None
    assert outbox_row.error is None
    assert db.flush_count == 1
    assert db.outbox_query is not None
    assert db.outbox_query.for_update_calls == [{"args": (), "kwargs": {"skip_locked": True}}]
    assert len(calls) == 1
    assert calls[0]["usage_payload"] == {"input_tokens": 12}


def test_process_assistant_turn_outbox_batch_sync_marks_errors(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        payload_jsonb={
            "conversation_id": CONVERSATION_ID,
            "usage": {"input_tokens": 12},
        },
        processed_at=None,
        retry_count=0,
        error=None,
        created_at=datetime.now(timezone.utc),
        id=2,
    )
    db = _DBStub(
        outbox_rows=[outbox_row],
        message=None,
        conversation=None,
        run=None,
    )

    monkeypatch.setattr(
        AssistantTurnAnalyticsService,
        "sync_rollups",
        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    result = admin_tasks._process_assistant_turn_outbox_batch_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=10,
    )

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert outbox_row.processed_at is None
    assert outbox_row.retry_count == 1
    assert isinstance(outbox_row.error, str) and "missing message_id" in outbox_row.error
    assert db.flush_count == 1
    assert db.outbox_query is not None
    assert db.outbox_query.for_update_calls == [{"args": (), "kwargs": {"skip_locked": True}}]


def test_process_assistant_turn_outbox_batch_sync_isolates_invalid_uuid_rows(monkeypatch) -> None:
    invalid_row = SimpleNamespace(
        payload_jsonb={
            "message_id": "not-a-uuid",
            "conversation_id": CONVERSATION_ID,
            "run_id": RUN_ID,
            "usage": {"input_tokens": 3},
        },
        processed_at=None,
        retry_count=0,
        error=None,
        created_at=datetime.now(timezone.utc),
        id=3,
    )
    valid_row = SimpleNamespace(
        payload_jsonb={
            "message_id": MESSAGE_ID,
            "conversation_id": CONVERSATION_ID,
            "run_id": RUN_ID,
            "usage": {"input_tokens": 12},
        },
        processed_at=None,
        retry_count=0,
        error=None,
        created_at=datetime.now(timezone.utc),
        id=4,
    )
    db = _DBStub(
        outbox_rows=[invalid_row, valid_row],
        message=SimpleNamespace(id=MESSAGE_ID, conversation_id=CONVERSATION_ID, run_id=RUN_ID),
        conversation=SimpleNamespace(id=CONVERSATION_ID, user_id="user_1"),
        run=SimpleNamespace(id=RUN_ID),
    )

    calls = []

    def _record_rollup(self, *, db, conversation, message, run, usage_payload):  # type: ignore[no-untyped-def]
        calls.append(
            {
                "db": db,
                "conversation": conversation,
                "message": message,
                "run": run,
                "usage_payload": usage_payload,
            }
        )

    monkeypatch.setattr(AssistantTurnAnalyticsService, "sync_rollups", _record_rollup)

    result = admin_tasks._process_assistant_turn_outbox_batch_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=25,
    )

    assert result == {"scanned": 2, "processed": 1, "errors": 1}
    assert invalid_row.processed_at is None
    assert invalid_row.retry_count == 1
    assert invalid_row.error == "invalid message_id"
    assert valid_row.processed_at is not None
    assert valid_row.error is None
    assert len(calls) == 1
    assert calls[0]["message"].id == MESSAGE_ID
    assert calls[0]["usage_payload"] == {"input_tokens": 12}
    assert db.flush_count == 1
    assert db.outbox_query is not None
    assert db.outbox_query.for_update_calls == [{"args": (), "kwargs": {"skip_locked": True}}]


def test_process_assistant_turn_outbox_batch_sync_dead_letters_exhausted_rows(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        payload_jsonb={
            "message_id": MESSAGE_ID,
            "conversation_id": CONVERSATION_ID,
            "usage": {"input_tokens": 12},
        },
        processed_at=None,
        retry_count=1,
        error="previous failure",
        created_at=datetime.now(timezone.utc),
        id=3,
    )
    db = _DBStub(
        outbox_rows=[outbox_row],
        message=None,
        conversation=None,
        run=None,
    )

    monkeypatch.setattr(admin_tasks.settings, "analytics_outbox_max_retries", 1)
    monkeypatch.setattr(
        AssistantTurnAnalyticsService,
        "sync_rollups",
        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    result = admin_tasks._process_assistant_turn_outbox_batch_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=10,
    )

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert outbox_row.processed_at is not None
    assert isinstance(outbox_row.error, str) and outbox_row.error.startswith("dead_lettered:max_retries_exceeded")
    assert db.flush_count == 1
    assert db.outbox_query is not None
    assert db.outbox_query.for_update_calls == [{"args": (), "kwargs": {"skip_locked": True}}]
