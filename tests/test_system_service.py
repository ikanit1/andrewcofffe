import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base, enable_sqlite_fk
from app.models import (Category, Order, OrderItem, Payment,
                        Product, Shift, User)
from app.services import runtime
from app.services import system_service as ss
from app.services.runtime import TaskState

FIRST_ORDER_AT = datetime(2026, 7, 20, 5, 30, tzinfo=timezone.utc)
LAST_ORDER_AT = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


# --- база --------------------------------------------------------------------

def _seed(session: Session) -> None:
    session.add_all([
        Category(id=1, name="Кофе"),
    ])
    session.add(Product(id=1, name="Латте", category_id=1, kind="prepared",
                        price_tiyn=150000))
    user = User(telegram_id=1, name="Кассир", role="cashier")
    session.add(user)
    session.flush()
    shift = Shift(cashier_id=user.id)
    session.add(shift)
    session.flush()
    for number, at in enumerate((FIRST_ORDER_AT, LAST_ORDER_AT), start=1):
        order = Order(shift_id=shift.id, number=number, subtotal_tiyn=150000,
                      total_tiyn=150000, created_at=at)
        session.add(order)
        session.flush()
        session.add(OrderItem(order_id=order.id, product_id=1, name="Латте",
                              unit_price_tiyn=150000, qty=1, line_total_tiyn=150000))
        session.add(Payment(order_id=order.id, method="cash", amount_tiyn=150000))
    session.commit()


@pytest.fixture()
def file_session(tmp_path):
    """База файлом, а не в памяти: без файла нечего мерить в размерах и WAL."""
    engine = create_engine(f"sqlite:///{tmp_path / 'pos.db'}")
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        _seed(s)
        yield s


def test_database_info_measures_the_real_file(file_session, tmp_path):
    info = ss.database_info(file_session)

    assert info.path == str(tmp_path / "pos.db")
    assert info.size_bytes > 0
    assert info.journal_mode == "wal"        # enable_sqlite_fk включает WAL
    assert info.wal_bytes > 0                # писали в WAL, файл рядом
    assert info.page_size > 0 and info.page_count > 0
    assert info.wasted_bytes == info.freelist_pages * info.page_size


def test_database_info_counts_rows_by_human_names(file_session):
    counts = {t.name: t.rows for t in ss.database_info(file_session).tables}

    assert counts["Чеки"] == 2
    assert counts["Позиции в чеках"] == 2
    assert counts["Оплаты"] == 2
    assert counts["Возвраты"] == 0
    assert counts["Товары"] == 1
    assert counts["Движения склада"] == 0
    assert counts["Смены"] == 1
    assert counts["Очередь уведомлений"] == 0


def test_database_info_reports_order_range_as_aware_utc(file_session):
    info = ss.database_info(file_session)

    assert info.oldest_order_at == FIRST_ORDER_AT
    assert info.newest_order_at == LAST_ORDER_AT
    assert info.oldest_order_at.utcoffset() == timedelta(0)


def test_database_info_skips_tables_absent_in_the_file(tmp_path):
    """Старая боевая база могла быть создана до появления части таблиц."""
    engine = create_engine(f"sqlite:///{tmp_path / 'pos.db'}")
    Base.metadata.create_all(engine, tables=[Order.__table__])

    with Session(engine) as s:
        info = ss.database_info(s)

    assert [t.name for t in info.tables] == ["Чеки"]


def test_database_info_survives_in_memory_database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as s:
        info = ss.database_info(s)

    assert (info.size_bytes, info.wal_bytes, info.shm_bytes) == (0, 0, 0)
    assert info.page_size > 0                # PRAGMA спрошен у самой сессии
    assert {t.name for t in info.tables} >= {"Чеки", "Смены"}


# --- бэкапы ------------------------------------------------------------------

