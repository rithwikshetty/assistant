from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.services.usage_service import UsageService


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


class _SnapshotQuery:
    def __init__(self, row):  # type: ignore[no-untyped-def]
        self._row = row

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):  # type: ignore[no-untyped-def]
        return self._row


class _SnapshotSession:
    def __init__(self, row):  # type: ignore[no-untyped-def]
        self._row = row

    def query(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return _SnapshotQuery(self._row)


def test_upsert_global_snapshot_uses_atomic_on_conflict_update() -> None:
    db = _ExecuteOnlySession()
    service = UsageService()

    service._upsert_global_snapshot(
        db=db,  # type: ignore[arg-type]
        scope="all",
        totals={
            "total_users": 10,
            "total_conversations": 20,
            "total_messages": 30,
            "total_files": 40,
            "total_storage_bytes": 50,
        },
        refreshed_at=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc),
    )

    assert len(db.executed) == 1
    sql = _to_sql(db.executed[0])
    assert "insert into admin_global_snapshot" in sql
    assert "on conflict" in sql
    assert "do update" in sql
    assert "total_users" in sql
    assert "total_conversations" in sql


def test_global_totals_from_snapshot_uses_fresh_row_without_refresh() -> None:
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        scope="all",
        total_users=12,
        total_conversations=23,
        total_messages=34,
        total_files=45,
        total_storage_bytes=56,
        refreshed_at=now,
    )
    db = _SnapshotSession(row)
    service = UsageService()

    def _should_not_compute(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise AssertionError("Fresh snapshots should not trigger totals recomputation")

    service._compute_global_totals = _should_not_compute  # type: ignore[method-assign]

    totals = service._global_totals_from_snapshot(
        db=db,  # type: ignore[arg-type]
        include_admins=True,
        include_file_totals=True,
    )

    assert totals == {
        "total_users": 12,
        "total_conversations": 23,
        "total_messages": 34,
        "total_files": 45,
        "total_storage_bytes": 56,
    }


def test_global_totals_from_snapshot_refreshes_stale_row_and_keeps_file_totals_when_not_requested() -> None:
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    row = SimpleNamespace(
        scope="all",
        total_users=3,
        total_conversations=4,
        total_messages=5,
        total_files=999,
        total_storage_bytes=888,
        refreshed_at=stale,
    )
    db = _SnapshotSession(row)
    service = UsageService()
    captured = {}

    def _fake_compute(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return {
            "total_users": 100,
            "total_conversations": 200,
            "total_messages": 300,
            "total_files": 0,
            "total_storage_bytes": 0,
        }

    def _capture_upsert(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

    service._compute_global_totals = _fake_compute  # type: ignore[method-assign]
    service._upsert_global_snapshot = _capture_upsert  # type: ignore[method-assign]

    totals = service._global_totals_from_snapshot(
        db=db,  # type: ignore[arg-type]
        include_admins=True,
        include_file_totals=False,
    )

    assert totals["total_users"] == 100
    assert totals["total_conversations"] == 200
    assert totals["total_messages"] == 300
    assert totals["total_files"] == 999
    assert totals["total_storage_bytes"] == 888
    assert captured["scope"] == "all"
    assert captured["totals"]["total_files"] == 999
