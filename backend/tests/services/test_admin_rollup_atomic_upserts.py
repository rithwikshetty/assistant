from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.chat.services.assistant_turn_analytics import AssistantTurnAnalyticsService
from app.database.models import AnalyticsOutbox, FactAssistantTurn, UserActivity
from app.services.admin.event_recorder import AdminEventRecorder


def _to_sql(stmt) -> str:  # type: ignore[no-untyped-def]
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


class _ExecuteOnlySession:
    def __init__(self) -> None:
        self.executed = []

    def execute(self, stmt):  # type: ignore[no-untyped-def]
        self.executed.append(stmt)
        return None

    def query(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise AssertionError("Atomic rollup paths should not require read-before-write queries")

    def flush(self):  # type: ignore[no-untyped-def]
        return None


class _AddOnlySession:
    def __init__(self) -> None:
        self.added = []

    def add(self, value):  # type: ignore[no-untyped-def]
        self.added.append(value)

    def execute(self, stmt):  # type: ignore[no-untyped-def]
        del stmt
        raise AssertionError("record_user_message should not use execute() directly")

    def query(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise AssertionError("record_user_message should not query")

    def flush(self):  # type: ignore[no-untyped-def]
        return None


class _AnalyticsQuery:
    def __init__(self, *, first_result=None, all_result=None, scalar_result=None) -> None:
        self._first_result = first_result
        self._all_result = all_result if all_result is not None else []
        self._scalar_result = scalar_result

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._all_result)

    def first(self):  # type: ignore[no-untyped-def]
        return self._first_result

    def scalar(self):  # type: ignore[no-untyped-def]
        return self._scalar_result

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return 0


class _AnalyticsSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, value):  # type: ignore[no-untyped-def]
        self.added.append(value)

    def flush(self):  # type: ignore[no-untyped-def]
        return None

    def query(self, model):  # type: ignore[no-untyped-def]
        model_name = getattr(model, "__name__", "")
        if model_name in {"ToolCall", "FactToolCall"}:
            return _AnalyticsQuery(all_result=[])
        if model_name == "FactAssistantTurn":
            return _AnalyticsQuery(first_result=None)
        if getattr(model, "key", None) == "role":
            return _AnalyticsQuery(scalar_result="user")
        if getattr(model, "key", None) == "message_id" and getattr(getattr(model, "class_", None), "__name__", "") == "FactAssistantTurn":
            return _AnalyticsQuery(first_result=None)
        raise AssertionError(f"Unexpected analytics query target: {model!r}")


def test_event_recorder_conversation_rollup_uses_atomic_upsert() -> None:
    db = _ExecuteOnlySession()

    AdminEventRecorder._increment_user_conversation_count(
        db,  # type: ignore[arg-type]
        user_id="user_123",
    )

    assert len(db.executed) == 1
    sql = _to_sql(db.executed[0])
    assert "insert into admin_user_rollup" in sql
    assert "on conflict" in sql
    assert "do update" in sql
    assert "conversation_count" in sql


def test_assistant_turn_rollup_delta_uses_atomic_upsert() -> None:
    db = _ExecuteOnlySession()
    service = AssistantTurnAnalyticsService()

    service._apply_admin_user_rollup_delta(
        db=db,  # type: ignore[arg-type]
        user_id="user_456",
        turn_count_delta=2,
        cost_delta=Decimal("0.125"),
        last_assistant_turn_at=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc),
    )

    assert len(db.executed) == 1
    sql = _to_sql(db.executed[0])
    assert "insert into admin_user_rollup" in sql
    assert "on conflict" in sql
    assert "assistant_turn_count" in sql
    assert "total_cost_usd" in sql


def test_sync_rollups_handles_first_turn_without_existing_fact(monkeypatch) -> None:
    db = _AnalyticsSession()
    service = AssistantTurnAnalyticsService()

    monkeypatch.setattr(service, "_apply_usage_rollup_delta", lambda **kwargs: None)
    monkeypatch.setattr(service, "_apply_model_rollup_delta", lambda **kwargs: None)
    monkeypatch.setattr(service, "_apply_tool_rollup_delta", lambda **kwargs: None)
    monkeypatch.setattr(service, "_apply_admin_user_rollup_delta", lambda **kwargs: None)

    created_at = datetime(2026, 3, 6, 10, 0, tzinfo=timezone.utc)
    conversation = SimpleNamespace(id="conv_1", user_id="user_1", project_id=None)
    message = SimpleNamespace(
        id="msg_1",
        created_at=created_at,
        response_latency_ms=420,
        cost_usd=Decimal("0.42"),
        model_provider="openai",
        model_name="gpt-5.4",
    )
    run = SimpleNamespace(id="run_1")

    service.sync_rollups(
        db=db,  # type: ignore[arg-type]
        conversation=conversation,
        message=message,
        run=run,
        usage_payload={
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
            "reasoning_output_tokens": 12,
        },
    )

    fact_rows = [item for item in db.added if isinstance(item, FactAssistantTurn)]
    assert len(fact_rows) == 1


