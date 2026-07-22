from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.backup_scheduler import seconds_until

TZ = ZoneInfo("Asia/Almaty")


def test_seconds_until_later_today():
    now = datetime(2026, 7, 22, 1, 0, tzinfo=TZ)
    assert seconds_until("03:00", now) == 2 * 3600


def test_seconds_until_wraps_to_tomorrow():
    now = datetime(2026, 7, 22, 4, 0, tzinfo=TZ)
    assert seconds_until("03:00", now) == 23 * 3600


def test_seconds_until_exact_now_is_next_day():
    now = datetime(2026, 7, 22, 3, 0, tzinfo=TZ)
    assert seconds_until("03:00", now) == 24 * 3600