def _put_backup(directory: Path, name: str, *, size: int, age_hours: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    f = directory / name
    f.write_bytes(b"x" * size)
    when = time.time() - age_hours * 3600
    os.utime(f, (when, when))
    return f


def test_backups_info_takes_the_freshest_copy(tmp_path):
    _put_backup(tmp_path, "pos-20260728-030000.db", size=100, age_hours=30)
    _put_backup(tmp_path, "pos-20260729-030000.db", size=200, age_hours=2)

    info = ss.backups_info(backups_dir=tmp_path, now=datetime.now(timezone.utc))

    assert info.count == 2
    assert info.total_bytes == 300
    assert info.latest_name == "pos-20260729-030000.db"
    assert info.age_hours == pytest.approx(2, abs=0.1)
    assert info.stale is False
    assert info.latest_at.utcoffset() == timedelta(0)


def test_backups_info_marks_old_copies_stale(tmp_path):
    _put_backup(tmp_path, "pos-20260726-030000.db", size=10, age_hours=72)

    info = ss.backups_info(backups_dir=tmp_path, now=datetime.now(timezone.utc))

    assert info.stale is True
    assert info.age_hours == pytest.approx(72, abs=0.1)


def test_backups_info_without_any_copies_is_stale(tmp_path):
    info = ss.backups_info(backups_dir=tmp_path / "нет-такой-папки")

    assert (info.count, info.total_bytes, info.latest_name) == (0, 0, "")
    assert info.latest_at is None and info.age_hours is None
    assert info.stale is True


def test_backups_info_ignores_foreign_files(tmp_path):
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "заметки.txt").write_text("не бэкап", encoding="utf-8")
    (tmp_path / "dump.db").write_bytes(b"x")

    assert ss.backups_info(backups_dir=tmp_path).count == 0


# --- журнал ------------------------------------------------------------------

def _write_log(root: Path, content: str | bytes) -> Path:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "server.log"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def test_log_tail_returns_the_last_lines(tmp_path):
    _write_log(tmp_path, "\n".join(f"строка {i}" for i in range(500)))

    info = ss.log_tail(root=tmp_path, limit=10)

    assert len(info.lines) == 10
    assert info.lines[-1] == "строка 499"
    assert info.size_bytes > 0


def test_log_tail_reads_only_the_tail_of_a_huge_file(tmp_path):
    """Журнал не ротируется и растёт месяцами — целиком его читать нельзя."""
    big = "\n".join(f"строка {i}" for i in range(200_000))
    path = _write_log(tmp_path, big)

    info = ss.log_tail(root=tmp_path, limit=5)

    assert path.stat().st_size > ss._TAIL_BYTES
    assert info.size_bytes == path.stat().st_size
    assert info.lines[-1] == "строка 199999"


def test_log_tail_survives_a_letter_cut_in_half(tmp_path):
    """Точка чтения почти всегда приходится на середину кириллической буквы."""
    body = "\n".join(f"строка {i}" for i in range(50))
    data = ("я" * ss._TAIL_BYTES + "\n" + body).encode("utf-8")
    if (len(data) - ss._TAIL_BYTES) % 2 == 0:
        data += b"!"  # хвост обязан начаться с середины двухбайтовой буквы
    _write_log(tmp_path, data)

    info = ss.log_tail(root=tmp_path, limit=100)

    assert info.lines[0] == "строка 0"       # обрезанный огрызок отброшен
    assert info.lines[-1].startswith("строка 49")


def test_log_tail_can_show_only_errors(tmp_path):
    _write_log(tmp_path, "\n".join([
        "запуск сервера",
        "ERROR не отдал страницу",
        "обычная строка",
        "Traceback (most recent call last):",
        "не удалось отправить бэкап",
        "смена закрыта",
    ]))

    info = ss.log_tail(root=tmp_path, errors_only=True)

    assert info.error_lines == 3
    assert len(info.lines) == 3
    assert all("обычная" not in line for line in info.lines)


def test_log_tail_counts_errors_even_when_showing_everything(tmp_path):
    _write_log(tmp_path, "тихо\nCRITICAL сервер упал\nтихо")

    info = ss.log_tail(root=tmp_path)

    assert info.error_lines == 1
    assert len(info.lines) == 3


def test_log_tail_reports_how_many_lines_it_scanned(tmp_path):
    """Ошибки считаются по всему прочитанному хвосту, а на экран идёт только limit.

    Без числа просмотренных строк «ошибок: 40» рядом с десятью показанными
    читается как «почти всё сломано», хотя сорок ошибок пришлись на сотню строк.
    """
    _write_log(tmp_path, "\n".join(
        ["ERROR сбой" if i % 10 == 0 else f"строка {i}" for i in range(100)]))

    info = ss.log_tail(root=tmp_path, limit=10)

    assert info.scanned_lines == 100
    assert info.error_lines == 10
    assert len(info.lines) == 10


def test_log_tail_without_a_file_is_empty(tmp_path):
    info = ss.log_tail(root=tmp_path)

    assert info.lines == [] and info.size_bytes == 0 and info.error_lines == 0
    assert info.path.endswith("server.log")


# --- ресурсы -----------------------------------------------------------------

