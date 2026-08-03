"""Состояние сервера кассы — то же, что показывает deploy/status.ps1, но в браузер.

Раньше ответы на вопрос «а всё ли в порядке?» были доступны только тому, кто стоит
перед моноблоком и может запустить status.ps1. Владелец бывает в кофейне не каждый
день, а касса смотрит наружу через Tailscale Funnel — значит, те же сведения нужно
уметь собрать изнутри процесса и отдать на экран.

Модуль только читает. Ни одна функция здесь ничего не чинит и не меняет: всё
лечение (контрольная точка WAL, VACUUM, чистка бэкапов) живёт в
maintenance_service, и владелец запускает его сам, увидев, что именно не так.

Метрики, которые не удалось получить, — None, а не ноль. Ноль на экране читается
как измеренное значение («процессор простаивает», «диск пустой»), и владелец
принял бы отсутствие данных за факт.
"""
import ctypes
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import (NotificationOutbox, Order, OrderItem,
                        Payment, Product, Refund, Shift, StockMove)
from app.services import updater, updates
from app.services.runtime import TaskState

try:
    import psutil
except ImportError:  # необязательная зависимость: без неё считаем сами
    psutil = None
else:
    # cpu_percent() без интервала возвращает загрузку с прошлого вызова, а самый
    # первый вызов — всегда 0.0: он только запоминает точку отсчёта. Тратим её
    # здесь, на импорте, иначе первое открытие экрана врало бы про простой
    # процессора. Мерить с interval=1 нельзя — это секунда мёртвого event loop.
    try:
        psutil.cpu_percent()
    except Exception:
        pass

_MB = 1024 * 1024
_GB = 1024 * 1024 * 1024

# Хвост журнала, который читаем с конца. Файл не ротируется и растёт месяцами:
# читать его целиком — это десятки мегабайт в памяти ради последних строк.
_TAIL_BYTES = 256 * 1024

_ERROR_MARKERS = ("error", "traceback", "exception", "critical", "упал", "не удалось")

# Пороги предупреждений. Вынесены наверх: их правят по опыту эксплуатации,
# и искать их по телу функции неудобно.
_DISK_BAD_GB = 1.0
_DISK_WARN_GB = 5.0
_WAL_RATIO = 10
_WAL_MIN_BYTES = 8 * _MB
_FREELIST_RATIO = 0.20
_FREELIST_MIN_BYTES = 5 * _MB
_BACKUP_STALE_HOURS = 48.0
_RAM_WARN_PERCENT = 90.0
_LOG_WARN_BYTES = 50 * _MB

# Человеческое имя -> модель. Порядок задаёт порядок строк на экране: сначала то,
# что растёт от продаж, потом справочники.
_COUNTED_TABLES = (
    ("Чеки", Order),
    ("Позиции в чеках", OrderItem),
    ("Оплаты", Payment),
    ("Возвраты", Refund),
    ("Движения склада", StockMove),
    ("Товары", Product),
    ("Смены", Shift),
    ("Очередь уведомлений", NotificationOutbox),
)


@dataclass(frozen=True)
class AppInfo:
    version: str
    python: str
    platform: str
    pid: int
    supervised: bool
    project_root: str
    started_at: datetime | None
    uptime_seconds: float | None
    public_url: str


@dataclass(frozen=True)
class Resources:
    cpu_percent: float | None
    ram_process_mb: float | None
    ram_total_mb: float | None
    ram_used_percent: float | None
    disk_free_gb: float | None
    disk_total_gb: float | None
    disk_used_percent: float | None
    source: str  # "psutil" | "stdlib"


@dataclass(frozen=True)
class TableRow:
    name: str
    table: str
    rows: int


@dataclass(frozen=True)
class DatabaseInfo:
    path: str
    size_bytes: int
    wal_bytes: int
    shm_bytes: int
    journal_mode: str
    page_size: int
    page_count: int
    freelist_pages: int
    wasted_bytes: int
    tables: list[TableRow] = field(default_factory=list)
    oldest_order_at: datetime | None = None
    newest_order_at: datetime | None = None


@dataclass(frozen=True)
class BackupsInfo:
    count: int
    total_bytes: int
    latest_name: str
    latest_at: datetime | None
    age_hours: float | None
    stale: bool


@dataclass(frozen=True)
class LogInfo:
    path: str
    size_bytes: int
    lines: list[str] = field(default_factory=list)
    error_lines: int = 0
    # Сколько строк прочитано с конца файла. Счётчик ошибок считается по ним всем,
    # а на экран попадает только limit последних — без этого числа «170 ошибок»
    # рядом со 120 показанными строками читается как «почти всё сломано».
    scanned_lines: int = 0


