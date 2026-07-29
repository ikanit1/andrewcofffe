"""Проверка производительности кассы: тормозит ли она и из-за чего.

Владелец жмёт кнопку на экране «Сервер» и получает несколько строк с понятным
ответом — быстро ли отвечает база, быстро ли открываются отчёты, успевает ли
диск. У каждой строки свой вердикт и подсказка, что с этим делать; общий
вердикт отчёта — худший из частных.

Ни одна проверка не меняет боевые данные. Скорость записи меряется на отдельной
временной базе рядом с pos.db (тот же диск — на системном temp замер соврал бы
про скорость), которая вместе с -wal и -shm удаляется в finally. INSERT в
рабочие таблицы не делается даже с последующим ROLLBACK: журнал и счётчики
всё равно изменились бы, а цена ошибки здесь — испорченный отчёт по выручке.
"""
import asyncio
import os
import shutil
import sqlite3
import statistics
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import engine as default_engine
from app.models.inventory import utcnow
from app.services import reporting_service

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# По префиксу видно, чей файл остался в каталоге, если касса упала посреди замера.
TEMP_PREFIX = "perfcheck-"

# Названия проверок — на них ссылаются и экран, и тесты; порядок в отчёте такой же.
NAME_DB_PING = "Отклик базы"
NAME_REPORT = "Чтение отчёта за месяц"
NAME_WRITE = "Запись в базу"
NAME_DISK = "Скорость диска"
NAME_FREE_SPACE = "Свободное место"
NAME_WAL = "Размер журнала WAL"
NAME_CPU = "Загрузка процессора"
NAME_RAM = "Занято памяти"

# Пороги сняты с моноблока с SSD, на котором стоит касса. SELECT 1 не читает ни
# одной страницы данных, поэтому дольше 25 мс он идёт не от «много работы», а от
# занятого диска или блокировки базы долгой операцией — это уже повод чинить.
#
# Порог месячного отчёта намеренно выше «мгновенного»: на живой базе со ста чеками
# он занимает около 300 мс, и жёлтая строка на исправной кассе научила бы владельца
# не верить экрану вовсе. Предупреждаем там, где задержку уже видно глазом.
DB_PING_OK_MS = 5.0
DB_PING_WARN_MS = 25.0
REPORT_OK_MS = 800.0
REPORT_WARN_MS = 2500.0
WRITE_OK_MS = 200.0
WRITE_WARN_MS = 800.0
DISK_OK_MBPS = 50.0      # ниже 15 МБ/с — это HDD или флешка, чек будет проводиться с паузой
DISK_WARN_MBPS = 15.0
FREE_SPACE_OK_GB = 5.0   # меньше гигабайта — SQLite перестанет принимать чеки
FREE_SPACE_WARN_GB = 1.0
CPU_OK_PCT = 70.0
CPU_WARN_PCT = 90.0
RAM_OK_PCT = 80.0
RAM_WARN_PCT = 92.0

# Журнал WAL нормально больше базы в разы; тревожно, когда он и кратно больше,
# и сам по себе крупный — тогда контрольная точка давно не проходила.
WAL_BIG_MB = 8.0
WAL_BIG_RATIO = 10.0

# Объёмы замеров. quick — для автозапуска при открытии экрана: он должен
# уложиться в доли секунды, полный прогон владелец запускает кнопкой.
PING_QUERIES = 50
PING_QUERIES_QUICK = 10
WRITE_ROWS = 200
WRITE_ROWS_QUICK = 50
DISK_MB = 8
DISK_MB_QUICK = 2

_VERDICT_WEIGHT = {"ok": 0, "warn": 1, "bad": 2}


@dataclass(frozen=True)
class PerfCheck:
    name: str
    value: float
    unit: str
    verdict: str  # "ok" | "warn" | "bad"
    hint: str
    detail: str = ""


@dataclass(frozen=True)
class PerfReport:
    checks: list[PerfCheck]
    verdict: str
    took_ms: int
    at: datetime  # aware UTC


