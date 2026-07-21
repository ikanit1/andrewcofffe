from datetime import datetime, timezone

from app.timezone import now_almaty, to_almaty, today_bounds_utc


def test_to_almaty_converts_utc_to_plus5():
    utc_dt = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    almaty_dt = to_almaty(utc_dt)
    assert almaty_dt.hour == 15
    assert almaty_dt.utcoffset().total_seconds() == 5 * 3600


def test_now_almaty_is_aware_and_offset_plus5():
    dt = now_almaty()
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 5 * 3600


def test_today_bounds_utc_midnight_almaty_is_19_utc_previous_day():
    # 2026-07-21 02:00 UTC = 2026-07-21 07:00 Алматы (UTC+5) — те же сутки Алматы
    now = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    start, end = today_bounds_utc(now)
    assert start == datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc)


def test_today_bounds_utc_before_almaty_midnight_uses_previous_utc_day():
    # 2026-07-20 18:00 UTC = 2026-07-20 23:00 Алматы — ещё те же сутки (20 июля Алматы)
    now = datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)
    start, end = today_bounds_utc(now)
    assert start == datetime(2026, 7, 19, 19, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc)
