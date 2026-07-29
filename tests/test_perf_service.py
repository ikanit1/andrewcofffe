import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.db import Base, enable_sqlite_fk
from app.models import Order, OrderItem, Payment, Shift, User
from app.services import perf_service

BASE_ORDER = (
    perf_service.NAME_DB_PING,
    perf_service.NAME_REPORT,
    perf_service.NAME_WRITE,
    perf_service.NAME_DISK,
    perf_service.NAME_FREE_SPACE,
    perf_service.NAME_WAL,
)


class _Resources:
    """Заглушка вместо system_service.resources(): замер железа тестам не нужен."""

    def __init__(self, cpu=None, ram=None, process_mb=None):
        self.cpu_percent = cpu
        self.ram_used_percent = ram
        self.ram_process_mb = process_mb


@pytest.fixture(autouse=True)
def _no_hardware_metrics(monkeypatch):
    """По умолчанию строк про процессор и память нет — иначе загруженный CI красит отчёт."""
    monkeypatch.setattr(perf_service, "_resources", lambda: _Resources())


@pytest.fixture()
def db(tmp_path):
    """База файлом, как боевая: замер записи создаёт временные файлы рядом с ней."""
    engine = create_engine(f"sqlite:///{tmp_path / 'pos.db'}")
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        user = User(telegram_id=1, name="Кассир", role="cashier", is_active=True)
        s.add(user)
        s.flush()
        shift = Shift(cashier_id=user.id, status="open", opening_cash_tiyn=0)
        s.add(shift)
        s.flush()
        for number in range(1, 4):
            order = Order(shift_id=shift.id, number=number, subtotal_tiyn=1500,
                          total_tiyn=1500, cost_tiyn=500)
            s.add(order)
            s.flush()
            s.add(OrderItem(order_id=order.id, name="Латте", unit_price_tiyn=1500,
                            qty=1, line_total_tiyn=1500))
            s.add(Payment(order_id=order.id, method="cash", amount_tiyn=1500))
        s.commit()
    yield engine
    engine.dispose()


def _counts(engine):
    with Session(engine) as s:
        return {
            "orders": s.scalar(select(func.count(Order.id))),
            "order_items": s.scalar(select(func.count(OrderItem.id))),
            "payments": s.scalar(select(func.count(Payment.id))),
        }


def _tables(engine):
    with engine.connect() as conn:
        return sorted(
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        )


def _by_name(report):
    return {c.name: c for c in report.checks}


def test_report_contains_all_checks_in_stable_order(db, tmp_path):
    report = perf_service.run_performance_check(engine=db, root=tmp_path)

    assert tuple(c.name for c in report.checks) == BASE_ORDER
    assert all(c.unit for c in report.checks)
    assert all(c.verdict in ("ok", "warn", "bad") for c in report.checks)


def test_measurement_does_not_touch_working_tables(db, tmp_path):
    """Главное требование: бенчмарк не имеет права изменить боевые данные.

    Замер записи идёт в отдельную временную базу, поэтому ни строк, ни таблиц
    в рабочей базе не прибавляется — даже служебной bench.
    """
    before, tables_before = _counts(db), _tables(db)

    perf_service.run_performance_check(engine=db, root=tmp_path)

    assert _counts(db) == before
    assert _tables(db) == tables_before
    assert "bench" not in tables_before


def test_temp_files_are_removed_after_run(db, tmp_path):
    perf_service.run_performance_check(engine=db, root=tmp_path)

    assert list(tmp_path.glob(f"{perf_service.TEMP_PREFIX}*")) == []


def test_temp_files_are_removed_even_when_measurement_fails(db, tmp_path, monkeypatch):
    """Файл замера создаётся до записи: без finally он остался бы после любой ошибки."""
    real_connect = perf_service.sqlite3.connect

    def boom(database, *args, **kwargs):
        # Роняем только подключение к временной базе — боевую трогать незачем.
        if perf_service.TEMP_PREFIX in str(database):
            raise OSError("диск отвалился")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(perf_service.sqlite3, "connect", boom)
    report = perf_service.run_performance_check(engine=db, root=tmp_path, quick=True)

    assert list(tmp_path.glob(f"{perf_service.TEMP_PREFIX}*")) == []
    write = _by_name(report)[perf_service.NAME_WRITE]
    assert write.verdict == "bad"
    assert "диск отвалился" in write.detail
    assert report.verdict == "bad"  # упавшая проверка не теряется в общем вердикте


