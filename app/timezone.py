from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.inventory import utcnow

ALMATY = ZoneInfo("Asia/Almaty")


def to_almaty(dt: datetime) -> datetime:
    """Переводит datetime в Asia/Almaty. Naive datetime трактуется как UTC —
    SQLite не сохраняет offset для DateTime(timezone=True), поэтому значения,
    перечитанные из БД в новой сессии, приходят naive, хотя по соглашению
    проекта все datetime хранятся и создаются в UTC (см. utcnow())."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ALMATY)


def now_almaty() -> datetime:
    return to_almaty(utcnow())


def today_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Границы текущих суток по времени Алматы, выраженные в UTC.

    Нужны для сравнения с полями created_at (хранятся в UTC).
    """
    local_now = to_almaty(now) if now is not None else now_almaty()
    start_local = datetime.combine(local_now.date(), time.min, tzinfo=ALMATY)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
