from datetime import datetime, timedelta, timezone

from app.utils.datetime_helpers import format_utc_z


def test_format_utc_z_for_aware_datetime() -> None:
    value = datetime(2026, 3, 3, 12, 5, 9, tzinfo=timezone.utc)
    assert format_utc_z(value) == "2026-03-03T12:05:09Z"


def test_format_utc_z_converts_offset_datetime_to_utc() -> None:
    plus_ten = timezone(timedelta(hours=10))
    value = datetime(2026, 3, 3, 23, 15, 0, tzinfo=plus_ten)
    assert format_utc_z(value) == "2026-03-03T13:15:00Z"


def test_format_utc_z_treats_naive_datetime_as_utc() -> None:
    value = datetime(2026, 3, 3, 9, 30, 0)
    assert format_utc_z(value) == "2026-03-03T09:30:00Z"
