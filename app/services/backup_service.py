import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.db import engine as default_engine
from app.models.inventory import utcnow
from app.timezone import to_almaty

logger = logging.getLogger(__name__)

# Без этих таблиц файл — не база кассы, а что-то постороннее.
_REQUIRED_TABLES = ("users", "products", "categories", "orders", "order_items", "payments")
# Что показываем владельцу перед восстановлением: сколько чего внутри файла.
_COUNTED_TABLES = (
    ("Товары", "products"),
    ("Чеки", "orders"),
    ("Позиции в чеках", "order_items"),
    ("Оплаты", "payments"),
    ("Смены", "shifts"),
    ("Пользователи", "users"),
)


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


# --------------------------------------------------------------------------
# Восстановление из копии
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupCheck:
    """Что внутри присланного файла и можно ли его разворачивать."""

    ok: bool
    problems: tuple[str, ...] = field(default_factory=tuple)
    counts: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    size_bytes: int = 0
    created_at: datetime | None = None


def inspect_backup(path: Path | str) -> BackupCheck:
    """Проверяет файл до подмены базы: целостность, состав таблиц, наполнение.

    Разворачивать непроверенный файл нельзя: испорченная копия молча заменит
    рабочую базу, и точка останется без чеков посреди дня.
    """
    path = Path(path)
    problems: list[str] = []
    if not path.exists():
        return BackupCheck(ok=False, problems=("Файл не найден",))
    size = path.stat().st_size
    if size == 0:
        return BackupCheck(ok=False, problems=("Файл пустой",), size_bytes=0)

    counts: list[tuple[str, int]] = []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return BackupCheck(ok=False, problems=(f"SQLite не открыл файл: {exc}",),
                           size_bytes=size)
    try:
        header = conn.execute("PRAGMA integrity_check").fetchone()
        if not header or str(header[0]).lower() != "ok":
            problems.append("Проверка целостности не прошла — файл повреждён")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in _REQUIRED_TABLES if t not in tables]
        if missing:
            problems.append("Это не база кассы: нет таблиц " + ", ".join(missing))
        else:
            for label, table in _COUNTED_TABLES:
                if table in tables:
                    counts.append((label, int(conn.execute(
                        f"SELECT COUNT(*) FROM {table}").fetchone()[0])))
            if not any(n for label, n in counts if label == "Пользователи"):
                problems.append("В копии нет ни одного пользователя — войти будет нечем")
    except sqlite3.DatabaseError as exc:
        problems.append(f"Файл не читается как база SQLite: {exc}")
    finally:
        conn.close()

    return BackupCheck(
        ok=not problems,
        problems=tuple(problems),
        counts=tuple(counts),
        size_bytes=size,
        created_at=datetime.fromtimestamp(path.stat().st_mtime),
    )


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    message: str
    previous_copy: str = ""      # имя копии рабочей базы, снятой перед подменой
    check: BackupCheck | None = None


def restore_from_file(path: Path | str, *, engine=None) -> RestoreResult:
    """Заменяет рабочую базу присланной копией.

    Порядок продиктован Windows и журналом SQLite:

    1. проверяем файл и запрещаем подмену при открытой смене — на своей
       короткоживущей сессии, потому что чужая открытая сессия держала бы
       файл базы и подмена сорвалась бы на полпути;
    2. снимаем копию текущей базы;
    3. закрываем соединения и удаляем -wal/-shm ДО подмены. Если журнал занят,
       прерываемся здесь — база ещё цела. Подменить сначала файл, а потом
       не суметь убрать журнал, значит получить смесь старых и новых данных.
    4. и только потом копируем присланный файл на место рабочего.

    Перезапуск сюда не входит — его планирует UI, как и при обновлении.
    """
    from sqlalchemy.orm import Session

    engine = engine if engine is not None else default_engine
    source = Path(path)

    check = inspect_backup(source)
    if not check.ok:
        return RestoreResult(ok=False, check=check,
                             message="Файл не прошёл проверку: " + "; ".join(check.problems))

    target = _database_path(engine)
    if target is None:
        return RestoreResult(ok=False, check=check,
                             message="Восстановление доступно только для SQLite-базы")
    if source.resolve() == target.resolve():
        return RestoreResult(ok=False, check=check,
                             message="Это и есть рабочая база — восстанавливать нечего")

    from app.services.shift_service import current_open_shift

    # Смену проверяем в той базе, которую собираемся заменить, а не через
    # глобальную сессию: иначе восстановление зависело бы от чужого файла.
    with Session(engine) as probe:
        if current_open_shift(probe) is not None:
            return RestoreResult(
                ok=False, check=check,
                message="Сначала закройте смену: подмена базы посреди смены "
                        "потеряет незакрытые чеки.")

    previous = ""
    try:
        if target.exists():
            backups = Path(target.parent / "backups")
            backups.mkdir(parents=True, exist_ok=True)
            copy = backups / f"pos-before-restore-{datetime.now():%Y-%m-%d_%H%M%S}.db"
            # Снимок делаем через SQLite, а не копированием файла: рядом может
            # лежать незаписанный WAL, и голая копия вышла бы неполной.
            raw = engine.raw_connection()
            try:
                dst = sqlite3.connect(copy)
                try:
                    raw.driver_connection.backup(dst)
                finally:
                    dst.close()
            finally:
                raw.close()
            previous = copy.name

        engine.dispose()
        for sidecar in (f"{target}-wal", f"{target}-shm"):
            Path(sidecar).unlink(missing_ok=True)
        shutil.copy2(source, target)
    except OSError as exc:
        hint = ""
        if getattr(exc, "winerror", None) == 32:
            hint = (" Файл базы занят другим процессом — закройте вторую вкладку "
                    "кассы или остановите её и повторите.")
        return RestoreResult(
            ok=False, check=check, previous_copy=previous,
            message=f"Не удалось заменить базу: {exc}.{hint} "
                    f"Рабочая база не тронута.")

    # Схему присланной копии дотягиваем до текущей версии кода: копия могла быть
    # снята со старой версии, где part колонок ещё не было.
    try:
        from app.db import init_db

        init_db()
    except Exception as exc:  # noqa: BLE001 — база уже подменена, откат хуже
        logger.exception("Схему восстановленной базы обновить не удалось")
        return RestoreResult(
            ok=False, check=check, previous_copy=previous,
            message=f"База заменена, но обновить её схему не удалось: {exc}. "
                    f"Прежняя база сохранена как backups/{previous}.")

    return RestoreResult(
        ok=True, check=check, previous_copy=previous,
        message=("База восстановлена из копии. Прежняя сохранена как "
                 f"backups/{previous}." if previous else "База восстановлена из копии."))


def _database_path(engine) -> Path | None:
    if engine.dialect.name != "sqlite":
        return None
    name = engine.url.database
    if not name or name == ":memory:":
        return None
    return Path(name)
