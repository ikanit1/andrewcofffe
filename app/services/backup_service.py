import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from app.db import engine as default_engine
from app.models.inventory import utcnow
from app.timezone import to_almaty

logger = logging.getLogger(__name__)


def _rotate(backups_dir: Path, keep_days: int) -> None:
    cutoff = time.time() - keep_days * 86400
    for f in backups_dir.glob("pos-*.db"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            logger.warning("Не удалось удалить старый бэкап %s", f)


def make_local_backup(*, engine=None, backups_dir=None, keep_days=None, now=None) -> Path:
    """Онлайн-снимок SQLite через sqlite3.backup() (безопасно при WAL) + ротация."""
    from app.config import settings
    engine = engine if engine is not None else default_engine
    backups_dir = Path(backups_dir) if backups_dir is not None else Path(settings.backups_dir)
    keep_days = keep_days if keep_days is not None else settings.backup_keep_days
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = to_almaty(now or utcnow()).strftime("%Y%m%d-%H%M%S")
    dest_path = backups_dir / f"pos-{stamp}.db"
    raw = engine.raw_connection()
    try:
        src = raw.driver_connection
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        raw.close()
    _rotate(backups_dir, keep_days)
    return dest_path


@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    delivered_count: int
    error: str | None = None


async def send_backup_to_admins(bot, path: Path, session, *, caption: str) -> int:
    """Шлёт файл бэкапа каждому активному админу. Возвращает число доставок."""
    from aiogram.types import FSInputFile
    from app.services.user_service import admin_telegram_ids

    delivered = 0
    for tg_id in admin_telegram_ids(session):
        try:
            await bot.send_document(tg_id, FSInputFile(str(path)), caption=caption)
            delivered += 1
        except Exception:
            logger.exception("Не удалось отправить бэкап админу %s", tg_id)
    return delivered


async def run_backup_once(*, engine=None, backups_dir=None, session_factory=None,
                          bot=None, now=None) -> BackupResult:
    """Локальный снимок (всегда) + отправка админам (если есть бот/токен)."""
    from app.config import settings
    from app.db import SessionLocal

    session_factory = session_factory or SessionLocal
    path = make_local_backup(engine=engine, backups_dir=backups_dir, now=now)
    size = path.stat().st_size
    error = "Файл больше 50 МБ — Telegram может отклонить" if size > 50 * 1024 * 1024 else None

    owns_bot = False
    if bot is None and settings.bot_token:
        from aiogram import Bot
        bot = Bot(settings.bot_token)
        owns_bot = True

    delivered = 0
    if bot is not None:
        try:
            with session_factory() as session:
                stamp = to_almaty(now or utcnow()).strftime("%d.%m %H:%M")
                caption = f"Бэкап {stamp} ({size / 1024 / 1024:.1f} МБ)"
                delivered = await send_backup_to_admins(bot, path, session, caption=caption)
        except Exception as e:
            error = f"{error + '; ' if error else ''}отправка не удалась: {e}"
        finally:
            if owns_bot:
                await bot.session.close()

    return BackupResult(path=path, size_bytes=size, delivered_count=delivered, error=error)