@dataclass(frozen=True)
class Issue:
    level: str  # "warn" | "bad"
    text: str
    hint: str


def app_info(*, root: Path | str | None = None, now: datetime | None = None) -> AppInfo:
    """Паспорт процесса: версия, окружение, время работы, адрес снаружи."""
    base = Path(root) if root is not None else updater.PROJECT_ROOT
    from app.config import settings
    from app.services import runtime

    return AppInfo(
        version=updates.local_version(),
        python=sys.version.split()[0],
        platform=platform.platform(),
        pid=os.getpid(),
        supervised=updater.is_supervised(),
        project_root=str(base),
        started_at=runtime.started_at(),
        uptime_seconds=runtime.uptime_seconds(now),
        public_url=settings.public_url,
    )


def resources(*, root: Path | str | None = None) -> Resources:
    """Процессор, память и диск. Не бросает исключений ни при каких обстоятельствах.

    Экран состояния — последнее место, где допустима ошибка: его открывают именно
    тогда, когда с кассой что-то не так, и падение здесь скрыло бы причину.
    """
    base = Path(root) if root is not None else updater.PROJECT_ROOT
    free_gb, total_gb, used_pct = _disk(base)

    if psutil is not None:
        vm = _safe(psutil.virtual_memory)
        return Resources(
            cpu_percent=_safe(lambda: round(float(psutil.cpu_percent()), 1)),
            ram_process_mb=_safe(
                lambda: round(psutil.Process().memory_info().rss / _MB, 1)),
            ram_total_mb=round(vm.total / _MB, 1) if vm is not None else None,
            ram_used_percent=round(float(vm.percent), 1) if vm is not None else None,
            disk_free_gb=free_gb, disk_total_gb=total_gb, disk_used_percent=used_pct,
            source="psutil",
        )

    total_mb, load_percent = _safe(_windows_ram) or (None, None)
    return Resources(
        cpu_percent=None,  # честного мгновенного замера без psutil нет
        ram_process_mb=_safe(_windows_process_ram_mb),
        ram_total_mb=total_mb,
        ram_used_percent=load_percent,
        disk_free_gb=free_gb, disk_total_gb=total_gb, disk_used_percent=used_pct,
        source="stdlib",
    )


def database_info(session: Session, *, engine=None) -> DatabaseInfo:
    """Размеры файлов базы, режим журнала и счётчики строк.

    Путь к файлу берём у движка, а не из настроек: на экране должна быть та база,
    которую сейчас читает сессия, — на временной базе (тесты, копия) настройки
    показали бы боевой pos.db.
    """
    bind = engine if engine is not None else session.get_bind()
    db_path = str(getattr(getattr(bind, "url", None), "database", "") or "")
    is_sqlite = getattr(bind.dialect, "name", "") == "sqlite"
    on_disk = bool(db_path) and db_path != ":memory:"

    page_size = page_count = freelist = 0
    journal_mode = ""
    if is_sqlite:
        # PRAGMA спрашиваем у самой сессии: у базы в памяти отдельное соединение
        # открыло бы пустую копию, и все цифры оказались бы нулями.
        reader = session if engine is None else engine.connect()
        try:
            journal_mode = str(_pragma(reader, "journal_mode") or "")
            page_size = int(_pragma(reader, "page_size") or 0)
            page_count = int(_pragma(reader, "page_count") or 0)
            freelist = int(_pragma(reader, "freelist_count") or 0)
        finally:
            if reader is not session:
                reader.close()

    present = _existing_tables(session, bind)
    tables = [
        TableRow(name=name, table=model.__tablename__,
                 rows=int(session.scalar(select(func.count()).select_from(model)) or 0))
        for name, model in _COUNTED_TABLES
        if model.__tablename__ in present
    ]

    oldest = newest = None
    if Order.__tablename__ in present:
        oldest = _as_utc(session.scalar(select(func.min(Order.created_at))))
        newest = _as_utc(session.scalar(select(func.max(Order.created_at))))

    main = Path(db_path) if on_disk else None
    return DatabaseInfo(
        path=db_path,
        size_bytes=_file_size(main),
        wal_bytes=_file_size(Path(f"{db_path}-wal") if on_disk else None),
        shm_bytes=_file_size(Path(f"{db_path}-shm") if on_disk else None),
        journal_mode=journal_mode,
        page_size=page_size,
        page_count=page_count,
        freelist_pages=freelist,
        wasted_bytes=freelist * page_size,
        tables=tables,
        oldest_order_at=oldest,
        newest_order_at=newest,
    )


