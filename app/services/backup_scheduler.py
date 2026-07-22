import asyncio
import logging
from datetime import datetime, timedelta

from app.models.inventory import utcnow
from app.timezone import to_almaty

logger = logging.getLogger(__name__)


def seconds_until(target_hhmm: str, now: datetime) -> float:
    """Секунды от now до ближайшего наступления HH:MM (в той же таймзоне, что и now)."""
    hh, mm = (int(x) for x in target_hhmm.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_backup_scheduler(*, engine=None) -> None:
    """Раз в сутки в settings.backup_time делает бэкап. Ошибки не убивают цикл."""
    from app.config import settings
    from app.services.backup_service import run_backup_once

    while True:
        delay = seconds_until(settings.backup_time, to_almaty(utcnow()))
        await asyncio.sleep(delay)
        try:
            result = await run_backup_once(engine=engine)
            logger.info("Бэкап: %s (%d Б, доставлено %d)%s",
                        result.path, result.size_bytes, result.delivered_count,
                        f", ошибка: {result.error}" if result.error else "")
        except Exception:
            logger.exception("Плановый бэкап не удался")