def verdict_for(value: float, *, ok: float, warn: float, higher_is_better: bool = False) -> str:
    """Число -> вердикт по порогам.

    Отдельная чистая функция, чтобы правила проверялись тестами, а не скоростью
    машины, на которой тесты запускают: на медленном CI настоящий замер выдаст
    что угодно, и проверять по нему пороговую логику бессмысленно.

    Ровно на границе вердикт выбирается в худшую сторону: предупреждение лучше
    показать чуть раньше, чем на день позже, когда чеки уже не проводятся.
    """
    if higher_is_better:
        if value > ok:
            return "ok"
        return "warn" if value > warn else "bad"
    if value < ok:
        return "ok"
    return "warn" if value < warn else "bad"


def worst_verdict(verdicts) -> str:
    """Общий вердикт — худший из частных: одна красная строка важнее пяти зелёных."""
    return max(verdicts, key=lambda v: _VERDICT_WEIGHT.get(v, 0), default="ok")


def run_performance_check(
    *,
    engine: Engine | None = None,
    root: Path | None = None,
    now: datetime | None = None,
    quick: bool = False,
) -> PerfReport:
    """Прогоняет все замеры по очереди. Синхронная и тяжёлая — из UI звать асинхронную обёртку."""
    engine = engine if engine is not None else default_engine
    root = Path(root) if root is not None else PROJECT_ROOT
    started = time.perf_counter()

    plan = [
        (NAME_DB_PING, lambda: _db_ping_check(engine, quick=quick)),
        (NAME_REPORT, lambda: _report_check(engine, now)),
        (NAME_WRITE, lambda: _write_check(root, quick=quick)),
        (NAME_DISK, lambda: _disk_check(root, quick=quick)),
        (NAME_FREE_SPACE, lambda: _free_space_check(root)),
        (NAME_WAL, lambda: _wal_check(engine, root)),
    ]
    checks = [_guarded(name, measure) for name, measure in plan]
    checks.extend(_load_checks())

    return PerfReport(
        checks=checks,
        verdict=worst_verdict(c.verdict for c in checks),
        took_ms=int(round((time.perf_counter() - started) * 1000)),
        at=now if now is not None else utcnow(),
    )


async def run_performance_check_async(
    *,
    engine: Engine | None = None,
    root: Path | None = None,
    now: datetime | None = None,
    quick: bool = False,
) -> PerfReport:
    """Тот же прогон, но в рабочем потоке.

    У NiceGUI один event loop на всё приложение: синхронный замер на несколько
    секунд заморозил бы экран кассира посреди продажи — кнопки не нажимались бы,
    пока меряется диск. asyncio.to_thread уводит замер в поток, а файловые
    операции и запросы SQLite отпускают GIL, так что касса продолжает работать.
    """
    return await asyncio.to_thread(
        run_performance_check, engine=engine, root=root, now=now, quick=quick
    )


def _guarded(name: str, measure) -> PerfCheck:
    """Упавшая проверка не должна уносить с собой весь отчёт.

    Каталог может оказаться закрытым на запись, база — заблокированной: тогда
    честнее показать одну красную строку с причиной, чем пустой экран.
    """
    try:
        return measure()
    except Exception as exc:  # noqa: BLE001 — причина уходит владельцу в detail
        return PerfCheck(
            name=name, value=0.0, unit="", verdict="bad",
            hint="Проверка не выполнилась — подробности в строке ниже.",
            detail=f"{type(exc).__name__}: {exc}",
        )


def _hint(verdict: str, message: str) -> str:
    """Подсказка нужна только когда что-то не так: на зелёной строке она мусор."""
    return message if verdict != "ok" else ""


def _ru(value: float, digits: int = 1) -> str:
    """Дробное число по-русски: «3,11», а не «3.11» — экран читает владелец, не сервер."""
    return f"{value:.{digits}f}".replace(".", ",")


def _db_ping_check(engine: Engine, *, quick: bool) -> PerfCheck:
    repeats = PING_QUERIES_QUICK if quick else PING_QUERIES
    samples: list[float] = []
    with engine.connect() as conn:
        for _ in range(repeats):
            started = time.perf_counter()
            conn.execute(text("SELECT 1")).scalar()
            samples.append((time.perf_counter() - started) * 1000)
    # Медиана, а не среднее: одна случайная пауза планировщика Windows сдвинула
    # бы среднее так, что здоровая база выглядела бы больной.
    value = round(statistics.median(samples), 2)
    verdict = verdict_for(value, ok=DB_PING_OK_MS, warn=DB_PING_WARN_MS)
    return PerfCheck(
        name=NAME_DB_PING, value=value, unit="мс", verdict=verdict,
        hint=_hint(verdict, "Диск занят другой программой или базу держит долгая "
                            "операция: проверьте копирование файлов и антивирус."),
        detail=f"{repeats} запросов, худший {_ru(max(samples), 2)} мс",
    )


