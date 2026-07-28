"""Данные для переработанного экрана отчётов: разбивка по дням, часам и чекам."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (Category, Order, OrderItem, Payment, Product, Refund,
                        Shift, User)
from app.services import reporting_service as rs

# Алматы = UTC+5. 03:00 UTC — это 08:00 того же дня по местному,
# а 20:00 UTC — уже 01:00 СЛЕДУЮЩЕГО дня: на этом ловятся ошибки группировки.
UTC = timezone.utc


def _db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rep.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed(Sm):
    with Sm() as s:
        cashier = User(telegram_id=1, name="Айгуль", role="cashier", is_active=True)
        cat = Category(name="Кофе")
        s.add_all([cashier, cat]); s.flush()
        prod = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=110000)
        s.add(prod); s.flush()
        shift = Shift(cashier_id=cashier.id, opened_at=datetime(2026, 7, 20, 3, 0, tzinfo=UTC),
                      status="closed", opening_cash_tiyn=500000)
        s.add(shift); s.flush()

        def order(num, when, total, cogs, qty, method):
            o = Order(shift_id=shift.id, number=num, status="paid", subtotal_tiyn=total,
                      total_tiyn=total, cost_tiyn=cogs, created_at=when)
            s.add(o); s.flush()
            s.add(OrderItem(order_id=o.id, product_id=prod.id, name="Латте",
                            unit_price_tiyn=total // qty, qty=qty,
                            line_total_tiyn=total, unit_cost_tiyn=cogs // qty))
            s.add(Payment(order_id=o.id, method=method, amount_tiyn=total, created_at=when))
            return o

        # 20 июля по Алматы: 08:00 и 09:30 местного
        order(1, datetime(2026, 7, 20, 3, 0, tzinfo=UTC), 110000, 40000, 1, "cash")
        order(2, datetime(2026, 7, 20, 4, 30, tzinfo=UTC), 220000, 80000, 2, "kaspi_qr")
        # 21 июля по Алматы: 20:00 UTC 20-го = 01:00 21-го местного
        o3 = order(3, datetime(2026, 7, 20, 20, 0, tzinfo=UTC), 110000, 40000, 1, "cash")
        s.add(Refund(order_id=o3.id, amount_tiyn=110000, reason="брак",
                     cashier_id=cashier.id, created_at=datetime(2026, 7, 20, 20, 30, tzinfo=UTC)))
        s.commit()
    return Sm


def _period(a: date, b: date) -> rs.Period:
    return rs.period_from_dates(a, b)


def test_revenue_by_day_groups_by_almaty_not_utc(tmp_path):
    """Чек в 20:00 UTC относится к следующему дню по Алматы (01:00).
    Группировка по UTC отнесла бы его к 20-му и переврала выручку обоих дней."""
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        rows = rs.revenue_by_day(s, _period(date(2026, 7, 20), date(2026, 7, 21)))
    by_day = {r.day: r for r in rows}
    assert by_day[date(2026, 7, 20)].revenue_tiyn == 330000   # 1100 + 2200
    assert by_day[date(2026, 7, 21)].revenue_tiyn == 110000   # чек из 20:00 UTC
    assert by_day[date(2026, 7, 21)].refunds_tiyn == 110000


def test_revenue_by_day_fills_days_without_sales(tmp_path):
    """Пустой день обязан быть в списке нулём: иначе на графике
    исчезнет столбец и неделя визуально сожмётся."""
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        rows = rs.revenue_by_day(s, _period(date(2026, 7, 19), date(2026, 7, 21)))
    assert [r.day for r in rows] == [date(2026, 7, 19), date(2026, 7, 20), date(2026, 7, 21)]
    assert rows[0].revenue_tiyn == 0 and rows[0].orders_count == 0


def test_revenue_by_day_counts_orders_and_items(tmp_path):
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        rows = {r.day: r for r in rs.revenue_by_day(s, _period(date(2026, 7, 20), date(2026, 7, 20)))}
    assert rows[date(2026, 7, 20)].orders_count == 2
    assert rows[date(2026, 7, 20)].items_count == 3   # 1 + 2


def test_revenue_by_hour_uses_local_hours(tmp_path):
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        hours = rs.revenue_by_hour(s, date(2026, 7, 20))
    by_hour = {h.hour: h for h in hours}
    assert by_hour[8].revenue_tiyn == 110000    # 03:00 UTC = 08:00 Алматы
    assert by_hour[9].revenue_tiyn == 220000    # 04:30 UTC = 09:30 Алматы
    assert by_hour[9].orders_count == 1


def test_revenue_by_hour_covers_whole_day(tmp_path):
    """Все 24 часа, чтобы столбцы графика не прыгали по ширине."""
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        hours = rs.revenue_by_hour(s, date(2026, 7, 20))
    assert [h.hour for h in hours] == list(range(24))


def test_summary_computes_average_check_from_net(tmp_path):
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        sm = rs.summary(s, _period(date(2026, 7, 20), date(2026, 7, 20)))
    assert sm.gross_tiyn == 330000
    assert sm.orders_count == 2
    assert sm.items_count == 3
    assert sm.avg_check_tiyn == 165000     # 330000 / 2


def test_summary_average_check_on_empty_period_is_zero(tmp_path):
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        sm = rs.summary(s, _period(date(2026, 1, 1), date(2026, 1, 2)))
    assert sm.orders_count == 0
    assert sm.avg_check_tiyn == 0
    assert sm.margin_pct == 0.0


def test_previous_period_is_same_length_immediately_before(tmp_path):
    """Неделя сравнивается с предыдущей неделей той же длины,
    иначе «+40% к прошлому периоду» ничего не значит."""
    p = _period(date(2026, 7, 20), date(2026, 7, 26))   # 7 дней
    prev = rs.previous_period(p)
    assert prev.end == p.start
    assert (p.end - p.start) == (prev.end - prev.start)


def test_day_receipts_include_lines_and_method(tmp_path):
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        receipts = rs.day_receipts(s, date(2026, 7, 20))
    assert [r.number for r in receipts] == [1, 2]
    first = receipts[0]
    assert first.total_tiyn == 110000
    assert first.method == "cash"
    assert [(l.name, l.qty) for l in first.lines] == [("Латте", 1)]


def test_day_receipts_expose_refund(tmp_path):
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        receipts = rs.day_receipts(s, date(2026, 7, 21))
    assert len(receipts) == 1
    assert receipts[0].refunded_tiyn == 110000
    assert receipts[0].refund_reason == "брак"


def test_day_receipts_sorted_by_time(tmp_path):
    Sm = _seed(_db(tmp_path))
    with Sm() as s:
        receipts = rs.day_receipts(s, date(2026, 7, 20))
    assert receipts == sorted(receipts, key=lambda r: r.at)