def backups_info(*, backups_dir: Path | str | None = None,
                 now: datetime | None = None) -> BackupsInfo:
    """Сколько копий базы лежит рядом и насколько свежа последняя.

    Свежесть считаем по времени файла, а не по имени: копию могли положить руками
    или принести из другого места, и разбирать её имя было бы гаданием.
    """
    from app.config import settings

    directory = Path(backups_dir) if backups_dir is not None else Path(settings.backups_dir)
    entries: list[tuple[float, int, str]] = []
    try:
        for f in directory.glob("pos-*.db"):
            try:
                st = f.stat()
            except OSError:
                continue  # файл мог исчезнуть между glob и stat
            entries.append((st.st_mtime, st.st_size, f.name))
    except OSError:
        pass
    entries.sort()

    total = sum(size for _, size, _ in entries)
    if not entries:
        return BackupsInfo(count=0, total_bytes=0, latest_name="", latest_at=None,
                           age_hours=None, stale=True)

    mtime, _, name = entries[-1]
    latest_at = datetime.fromtimestamp(mtime, timezone.utc)
    moment = now if now is not None else datetime.now(timezone.utc)
    age_hours = (moment - latest_at).total_seconds() / 3600
    return BackupsInfo(count=len(entries), total_bytes=total, latest_name=name,
                       latest_at=latest_at, age_hours=age_hours,
                       stale=age_hours > _BACKUP_STALE_HOURS)


def log_tail(*, root: Path | str | None = None, limit: int = 200,
             errors_only: bool = False) -> LogInfo:
    """Последние строки logs/server.log.

    Журнал пишет deploy/run-server.ps1, он не ротируется и живёт месяцами, поэтому
    читаем только хвост файла. Декодируем с errors="replace": на границе чтения
    почти наверняка разрезана кириллическая буква, и строгий декодер уронил бы
    весь экран из-за одного полубайта.
    """
    path = (Path(root) if root is not None else updater.PROJECT_ROOT) / "logs" / "server.log"
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            start = max(0, size - _TAIL_BYTES)
            f.seek(start)
            chunk = f.read()
    except OSError:
        return LogInfo(path=str(path), size_bytes=0, lines=[], error_lines=0)

    lines = chunk.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # первая строка обрезана посередине — показывать нечего

    error_lines = sum(1 for line in lines if _is_error(line))
    shown = [line for line in lines if _is_error(line)] if errors_only else lines
    return LogInfo(path=str(path), size_bytes=size,
                   lines=shown[-limit:] if limit > 0 else [],
                   error_lines=error_lines, scanned_lines=len(lines))


def issues(app: AppInfo, res: Resources, db: DatabaseInfo, backups: BackupsInfo,
           tasks: list[TaskState], *, log: LogInfo | None = None) -> list[Issue]:
    """Что именно не так — с указанием, какую кнопку нажать.

    Подсказка всегда называет конкретное действие: «обратитесь к администратору»
    здесь бессмысленно, администратор — это и есть тот, кто смотрит на экран.

    log отсутствует в остальных сигнатурах модуля намеренно: размер журнала —
    единственная проверка, для которой не хватает уже собранных структур. Если
    его не передали, размер берём сами одним stat — это дешевле, чем заставлять
    экран читать хвост журнала ради одной цифры.
    """
    found: list[Issue] = []

    for task in tasks:
        if task.error:
            found.append(Issue(
                level="bad",
                text=f"Фоновая задача «{task.name}» остановилась: {task.error}",
                hint="Перезапустите кассу — задача поднимется вместе с сервером.",
            ))

    if res.disk_free_gb is not None:
        if res.disk_free_gb < _DISK_BAD_GB:
            found.append(Issue(
                level="bad",
                text=f"На диске осталось {res.disk_free_gb:.1f} ГБ — касса может "
                     f"перестать записывать продажи",
                hint="Удалите старые копии базы и заархивируйте журнал — обе кнопки "
                     "в разделе «Обслуживание» ниже.",
            ))
        elif res.disk_free_gb < _DISK_WARN_GB:
            found.append(Issue(
                level="warn",
                text=f"На диске осталось {res.disk_free_gb:.1f} ГБ",
                hint="Нажмите «Убрать старые копии» — обычно место занимают именно они.",
            ))

    if db.wal_bytes > _WAL_MIN_BYTES and db.wal_bytes > db.size_bytes * _WAL_RATIO:
        found.append(Issue(
            level="warn",
            text=f"Журнал изменений базы разросся: {_mb(db.wal_bytes)} при базе "
                 f"{_mb(db.size_bytes)}",
            hint="Нажмите «Контрольная точка WAL» — данные вернутся в основной файл.",
        ))

    if (db.wasted_bytes > _FREELIST_MIN_BYTES
            and db.size_bytes and db.wasted_bytes > db.size_bytes * _FREELIST_RATIO):
        found.append(Issue(
            level="warn",
            text=f"В базе {_mb(db.wasted_bytes)} пустого места после удалений",
            hint="Нажмите «Сжать базу (VACUUM)» — это освободит место на диске.",
        ))

    if backups.count == 0:
        found.append(Issue(
            level="bad",
            text="Резервных копий базы нет ни одной",
            hint="Проверьте BACKUP_ENABLED в .env и что задача «Бэкапы» работает "
                 "в списке выше.",
        ))
    elif backups.stale:
        age = f"{backups.age_hours / 24:.0f} сут" if backups.age_hours and backups.age_hours >= 48 \
            else f"{backups.age_hours:.0f} ч"
        found.append(Issue(
            level="warn",
            text=f"Последней копии базы уже {age}",
            hint="Проверьте, что задача «Бэкапы» работает, — иначе при поломке "
                 "восстанавливать будет нечего.",
        ))

    if res.ram_used_percent is not None and res.ram_used_percent > _RAM_WARN_PERCENT:
        found.append(Issue(
            level="warn",
            text=f"Память занята на {res.ram_used_percent:.0f}%",
            hint="Закройте лишние программы на моноблоке или перезагрузите его "
                 "до начала смены.",
        ))

    log_bytes = log.size_bytes if log is not None else _log_size(app.project_root)
    if log_bytes > _LOG_WARN_BYTES:
        found.append(Issue(
            level="warn",
            text=f"Журнал сервера вырос до {_mb(log_bytes)}",
            hint="Нажмите «Архивировать журнал» — старые записи уедут в отдельный файл.",
        ))

    # Сортировка устойчивая: внутри уровня остаётся порядок проверок, а сверху
    # оказывается то, из-за чего касса может встать сегодня.
    found.sort(key=lambda i: 0 if i.level == "bad" else 1)
    return found


