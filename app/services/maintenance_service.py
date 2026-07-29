"""Обслуживание кассы: заранее определённый набор операций.

Экран «Сервер» показывает, что не так; чинит — этот модуль. Список операций
закрыт и задан здесь, кнопки на экране лишь вызывают их по имени. Касса смотрит
наружу через Tailscale Funnel, и поле «выполните запрос» на такой странице
превратило бы одну угнанную вкладку в полный доступ к моноблоку.

Ни одна функция не бросает наружу: причина уходит в MaintenanceResult(ok=False).
Обслуживание открывают, когда уже что-то сломалось, и падение страницы скрыло бы
как раз то, ради чего её открыли.
"""
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db import engine as default_engine

# Битая база выдаёт по строке на каждую испорченную страницу — их могут быть
# тысячи. На экран пускаем только начало: причина видна и по первым строкам.
_MAX_DETAIL_LINES = 20

# Копии с этим префиксом делают руками перед рискованным шагом (см. updater.py
# и скрипты в корне проекта). Под маску pos-*.db они попадают, но чистка их не
# трогает: стереть по расписанию единственную точку отката хуже, чем занять место.
_MANUAL_BACKUP_PREFIX = "pos-before-"


@dataclass(frozen=True)
class MaintenanceResult:
    ok: bool
    title: str
    message: str
    detail: str = ""
    freed_bytes: int = 0


def wal_checkpoint(*, engine: Engine | None = None) -> MaintenanceResult:
    """Возвращает накопленные изменения из журнала WAL в основной файл базы.

    Штатно SQLite делает это сам, но только когда журнал никто не читает. У кассы
    соединения живут постоянно, и файл -wal может месяцами расти, ни разу не
    усекаясь: на боевой базе он доходил до 4 МБ при самой базе в 224 КБ.
    """
    engine = engine if engine is not None else default_engine
    wal = _wal_path(engine)
    before = _size(wal)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            row = conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)")).fetchone()
    except Exception as exc:  # noqa: BLE001 — причина уходит владельцу в detail
        return _failed("Контрольная точка WAL", exc)

    after = _size(wal)
    freed = max(0, before - after)
    # PRAGMA отдаёт три числа: busy (кто-то мешал), сколько страниц в журнале и
    # сколько удалось перенести. busy=1 — журнал читают прямо сейчас, и усечь его
    # не дали; это не ошибка, просто повторить позже.
    busy = int(row[0]) if row is not None and len(row) >= 1 else 0
    if busy:
        return MaintenanceResult(
            ok=True, title="Контрольная точка WAL",
            message="Журнал перенесён в базу не полностью: с ней сейчас работают. "
                    "Повторите, когда касса будет свободна.",
            detail=f"было {_mb(before)}, стало {_mb(after)}", freed_bytes=freed,
        )
    return MaintenanceResult(
        ok=True, title="Контрольная точка WAL",
        message=f"Журнал изменений перенесён в базу, освободилось {_mb(freed)}.",
        detail=f"было {_mb(before)}, стало {_mb(after)}", freed_bytes=freed,
    )


def vacuum(*, engine: Engine | None = None) -> MaintenanceResult:
    """Перестраивает файл базы, возвращая диску место после удалённых строк."""
    engine = engine if engine is not None else default_engine
    db = _database_path(engine)
    before = _size(db)
    started = time.perf_counter()
    try:
        # VACUUM нельзя выполнить внутри транзакции, а SQLAlchemy открывает её
        # неявно на каждом соединении. Без AUTOCOMMIT операция падает с
        # «cannot VACUUM from within a transaction».
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))
    except Exception as exc:  # noqa: BLE001
        return _failed("Сжатие базы", exc)

    after = _size(db)
    freed = max(0, before - after)
    took = time.perf_counter() - started
    return MaintenanceResult(
        ok=True, title="Сжатие базы",
        message=(f"База сжата, освободилось {_mb(freed)}." if freed
                 else "База сжата, но свободного места в ней и не было — "
                      "это нормально."),
        detail=f"было {_mb(before)}, стало {_mb(after)}, заняло {took:.1f} с",
        freed_bytes=freed,
    )


def analyze(*, engine: Engine | None = None) -> MaintenanceResult:
    """Обновляет статистику, по которой SQLite выбирает план запроса.

    После крупного импорта меню или чистки чеков старая статистика заставляет
    базу читать таблицы целиком там, где хватило бы индекса, — отчёты открываются
    заметно дольше без всякой видимой причины.
    """
    engine = engine if engine is not None else default_engine
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("ANALYZE"))
    except Exception as exc:  # noqa: BLE001
        return _failed("Обновление статистики", exc)
    return MaintenanceResult(
        ok=True, title="Обновление статистики",
        message="Статистика обновлена — отчёты будут строиться по свежим данным.",
    )