def _report_check(engine: Engine, now: datetime | None) -> PerfCheck:
    """Честный замер: ровно те запросы, которых владелец ждёт, открывая отчёты."""
    period = reporting_service.period_from_preset("month", now)
    started = time.perf_counter()
    with Session(engine) as session:
        summary = reporting_service.summary(session, period)
        reporting_service.revenue_by_day(session, period)
        reporting_service.top_products(session, period)
    value = round((time.perf_counter() - started) * 1000, 1)
    verdict = verdict_for(value, ok=REPORT_OK_MS, warn=REPORT_WARN_MS)
    return PerfCheck(
        name=NAME_REPORT, value=value, unit="мс", verdict=verdict,
        hint=_hint(verdict, "Отчёты открываются долго. Помогут «Сжать базу» и "
                            "«Обновить статистику» на этом же экране."),
        detail=f"чеков за период: {summary.orders_count}",
    )


def _write_check(root: Path, *, quick: bool) -> PerfCheck:
    rows = WRITE_ROWS_QUICK if quick else WRITE_ROWS
    value = round(_measure_write_ms(root, rows), 1)
    verdict = verdict_for(value, ok=WRITE_OK_MS, warn=WRITE_WARN_MS)
    return PerfCheck(
        name=NAME_WRITE, value=value, unit="мс", verdict=verdict,
        hint=_hint(verdict, "Запись идёт медленно — обычно это антивирус, проверяющий "
                            "каждый файл, или заканчивающееся место на диске."),
        detail=f"{rows} строк одной транзакцией, во временной базе",
    )


