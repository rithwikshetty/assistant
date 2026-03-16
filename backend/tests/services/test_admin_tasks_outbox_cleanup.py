from app.database.models import AnalyticsOutbox
from app.services.admin import tasks as admin_tasks


class _SelectQueryStub:
    def __init__(self, ids):  # type: ignore[no-untyped-def]
        self._ids = ids

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def limit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return [(row_id,) for row_id in self._ids]


class _DeleteQueryStub:
    def __init__(self, db):  # type: ignore[no-untyped-def]
        self._db = db

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def delete(self, synchronize_session=False):  # type: ignore[no-untyped-def]
        del synchronize_session
        self._db.delete_calls += 1
        return len(self._db.ids)


class _CleanupDBStub:
    def __init__(self, ids):  # type: ignore[no-untyped-def]
        self.ids = ids
        self.flush_count = 0
        self.delete_calls = 0

    def query(self, model):  # type: ignore[no-untyped-def]
        model_name = getattr(model, "__name__", "")
        if model_name == "AnalyticsOutbox":
            return _DeleteQueryStub(self)
        if model is AnalyticsOutbox.id:
            return _SelectQueryStub(self.ids)
        raise AssertionError(f"Unexpected query model: {model_name}")

    def flush(self):  # type: ignore[no-untyped-def]
        self.flush_count += 1


def test_cleanup_analytics_outbox_sync_deletes_processed_rows() -> None:
    db = _CleanupDBStub(ids=[101, 102, 103])

    result = admin_tasks._cleanup_analytics_outbox_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=500,
        retention_days=14,
    )

    assert result == {"deleted": 3}
    assert db.delete_calls == 1
    assert db.flush_count == 1


def test_cleanup_analytics_outbox_sync_noop_when_no_candidates() -> None:
    db = _CleanupDBStub(ids=[])

    result = admin_tasks._cleanup_analytics_outbox_sync(  # type: ignore[attr-defined]
        db,  # type: ignore[arg-type]
        batch_size=500,
        retention_days=14,
    )

    assert result == {"deleted": 0}
    assert db.delete_calls == 0
    assert db.flush_count == 0