def test_record_user_message_emits_activity_and_outbox_rows(monkeypatch) -> None:
    db = _AddOnlySession()
    recorder = AdminEventRecorder()
    created_at = datetime(2026, 3, 2, 9, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(
        AdminEventRecorder,
        "_dispatch_activity_outbox_worker",
        staticmethod(lambda: None),
    )

    recorder.record_user_message(
        db,  # type: ignore[arg-type]
        user_id="user_789",
        target_id="msg_123",
        conversation_id="conv_123",
        run_id="run_123",
        request_id="req_123",
        created_at=created_at,
    )

    assert len(db.added) == 2
    activity = next(item for item in db.added if isinstance(item, UserActivity))
    outbox = next(item for item in db.added if isinstance(item, AnalyticsOutbox))

    assert activity.user_id == "user_789"
    assert activity.activity_type == "user_message_submitted"
    assert str(activity.target_id) == "msg_123"
    assert str(activity.conversation_id) == "conv_123"
    assert str(activity.run_id) == "run_123"
    assert activity.metadata_jsonb == {
        "message_id": "msg_123",
        "request_id": "req_123",
    }
    assert activity.created_at == created_at

    assert outbox.event_type == "analytics.activity.recorded"
    assert outbox.event_version == 1
    assert outbox.entity_id == "msg_123"
    assert outbox.payload_jsonb["activity_type"] == "user_message_submitted"
    assert outbox.payload_jsonb["user_id"] == "user_789"
    assert outbox.payload_jsonb["target_id"] == "msg_123"
    assert outbox.payload_jsonb["message_id"] == "msg_123"
    assert outbox.payload_jsonb["conversation_id"] == "conv_123"
    assert outbox.payload_jsonb["run_id"] == "run_123"
    assert outbox.payload_jsonb["request_id"] == "req_123"
    assert outbox.payload_jsonb["metadata"]["message_id"] == "msg_123"
    assert outbox.payload_jsonb["metadata"]["request_id"] == "req_123"
    assert outbox.payload_jsonb["created_at"] == created_at.isoformat()


def test_record_share_created_emits_activity_and_outbox_rows(monkeypatch) -> None:
    db = _AddOnlySession()
    recorder = AdminEventRecorder()

    monkeypatch.setattr(
        AdminEventRecorder,
        "_dispatch_activity_outbox_worker",
        staticmethod(lambda: None),
    )

    recorder.record_share_created(
        db,  # type: ignore[arg-type]
        user_id="user_321",
        share_id="share_123",
    )

    assert len(db.added) == 2
    activity = next(item for item in db.added if isinstance(item, UserActivity))
    outbox = next(item for item in db.added if isinstance(item, AnalyticsOutbox))

    assert activity.user_id == "user_321"
    assert activity.activity_type == "share_created"
    assert str(activity.target_id) == "share_123"

    assert outbox.event_type == "analytics.activity.recorded"
    assert outbox.event_version == 1
    assert outbox.entity_id == "share_123"
    assert outbox.payload_jsonb["activity_type"] == "share_created"
    assert outbox.payload_jsonb["user_id"] == "user_321"
    assert outbox.payload_jsonb["target_id"] == "share_123"


def test_record_output_applied_to_live_work_emits_activity_and_outbox_rows(monkeypatch) -> None:
    db = _AddOnlySession()
    recorder = AdminEventRecorder()
    created_at = datetime(2026, 3, 3, 8, 45, tzinfo=timezone.utc)

    monkeypatch.setattr(
        AdminEventRecorder,
        "_dispatch_activity_outbox_worker",
        staticmethod(lambda: None),
    )

    recorder.record_output_applied_to_live_work(
        db,  # type: ignore[arg-type]
        user_id="user_654",
        task_id="task_123",
        conversation_id="conv_987",
        created_at=created_at,
    )

    assert len(db.added) == 2
    activity = next(item for item in db.added if isinstance(item, UserActivity))
    outbox = next(item for item in db.added if isinstance(item, AnalyticsOutbox))

    assert activity.user_id == "user_654"
    assert activity.activity_type == "output_applied_to_live_work"
    assert str(activity.target_id) == "task_123"
    assert str(activity.task_id) == "task_123"
    assert str(activity.conversation_id) == "conv_987"
    assert activity.metadata_jsonb is None
    assert activity.created_at == created_at

    assert outbox.event_type == "analytics.activity.recorded"
    assert outbox.event_version == 1
    assert outbox.entity_id == "task_123"
    assert outbox.payload_jsonb["activity_type"] == "output_applied_to_live_work"
    assert outbox.payload_jsonb["user_id"] == "user_654"
    assert outbox.payload_jsonb["target_id"] == "task_123"
    assert outbox.payload_jsonb["task_id"] == "task_123"
    assert outbox.payload_jsonb["conversation_id"] == "conv_987"
    assert outbox.payload_jsonb["created_at"] == created_at.isoformat()


def test_record_output_deployed_to_live_work_emits_activity_and_outbox_rows(monkeypatch) -> None:
    db = _AddOnlySession()
    recorder = AdminEventRecorder()

    monkeypatch.setattr(
        AdminEventRecorder,
        "_dispatch_activity_outbox_worker",
        staticmethod(lambda: None),
    )

    recorder.record_output_deployed_to_live_work(
        db,  # type: ignore[arg-type]
        user_id="user_777",
        task_id="task_456",
        conversation_id="conv_654",
    )

    assert len(db.added) == 2
    activity = next(item for item in db.added if isinstance(item, UserActivity))
    outbox = next(item for item in db.added if isinstance(item, AnalyticsOutbox))

    assert activity.user_id == "user_777"
    assert activity.activity_type == "output_deployed_to_live_work"
    assert str(activity.target_id) == "task_456"
    assert str(activity.task_id) == "task_456"
    assert str(activity.conversation_id) == "conv_654"
    assert activity.metadata_jsonb is None

    assert outbox.event_type == "analytics.activity.recorded"
    assert outbox.event_version == 1
    assert outbox.entity_id == "task_456"
    assert outbox.payload_jsonb["activity_type"] == "output_deployed_to_live_work"
    assert outbox.payload_jsonb["user_id"] == "user_777"
    assert outbox.payload_jsonb["target_id"] == "task_456"
    assert outbox.payload_jsonb["task_id"] == "task_456"
    assert outbox.payload_jsonb["conversation_id"] == "conv_654"
