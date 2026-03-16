from datetime import date

from sqlalchemy.dialects import postgresql

from app.services.feedback_service import FeedbackService


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
        raise AssertionError("Atomic feedback rollup path should not require query reads")


class _GroupedRowsQuery:
    def __init__(self, rows) -> None:  # type: ignore[no-untyped-def]
        self._rows = rows

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def group_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return self._rows


class _GroupedRowsSession:
    def __init__(self, rows) -> None:  # type: ignore[no-untyped-def]
        self._rows = rows

    def query(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return _GroupedRowsQuery(self._rows)


class _NoQuerySession:
    def query(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise AssertionError("Role-stable updates should return before querying")


def test_add_feedback_delta_uses_atomic_upsert_for_all_scopes() -> None:
    service = FeedbackService()
    db = _ExecuteOnlySession()

    service._add_feedback_delta(
        db,  # type: ignore[arg-type]
        metric_date=date(2026, 3, 2),
        user_role="user",
        delta={
            "total_count": 1,
            "up_count": 1,
            "down_count": 0,
            "time_saved_minutes": 5,
            "time_spent_minutes": 0,
        },
    )

    assert len(db.executed) == 2
    sql_all = _to_sql(db.executed[0])
    sql_non_admin = _to_sql(db.executed[1])
    assert "insert into agg_feedback_day" in sql_all
    assert "insert into agg_feedback_day" in sql_non_admin
    assert "on conflict" in sql_all
    assert "on conflict" in sql_non_admin


def test_role_change_adjusts_non_admin_feedback_rollup_delta(monkeypatch) -> None:
    service = FeedbackService()
    db = _GroupedRowsSession(
        rows=[
            (date(2026, 3, 1), 3, 2, 1, 20, 8),
        ]
    )
    captured = []

    def _capture(db, *, metric_date, scope, delta):  # type: ignore[no-untyped-def]
        del db
        captured.append((metric_date, scope, delta))

    monkeypatch.setattr(FeedbackService, "_apply_feedback_delta_atomic", staticmethod(_capture))

    service.adjust_non_admin_rollup_for_role_change(
        db=db,  # type: ignore[arg-type]
        user_id="user_999",
        old_role="user",
        new_role="admin",
    )

    assert len(captured) == 1
    metric_date, scope, delta = captured[0]
    assert metric_date == date(2026, 3, 1)
    assert scope == "non_admin"
    assert delta["total_count"] == -3
    assert delta["up_count"] == -2
    assert delta["down_count"] == -1
    assert delta["time_saved_minutes"] == -20
    assert delta["time_spent_minutes"] == -8


def test_role_stable_change_does_not_recompute_feedback_rollups() -> None:
    service = FeedbackService()

    service.adjust_non_admin_rollup_for_role_change(
        db=_NoQuerySession(),  # type: ignore[arg-type]
        user_id="user_stable",
        old_role="user",
        new_role="user",
    )