def integrity_check(*, engine: Engine | None = None) -> MaintenanceResult:
    """Проверяет, цела ли база и нет ли битых ссылок между таблицами."""
    engine = engine if engine is not None else default_engine
    try:
        with engine.connect() as conn:
            pages = [str(r[0]) for r in conn.execute(text("PRAGMA integrity_check")).fetchall()]
            orphans = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    except Exception as exc:  # noqa: BLE001
        return _failed("Проверка целостности", exc)

    problems = [p for p in pages if p.lower() != "ok"]
    problems += [f"битая ссылка в таблице {r[0]} (строка {r[1]})" for r in orphans]
    if not problems:
        return MaintenanceResult(
            ok=True, title="Проверка целостности",
            message="База в порядке: повреждений и битых ссылок нет.",
        )
    return MaintenanceResult(
        ok=False, title="Проверка целостности",
        message=f"Найдено проблем: {len(problems)}. Восстановите базу из копии "
                f"в разделе «Бэкапы» — работать на повреждённой опасно.",
        detail=_trim(problems),
    )


def archive_log(*, root: Path | str | None = None,
                now: datetime | None = None) -> MaintenanceResult:
    """Отправляет накопившийся журнал в отдельный файл, начиная новый с нуля.

    deploy/run-server.ps1 пишет в logs/server.log через >> и не ротирует его
    никогда — за месяцы работы файл вырастает до десятков мегабайт, и открыть
    его на моноблоке становится нечем.
    """
    base = Path(root) if root is not None else _project_root()
    log = base / "logs" / "server.log"
    if not log.exists():
        return MaintenanceResult(
            ok=False, title="Архивирование журнала",
            message="Журнала нет — сервер ни разу не запускался через start.ps1.",
        )

    size = _size(log)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    archived = log.with_name(f"server-{stamp}.log")
    try:
        log.rename(archived)
        log.touch()
    except OSError as exc:
        # На Windows переименовать файл, открытый другим процессом, нельзя. Журнал
        # держит запущенный cmd из run-server.ps1, так что это обычный случай, а не
        # сбой. Обрезать или удалять файл силой не пытаемся: пишущий процесс
        # продолжит писать по старому смещению и оставит дыру из нулей.
        return MaintenanceResult(
            ok=False, title="Архивирование журнала",
            message="Журнал занят запущенным сервером — заархивировать его можно "
                    "только при остановленной кассе.",
            detail=f"{type(exc).__name__}: {exc}",
        )
    return MaintenanceResult(
        ok=True, title="Архивирование журнала",
        message=f"Журнал на {_mb(size)} убран в {archived.name}, запись пошла заново.",
        freed_bytes=size,
    )


def cleanup_backups(*, keep_days: int | None = None,
                    backups_dir: Path | str | None = None) -> MaintenanceResult:
    """Удаляет автоматические копии базы старше keep_days.

    Ручные копии (pos-before-*.db) не трогает: их делают перед обновлением и
    другими рискованными шагами, и именно к ним возвращаются, когда что-то пошло
    не так, — иногда спустя недели.
    """
    from app.config import settings

    directory = Path(backups_dir) if backups_dir is not None else Path(settings.backups_dir)
    days = keep_days if keep_days is not None else settings.backup_keep_days
    cutoff = time.time() - days * 86400

    removed = 0
    freed = 0
    kept_manual = 0
    failed: list[str] = []
    try:
        candidates = sorted(directory.glob("pos-*.db"))
    except OSError as exc:
        return _failed("Чистка копий базы", exc)

    for f in candidates:
        if f.name.startswith(_MANUAL_BACKUP_PREFIX):
            kept_manual += 1
            continue
        try:
            st = f.stat()
            if st.st_mtime >= cutoff:
                continue
            f.unlink()
        except OSError as exc:
            failed.append(f"{f.name}: {exc}")
            continue
        removed += 1
        freed += st.st_size

    detail = _trim(failed) if failed else (
        f"ручных копий сохранено: {kept_manual}" if kept_manual else "")
    return MaintenanceResult(
        ok=not failed, title="Чистка копий базы",
        message=(f"Удалено копий: {removed}, освободилось {_mb(freed)}." if removed
                 else f"Удалять нечего — все копии свежее {days} дней."),
        detail=detail, freed_bytes=freed,
    )


def _project_root() -> Path:
    from app.services.updater import PROJECT_ROOT

    return PROJECT_ROOT


def _database_path(engine: Engine) -> Path | None:
    """Файл базы. None — база в памяти (тесты) или движок не SQLite."""
    if engine.dialect.name != "sqlite":
        return None
    name = engine.url.database
    if not name or name == ":memory:":
        return None
    return Path(name)


def _wal_path(engine: Engine) -> Path | None:
    db = _database_path(engine)
    return None if db is None else Path(f"{db}-wal")


def _size(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _trim(lines: list[str]) -> str:
    shown = lines[:_MAX_DETAIL_LINES]
    if len(lines) > _MAX_DETAIL_LINES:
        shown.append(f"…и ещё {len(lines) - _MAX_DETAIL_LINES}")
    return "\n".join(shown)


def _failed(title: str, exc: Exception) -> MaintenanceResult:
    return MaintenanceResult(
        ok=False, title=title,
        message="Операция не выполнилась — база и файлы остались как были.",
        detail=f"{type(exc).__name__}: {exc}",
    )


def _mb(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} МБ"