def test_quick_mode_measures_smaller_volumes(db, tmp_path):
    """«Быстрее» проверяем объёмами, а не секундомером: на занятом CI время скачет,
    и тест начал бы падать через раз, ничего не сообщая о самом коде."""
    assert perf_service.PING_QUERIES_QUICK < perf_service.PING_QUERIES
    assert perf_service.WRITE_ROWS_QUICK < perf_service.WRITE_ROWS
    assert perf_service.DISK_MB_QUICK < perf_service.DISK_MB

    quick = _by_name(perf_service.run_performance_check(engine=db, root=tmp_path, quick=True))
    full = _by_name(perf_service.run_performance_check(engine=db, root=tmp_path))

    assert f"{perf_service.PING_QUERIES_QUICK} запросов" in quick[perf_service.NAME_DB_PING].detail
    assert f"{perf_service.PING_QUERIES} запросов" in full[perf_service.NAME_DB_PING].detail
    assert f"{perf_service.WRITE_ROWS_QUICK} строк" in quick[perf_service.NAME_WRITE].detail
    assert f"{perf_service.WRITE_ROWS} строк" in full[perf_service.NAME_WRITE].detail
    assert f"{perf_service.DISK_MB_QUICK} МБ" in quick[perf_service.NAME_DISK].detail
    assert f"{perf_service.DISK_MB} МБ" in full[perf_service.NAME_DISK].detail


def test_report_verdict_is_the_worst_check(db, tmp_path):
    report = perf_service.run_performance_check(engine=db, root=tmp_path, quick=True)

    assert report.verdict == perf_service.worst_verdict(c.verdict for c in report.checks)


def test_took_ms_and_time_are_filled(db, tmp_path):
    now = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)
    report = perf_service.run_performance_check(engine=db, root=tmp_path, now=now, quick=True)

    assert report.at == now
    assert report.at.tzinfo is not None
    assert report.took_ms >= 0


def test_hint_is_empty_while_everything_is_fine(db, tmp_path):
    """Подсказка на зелёной строке — шум: владелец перестаёт читать подсказки вообще."""
    report = perf_service.run_performance_check(engine=db, root=tmp_path, quick=True)

    assert all(c.hint == "" for c in report.checks if c.verdict == "ok")
    assert all(c.hint for c in report.checks if c.verdict != "ok")


def test_report_check_runs_real_report_queries(db, tmp_path):
    """Замер честный: считает те же чеки, что владелец увидит в отчётах за месяц."""
    report = perf_service.run_performance_check(engine=db, root=tmp_path, quick=True)

    assert "3" in _by_name(report)[perf_service.NAME_REPORT].detail


def test_wal_check_warns_only_when_journal_outgrew_database(db, tmp_path):
    check = _by_name(
        perf_service.run_performance_check(engine=db, root=tmp_path, quick=True)
    )[perf_service.NAME_WAL]

    assert check.unit == "МБ"
    assert check.verdict == "ok"  # свежая база, контрольная точка недавно была


def test_hardware_checks_appear_only_when_measurable(db, tmp_path, monkeypatch):
    monkeypatch.setattr(perf_service, "_resources",
                        lambda: _Resources(cpu=95.0, ram=99.0, process_mb=120.0))
    report = perf_service.run_performance_check(engine=db, root=tmp_path, quick=True)
    names = [c.name for c in report.checks]

    assert names[-2:] == [perf_service.NAME_CPU, perf_service.NAME_RAM]
    assert report.verdict == "bad"
    assert "120" in _by_name(report)[perf_service.NAME_RAM].detail


def test_hardware_checks_are_skipped_without_psutil(db, tmp_path, monkeypatch):
    """Строки «—» быть не должно: прочерк читается как поломка, хотя мерять нечем."""
    monkeypatch.setattr(perf_service, "_resources", lambda: None)
    report = perf_service.run_performance_check(engine=db, root=tmp_path, quick=True)

    assert tuple(c.name for c in report.checks) == BASE_ORDER


def test_async_wrapper_returns_the_same_report(db, tmp_path):
    report = asyncio.run(
        perf_service.run_performance_check_async(engine=db, root=tmp_path, quick=True))

    assert tuple(c.name for c in report.checks) == BASE_ORDER
    assert list(tmp_path.glob(f"{perf_service.TEMP_PREFIX}*")) == []


@pytest.mark.parametrize(
    "value,expected",
    [(0.5, "ok"), (4.99, "ok"), (5.0, "warn"), (24.9, "warn"), (25.0, "bad"), (900.0, "bad")],
)
def test_verdict_for_lower_is_better(value, expected):
    assert perf_service.verdict_for(
        value, ok=perf_service.DB_PING_OK_MS, warn=perf_service.DB_PING_WARN_MS) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(500.0, "ok"), (50.1, "ok"), (50.0, "warn"), (15.1, "warn"), (15.0, "bad"), (0.0, "bad")],
)
def test_verdict_for_higher_is_better(value, expected):
    assert perf_service.verdict_for(
        value, ok=perf_service.DISK_OK_MBPS, warn=perf_service.DISK_WARN_MBPS,
        higher_is_better=True) == expected


@pytest.mark.parametrize(
    "verdicts,expected",
    [
        ((), "ok"),
        (("ok", "ok"), "ok"),
        (("ok", "warn", "ok"), "warn"),
        (("warn", "bad", "ok"), "bad"),
        (("bad", "bad"), "bad"),
    ],
)
def test_worst_verdict_wins(verdicts, expected):
    assert perf_service.worst_verdict(verdicts) == expected
