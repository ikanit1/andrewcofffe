import logging
import sqlite3
import time
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
