from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.admin import tasks as admin_tasks
from app.services.admin.model_usage_analytics import ModelUsageAnalyticsService

_VALID_USER_ID = "11111111-1111-1111-1111-111111111111"


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
    def __init__(self, *, outbox_rows, user_roles):
        self._outbox_rows = outbox_rows
        self._user_roles = user_roles
        self.flush_count = 0
        self.outbox_query = None

    def query(self, *models):  # type: ignore[no-untyped-def]
        model_name = getattr(models[0], "__name__", "") if models else ""
        if model_name == "AnalyticsOutbox":
            self.outbox_query = _QueryStub(all_result=self._outbox_rows)
            return self.outbox_query

        if models and len(models) == 2 and str(getattr(models[0], "key", "")) == "id":
            role_rows = [(uid, role) for uid, role in self._user_roles.items()]
            return _QueryStub(all_result=role_rows)

        raise AssertionError(f"Unexpected query models: {models}")

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


def test_process_model_usage_outbox_batch_sync_processes_rows(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        payload_jsonb={
            "event_id": "evt_1",
            "user_id": _VALID_USER_ID,
            "operation_type": "title_generation",
            "model_provider": "openai",
            "model_name": "gpt-4.1-nano",
        },
        entity_id="evt_1",
        processed_at=None,
        retry_count=0,
        error=None,
        created_at=datetime.now(timezone.utc),
        id=1,
    )
    db = _DBStub(
        outbox_rows=[outbox_row],
        user_roles={_VALID_USER_ID: "user"},
    )

    calls = []

    def _record_rollup(self, *, db, event_id, payload, is_admin_user, fallback_created_at):  # type: ignore[no-untyped-def]
        calls.append(
            {
                "db": db,
                "event_id": event_id,
                "payload": payload,
                "is_admin_user": is_admin_user,
                "fallback_created_at": fallback_created_at,
            }
        )
        return True

    monkeypatch.setattr(ModelUsageAnalyticsService, "sync_rollups", _record_rollup)

    result = admin_tasks._process_model_usage_outbox_batch_sync(  # type: ignore[attr-defined]
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
    assert calls[0]["event_id"] == "evt_1"
    assert calls[0]["is_admin_user"] is False


def test_process_model_usage_outbox_batch_sync_marks_errors(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        payload_jsonb={
            "user_id": _VALID_USER_ID,
            "operation_type": "title_generation",
        },
        entity_id="",
        processed_at=None,
        retry_count=0,
        error=None,
        created_at=datetime.now(timezone.utc),
        id=2,
    )
    db = _DBStub(
        outbox_rows=[outbox_row],
        user_roles={_VALID_USER_ID: "user"},
    )

    monkeypatch.setattr(
        ModelUsageAnalyticsService,
        "sync_rollups",
        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    result = admin_tasks._process_model_usage_outbox_batch_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=10,
    )

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert outbox_row.processed_at is None
    assert outbox_row.retry_count == 1
    assert isinstance(outbox_row.error, str) and "missing event_id" in outbox_row.error
    assert db.flush_count == 1
    assert db.outbox_query is not None
    assert db.outbox_query.for_update_calls == [{"args": (), "kwargs": {"skip_locked": True}}]


def test_process_model_usage_outbox_batch_sync_dead_letters_exhausted_rows(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        payload_jsonb={
            "event_id": "evt_1",
            "user_id": _VALID_USER_ID,
            "operation_type": "title_generation",
            "model_provider": "openai",
            "model_name": "gpt-4.1-nano",
        },
        entity_id="evt_1",
        processed_at=None,
        retry_count=1,
        error="previous failure",
        created_at=datetime.now(timezone.utc),
        id=3,
    )
    db = _DBStub(
        outbox_rows=[outbox_row],
        user_roles={_VALID_USER_ID: "user"},
    )

    monkeypatch.setattr(admin_tasks.settings, "analytics_outbox_max_retries", 1)
    monkeypatch.setattr(
        ModelUsageAnalyticsService,
        "sync_rollups",
        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    result = admin_tasks._process_model_usage_outbox_batch_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=10,
    )

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert outbox_row.processed_at is not None
    assert isinstance(outbox_row.error, str) and outbox_row.error.startswith("dead_lettered:max_retries_exceeded")
    assert db.flush_count == 1
    assert db.outbox_query is not None
    assert db.outbox_query.for_update_calls == [{"args": (), "kwargs": {"skip_locked": True}}]


def test_process_model_usage_outbox_batch_sync_marks_invalid_user_ids(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        payload_jsonb={
            "event_id": "evt_1",
            "user_id": "user_1",
            "operation_type": "title_generation",
            "model_provider": "openai",
            "model_name": "gpt-4.1-nano",
        },
        entity_id="evt_1",
        processed_at=None,
        retry_count=0,
        error=None,
        created_at=datetime.now(timezone.utc),
        id=4,
    )
    db = _DBStub(
        outbox_rows=[outbox_row],
        user_roles={_VALID_USER_ID: "user"},
    )

    calls = []

    def _record_rollup(self, *, db, event_id, payload, is_admin_user, fallback_created_at):  # type: ignore[no-untyped-def]
        calls.append(
            {
                "db": db,
                "event_id": event_id,
                "payload": payload,
                "is_admin_user": is_admin_user,
                "fallback_created_at": fallback_created_at,
            }
        )
        return True

    monkeypatch.setattr(ModelUsageAnalyticsService, "sync_rollups", _record_rollup)

    result = admin_tasks._process_model_usage_outbox_batch_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=25,
    )

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert outbox_row.processed_at is None
    assert outbox_row.retry_count == 1
    assert isinstance(outbox_row.error, str) and outbox_row.error  # error contains the invalid user_id
    assert db.flush_count == 1
    assert len(calls) == 0