def overall_verdict(found: list[Issue]) -> str:
    if any(i.level == "bad" for i in found):
        return "bad"
    return "warn" if found else "ok"


def _safe(fn):
    """Значение или None: одна недоступная метрика не должна ронять весь экран."""
    try:
        return fn()
    except Exception:
        return None


def _disk(base: Path) -> tuple[float | None, float | None, float | None]:
    """Свободно/всего/занято по диску, где лежит проект.

    shutil.disk_usage — тот же системный вызов, что и у psutil, поэтому отдельной
    ветки для psutil нет: разошлись бы только округления.
    """
    try:
        usage = shutil.disk_usage(base)
    except OSError:
        return None, None, None
    used_percent = (round((usage.total - usage.free) / usage.total * 100, 1)
                    if usage.total else None)
    return round(usage.free / _GB, 1), round(usage.total / _GB, 1), used_percent


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _windows_ram() -> tuple[float | None, float | None]:
    """Всего памяти в МБ и её загрузка в процентах через GlobalMemoryStatusEx."""
    if not hasattr(ctypes, "windll"):
        return None, None
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    return round(status.ullTotalPhys / _MB, 1), float(status.dwMemoryLoad)


def _windows_process_ram_mb() -> float | None:
    """Рабочий набор текущего процесса через psapi — аналог WorkingSet64 в status.ps1."""
    if not hasattr(ctypes, "windll"):
        return None
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    # Без argtypes ctypes передал бы псевдодескриптор процесса как 32-битный int,
    # и на 64-битной Windows вызов ушёл бы с обрезанным аргументом.
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_ProcessMemoryCounters), ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int

    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return round(counters.WorkingSetSize / _MB, 1)


def _pragma(reader, name: str):
    return reader.execute(text(f"PRAGMA {name}")).scalar()


def _existing_tables(session: Session, bind) -> set[str]:
    """Имена таблиц, которые реально есть в базе.

    Спрашиваем через сессию по той же причине, что и PRAGMA: inspect(engine)
    открыл бы своё соединение и для базы в памяти увидел бы пустоту.
    """
    if getattr(bind.dialect, "name", "") == "sqlite":
        return set(session.scalars(text("SELECT name FROM sqlite_master WHERE type='table'")))
    from sqlalchemy import inspect as sa_inspect

    return set(sa_inspect(bind).get_table_names())


def _as_utc(value) -> datetime | None:
    """SQLite отдаёт время без смещения — по соглашению проекта это UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _file_size(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _log_size(root: str) -> int:
    return _file_size(Path(root) / "logs" / "server.log")


def _is_error(line: str) -> bool:
    low = line.lower()
    return any(marker in low for marker in _ERROR_MARKERS)


def _mb(value: int) -> str:
    return f"{value / _MB:.1f} МБ"
