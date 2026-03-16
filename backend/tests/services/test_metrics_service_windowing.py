from datetime import date, datetime, timezone

from app.services.metrics_service import _resolve_datetime_window


def test_resolve_datetime_window_with_explicit_dates_uses_inclusive_end_day() -> None:
    now = datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc)

    start_dt, end_exclusive_dt, effective_days = _resolve_datetime_window(
        now=now,
        days=30,
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 3),
    )

    assert start_dt == datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    assert end_exclusive_dt == datetime(2026, 2, 4, 0, 0, tzinfo=timezone.utc)
    assert effective_days == 3


def test_resolve_datetime_window_for_days_clamps_to_minimum_one_day() -> None:
    now = datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc)

    start_dt, end_exclusive_dt, effective_days = _resolve_datetime_window(
        now=now,
        days=0,
        start_date=None,
        end_date=None,
    )

    assert start_dt == datetime(2026, 2, 28, 0, 0, tzinfo=timezone.utc)
    assert end_exclusive_dt == datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    assert effective_days == 1