def _measure_write_ms(root: Path, rows: int) -> float:
    """Вставки в свою временную базу рядом с боевой — pos.db при этом не открывается."""
    path = _temp_path(root, ".db")
    try:
        conn = sqlite3.connect(path, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            # FULL, а не NORMAL: без fsync замерялась бы скорость кэша Windows,
            # а касса теряла бы чеки при отключении света.
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute(
                "CREATE TABLE bench (id INTEGER PRIMARY KEY, name TEXT, "
                "amount INTEGER, at TEXT)"
            )
            payload = [(f"Позиция {i}", i * 100, "2026-01-01T00:00:00+00:00") for i in range(rows)]
            started = time.perf_counter()
            conn.execute("BEGIN")
            conn.executemany("INSERT INTO bench (name, amount, at) VALUES (?, ?, ?)", payload)
            conn.commit()
            return (time.perf_counter() - started) * 1000
        finally:
            conn.close()
    finally:
        _remove_db_files(path)


def _disk_check(root: Path, *, quick: bool) -> PerfCheck:
    size_mb = DISK_MB_QUICK if quick else DISK_MB
    write_mbps, read_mbps = _measure_disk_mbps(root, size_mb)
    # Берём худшую из двух: чтение почти всегда попадает в кэш Windows и само по
    # себе показало бы гигабайты в секунду даже на умирающем диске.
    value = round(min(write_mbps, read_mbps), 1)
    verdict = verdict_for(value, ok=DISK_OK_MBPS, warn=DISK_WARN_MBPS, higher_is_better=True)
    return PerfCheck(
        name=NAME_DISK, value=value, unit="МБ/с", verdict=verdict,
        hint=_hint(verdict, "Диск медленный. Если касса стоит на HDD или флешке, "
                            "пауза будет на каждом чеке — перенесите на SSD."),
        detail=f"{size_mb} МБ: запись {write_mbps:.0f}, чтение {read_mbps:.0f} МБ/с",
    )


def _measure_disk_mbps(root: Path, size_mb: int) -> tuple[float, float]:
    chunk = b"\xa5" * (1024 * 1024)
    path = _temp_path(root, ".bin")
    try:
        started = time.perf_counter()
        with open(path, "wb") as f:
            for _ in range(size_mb):
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        write_s = max(time.perf_counter() - started, 1e-6)

        started = time.perf_counter()
        with open(path, "rb") as f:
            while f.read(1024 * 1024):
                pass
        read_s = max(time.perf_counter() - started, 1e-6)
    finally:
        path.unlink(missing_ok=True)
    return size_mb / write_s, size_mb / read_s


def _free_space_check(root: Path) -> PerfCheck:
    usage = shutil.disk_usage(root)
    value = round(usage.free / 1024 ** 3, 1)
    verdict = verdict_for(value, ok=FREE_SPACE_OK_GB, warn=FREE_SPACE_WARN_GB,
                          higher_is_better=True)
    return PerfCheck(
        name=NAME_FREE_SPACE, value=value, unit="ГБ", verdict=verdict,
        hint=_hint(verdict, "Места почти не осталось: без него база перестанет принимать "
                            "чеки. Удалите старые копии и архивы журнала."),
        detail=f"из {usage.total / 1024 ** 3:.0f} ГБ",
    )


def _wal_check(engine: Engine, root: Path) -> PerfCheck:
    db_path = _database_path(engine, root)
    db_bytes = db_path.stat().st_size if db_path is not None and db_path.exists() else 0
    wal_path = Path(f"{db_path}-wal") if db_path is not None else None
    wal_bytes = wal_path.stat().st_size if wal_path is not None and wal_path.exists() else 0

    value = round(wal_bytes / 1024 ** 2, 1)
    overgrown = value > WAL_BIG_MB and wal_bytes > db_bytes * WAL_BIG_RATIO
    verdict = "warn" if overgrown else "ok"
    return PerfCheck(
        name=NAME_WAL, value=value, unit="МБ", verdict=verdict,
        hint=_hint(verdict, "Журнал сильно больше самой базы — сделайте контрольную "
                            "точку WAL на этом экране, чтение ускорится."),
        detail=f"база {_ru(db_bytes / 1024 ** 2)} МБ",
    )


def _load_checks() -> list[PerfCheck]:
    """Процессор и память — только если их есть чем измерить.

    Прочерк вместо числа владелец читает как поломку, поэтому при отсутствии
    psutil строки в отчёте просто не будет.
    """
    res = _resources()
    if res is None:
        return []
    checks: list[PerfCheck] = []
    if res.cpu_percent is not None:
        value = round(float(res.cpu_percent), 1)
        verdict = verdict_for(value, ok=CPU_OK_PCT, warn=CPU_WARN_PCT)
        checks.append(PerfCheck(
            name=NAME_CPU, value=value, unit="%", verdict=verdict,
            hint=_hint(verdict, "Процессор занят посторонней работой — обновлением Windows "
                                "или антивирусом. Касса будет отвечать с задержкой."),
        ))
    if res.ram_used_percent is not None:
        value = round(float(res.ram_used_percent), 1)
        verdict = verdict_for(value, ok=RAM_OK_PCT, warn=RAM_WARN_PCT)
        process_mb = getattr(res, "ram_process_mb", None)
        checks.append(PerfCheck(
            name=NAME_RAM, value=value, unit="%", verdict=verdict,
            hint=_hint(verdict, "Память почти занята: Windows начнёт выгружать её на диск, "
                                "и касса станет тормозить. Закройте лишние программы."),
            detail=f"касса занимает {process_mb:.0f} МБ" if process_mb is not None else "",
        ))
    return checks


def _resources():
    """Сведения о железе берём у экрана «Сервер»; их отсутствие — не повод ронять отчёт."""
    try:
        from app.services.system_service import resources

        return resources()
    except Exception:  # noqa: BLE001 — замеры базы и диска важнее пары строк про железо
        return None


def _database_path(engine: Engine, root: Path) -> Path | None:
    """Файл боевой базы. None — база в памяти (тесты) или не SQLite."""
    if engine.dialect.name != "sqlite":
        return None
    name = engine.url.database
    if not name or name == ":memory:":
        return None
    path = Path(name)
    return path if path.is_absolute() else root / path


def _temp_path(root: Path, suffix: str) -> Path:
    """Файл замера создаётся рядом с базой: на другом диске цифры были бы не про кассу."""
    fd, name = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=suffix, dir=root)
    os.close(fd)
    return Path(name)


def _remove_db_files(path: Path) -> None:
    """Вместе с базой уходят её -wal и -shm, иначе в каталоге копится мусор."""
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)