def test_resources_reports_a_known_source():
    res = ss.resources()

    assert res.source in {"psutil", "stdlib"}
    assert res.disk_total_gb is not None and res.disk_total_gb > 0
    assert res.disk_free_gb is not None


def test_resources_works_without_psutil(monkeypatch):
    """psutil — необязательная зависимость: без неё экран всё равно нужен."""
    monkeypatch.setattr(ss, "psutil", None)

    res = ss.resources()

    assert res.source == "stdlib"
    assert res.cpu_percent is None           # честного мгновенного замера нет
    assert res.disk_free_gb is not None
    if sys.platform == "win32":
        assert res.ram_total_mb and res.ram_total_mb > 0
        assert res.ram_process_mb and res.ram_process_mb > 0


def test_resources_does_not_raise_on_a_missing_root(monkeypatch, tmp_path):
    monkeypatch.setattr(ss, "psutil", None)

    res = ss.resources(root=tmp_path / "нет-такой-папки")

    assert res.disk_free_gb is None and res.disk_total_gb is None


# --- паспорт процесса --------------------------------------------------------

@pytest.fixture()
def clean_runtime():
    runtime.reset()
    yield runtime
    runtime.reset()


def test_app_info_describes_this_process(clean_runtime, monkeypatch, tmp_path):
    from app.config import settings
    from app.services import updates

    start = datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc)
    clean_runtime.mark_started(start)
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")

    info = ss.app_info(root=tmp_path, now=start + timedelta(hours=3))

    assert info.pid == os.getpid()
    assert info.python == sys.version.split()[0]
    assert info.platform
    assert info.supervised is True
    assert info.project_root == str(tmp_path)
    assert info.started_at == start
    assert info.uptime_seconds == 3 * 3600
    assert info.version == updates.local_version()
    assert info.public_url == settings.public_url


def test_app_info_without_supervisor(clean_runtime, monkeypatch):
    monkeypatch.delenv("COFFEEPOS_SUPERVISED", raising=False)

    info = ss.app_info()

    assert info.supervised is False
    assert info.started_at is None and info.uptime_seconds is None


# --- предупреждения ----------------------------------------------------------

def _app(root: Path | str = "C:/coffee") -> ss.AppInfo:
    return ss.AppInfo(version="2026.07.29", python="3.14.6", platform="Windows-10",
                      pid=1, supervised=True, project_root=str(root),
                      started_at=None, uptime_seconds=None,
                      public_url="http://localhost:8080")


def _res(**kw) -> ss.Resources:
    base = dict(cpu_percent=5.0, ram_process_mb=120.0, ram_total_mb=8000.0,
                ram_used_percent=50.0, disk_free_gb=100.0, disk_total_gb=500.0,
                disk_used_percent=80.0, source="psutil")
    return ss.Resources(**{**base, **kw})


def _db(**kw) -> ss.DatabaseInfo:
    base = dict(path="pos.db", size_bytes=224 * 1024, wal_bytes=0, shm_bytes=0,
                journal_mode="wal", page_size=4096, page_count=56,
                freelist_pages=0, wasted_bytes=0)
    return ss.DatabaseInfo(**{**base, **kw})


def _backups(**kw) -> ss.BackupsInfo:
    base = dict(count=3, total_bytes=3 * 1024 * 1024, latest_name="pos-20260729.db",
                latest_at=datetime(2026, 7, 29, 3, tzinfo=timezone.utc),
                age_hours=2.0, stale=False)
    return ss.BackupsInfo(**{**base, **kw})


def _issues(*, res=None, db=None, backups=None, tasks=(), log_bytes=0) -> list[ss.Issue]:
    return ss.issues(_app(), res or _res(), db or _db(), backups or _backups(),
                     list(tasks),
                     log=ss.LogInfo(path="server.log", size_bytes=log_bytes))


def test_no_issues_on_a_healthy_server():
    assert _issues() == []
    assert ss.overall_verdict([]) == "ok"


def test_almost_full_disk_is_bad():
    (issue,) = _issues(res=_res(disk_free_gb=0.4))

    assert issue.level == "bad"
    assert "0.4" in issue.text and issue.hint


def test_low_disk_is_only_a_warning():
    (issue,) = _issues(res=_res(disk_free_gb=3.0))

    assert issue.level == "warn"


def test_five_gigabytes_free_is_still_fine():
    assert _issues(res=_res(disk_free_gb=5.0)) == []


