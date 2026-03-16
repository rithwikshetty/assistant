from datetime import date, datetime, timezone

from app.services.usage_service import _build_usage_window


def test_build_usage_window_preserves_full_range_for_aggregate_refresh() -> None:
    now = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)

    window = _build_usage_window(
        now=now,
        days=120,
        start_date=None,
        end_date=None,
    )

    assert window.range_start_day == date(2025, 10, 30)
    assert window.series_start_day == date(2025, 11, 30)
    assert window.ensure_start_day == date(2025, 10, 30)
    assert len(window.day_sequence) == 90


def test_build_usage_window_uses_explicit_start_end_dates() -> None:
    now = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)

    window = _build_usage_window(
        now=now,
        days=30,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 9, 10),
    )

    assert window.range_start_day == date(2025, 9, 1)
    assert window.range_end_day == date(2025, 9, 10)
    assert window.series_start_day == date(2025, 9, 1)
    assert window.ensure_start_day == date(2025, 9, 1)
    assert len(window.day_sequence) == 10


def test_build_usage_window_clamps_non_positive_days() -> None:
    now = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)

    window = _build_usage_window(
        now=now,
        days=0,
        start_date=None,
        end_date=None,
    )

    assert window.range_start_day == date(2026, 2, 26)
    assert window.series_start_day == date(2026, 2, 27)
    assert window.ensure_start_day == date(2026, 2, 26)
    assert len(window.day_sequence) == 1