def test_unknown_disk_size_is_not_reported():
    """Не смогли измерить — молчим: выдуманное предупреждение хуже пустоты."""
    assert _issues(res=_res(disk_free_gb=None)) == []


def test_wal_much_bigger_than_the_base_asks_for_a_checkpoint():
    # Реальный случай: база 224 КБ, а pos.db-wal разросся до 4 МБ и продолжал расти.
    (issue,) = _issues(db=_db(size_bytes=224 * 1024, wal_bytes=12 * 1024 * 1024))

    assert issue.level == "warn"
    assert "WAL" in issue.hint


def test_big_wal_next_to_a_big_base_is_normal():
    assert _issues(db=_db(size_bytes=200 * 1024 * 1024,
                          wal_bytes=12 * 1024 * 1024)) == []


def test_small_wal_is_never_reported():
    assert _issues(db=_db(size_bytes=10 * 1024, wal_bytes=4 * 1024 * 1024)) == []


def test_freelist_over_a_fifth_of_the_file_asks_for_vacuum():
    (issue,) = _issues(db=_db(size_bytes=20 * 1024 * 1024,
                              page_size=4096, freelist_pages=1536,
                              wasted_bytes=6 * 1024 * 1024))

    assert issue.level == "warn"
    assert "VACUUM" in issue.hint


def test_small_freelist_share_is_not_worth_a_vacuum():
    assert _issues(db=_db(size_bytes=100 * 1024 * 1024,
                          wasted_bytes=6 * 1024 * 1024)) == []


def test_freelist_under_five_megabytes_is_not_worth_a_vacuum():
    assert _issues(db=_db(size_bytes=2 * 1024 * 1024,
                          wasted_bytes=1024 * 1024)) == []


def test_stale_backups_are_a_warning():
    (issue,) = _issues(backups=_backups(age_hours=60.0, stale=True))

    assert issue.level == "warn"
    assert "коп" in issue.text.lower()


def test_no_backups_at_all_is_bad():
    (issue,) = _issues(backups=_backups(count=0, total_bytes=0, latest_name="",
                                        latest_at=None, age_hours=None, stale=True))

    assert issue.level == "bad"


def test_crashed_background_task_is_bad_and_names_the_error():
    task = TaskState(name="Бэкапы", enabled=True, running=False,
                     error="OSError('диск полон')")

    (issue,) = _issues(tasks=[task])

    assert issue.level == "bad"
    assert "Бэкапы" in issue.text and "диск полон" in issue.text


def test_healthy_and_disabled_tasks_are_not_issues():
    tasks = [
        TaskState(name="Бэкапы", enabled=True, running=True, error=""),
        TaskState(name="Telegram-бот", enabled=False, running=False, error=""),
    ]

    assert _issues(tasks=tasks) == []


def test_ram_over_ninety_percent_is_a_warning():
    (issue,) = _issues(res=_res(ram_used_percent=95.0))

    assert issue.level == "warn"
    assert "95" in issue.text


def test_ram_exactly_at_the_threshold_is_still_fine():
    assert _issues(res=_res(ram_used_percent=90.0)) == []


def test_huge_log_asks_to_archive_it():
    (issue,) = _issues(log_bytes=60 * 1024 * 1024)

    assert issue.level == "warn"
    assert "рхивир" in issue.hint


def test_log_size_is_read_from_disk_when_not_given(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "server.log").write_text("тихо", encoding="utf-8")

    assert ss.issues(_app(tmp_path), _res(), _db(), _backups(), []) == []


def test_every_issue_explains_what_to_press():
    found = _issues(res=_res(disk_free_gb=0.2, ram_used_percent=99.0),
                    db=_db(wal_bytes=12 * 1024 * 1024),
                    backups=_backups(count=0, latest_name="", latest_at=None,
                                     age_hours=None, stale=True),
                    tasks=[TaskState("Бэкапы", True, False, "OSError()")],
                    log_bytes=60 * 1024 * 1024)

    assert len(found) == 6
    assert all(i.hint and i.text for i in found)


def test_bad_issues_come_first():
    found = _issues(res=_res(disk_free_gb=0.2, ram_used_percent=99.0))

    assert [i.level for i in found] == ["bad", "warn"]


def test_overall_verdict_picks_the_worst():
    warn = ss.Issue("warn", "т", "п")
    bad = ss.Issue("bad", "т", "п")

    assert ss.overall_verdict([]) == "ok"
    assert ss.overall_verdict([warn]) == "warn"
    assert ss.overall_verdict([warn, bad]) == "bad"
