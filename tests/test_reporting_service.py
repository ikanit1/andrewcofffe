from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Category, Order, OrderItem, Payment, Product, Refund, Shift, User,
)
from app.services import reporting_service as rs

ALMATY = ZoneInfo("Asia/Almaty")


def test_period_from_preset_today():
    now = datetime(2026, 7, 22, 10, 0, tzinfo=ALMATY)
    p = rs.period_from_preset("today", now)
    # 22 июля 00:00 Almaty == 21 июля 19:00 UTC (Almaty = UTC+5 с 2024)
    assert p.start == datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc)
    assert p.end == datetime(2026, 7, 22, 19, 0, tzinfo=timezone.utc)


def test_period_from_preset_yesterday():
    now = datetime(2026, 7, 22, 10, 0, tzinfo=ALMATY)
    p = rs.period_from_preset("yesterday", now)
    assert p.start == datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc)
    assert p.end == datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc)


def test_period_from_dates_inclusive_end():
    p = rs.period_from_dates(date(2026, 7, 1), date(2026, 7, 31))
    assert p.start == datetime(2026, 6, 30, 19, 0, tzinfo=timezone.utc)
    # конец — начало 1 августа Almaty (эксклюзивно)
    assert p.end == datetime(2026, 7, 31, 19, 0, tzinfo=timezone.utc)


def _seed(tmp_path):
    """Наполняет временную БД: 1 смена, 2 заказа, оплаты (нал+карта), 1 возврат."""
    engine = create_engine(f"sqlite:///{tmp_path / 'r.db'}")
    Base.metadata.create_all(engine)
    Sm = sessionmaker(bind=engine)
    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    with Sm() as s:
        cashier = User(telegram_id=1, name="Айгуль", role="cashier", is_active=True)
        cat = Category(name="Кофе")
        s.add_all([cashier, cat]); s.flush()
        prod = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=1500)
        s.add(prod); s.flush()
        shift = Shift(cashier_id=cashier.id, opened_at=now, status="open", opening_cash_tiyn=0)
        s.add(shift); s.flush()
        o1 = Order(shift_id=shift.id, number=1, status="paid", subtotal_tiyn=3000,
                   total_tiyn=3000, cost_tiyn=800, created_at=now)
        s.add(o1); s.flush()
        s.add(OrderItem(order_id=o1.id, product_id=prod.id, name="Латте",
                        unit_price_tiyn=1500, qty=2, line_total_tiyn=3000,
                        unit_cost_tiyn=400, refunded_qty=1))
        s.add(Payment(order_id=o1.id, method="cash", amount_tiyn=3000, created_at=now))
        o2 = Order(shift_id=shift.id, number=2, status="paid", subtotal_tiyn=1500,
                   total_tiyn=1500, cost_tiyn=400, created_at=now)
        s.add(o2); s.flush()
        s.add(OrderItem(order_id=o2.id, product_id=prod.id, name="Латте",
                        unit_price_tiyn=1500, qty=1, line_total_tiyn=1500,
                        unit_cost_tiyn=400, refunded_qty=0))
        s.add(Payment(order_id=o2.id, method="card", amount_tiyn=1500, created_at=now))
        s.add(Refund(order_id=o1.id, amount_tiyn=1500, reason="брак",
                     cashier_id=cashier.id, created_at=now))
        s.commit()
    return Sm, now


def test_revenue_by_method(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        r = rs.revenue_by_method(s, p)
    assert r.by_method == {"cash": 3000, "card": 1500}
    assert r.gross_tiyn == 4500
    assert r.refunds_tiyn == 1500
    assert r.net_tiyn == 3000
    assert r.orders_count == 2


def test_top_products_net_qty(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        rows = rs.top_products(s, p)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "Латте"
    assert row.qty_sold == 3
    assert row.qty_refunded == 1
    assert row.qty_net == 2
    assert row.revenue_tiyn == 4500


def test_revenue_by_category(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        rows = rs.revenue_by_category(s, p)
    assert len(rows) == 1
    assert rows[0].category == "Кофе"
    assert rows[0].revenue_tiyn == 4500
    assert rows[0].qty_net == 2


def test_cost_and_margin(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        m = rs.cost_and_margin(s, p)
    assert m.revenue_tiyn == 4500
    assert m.cogs_tiyn == 1200
    assert m.margin_tiyn == 3300
    assert m.margin_pct == 73.3
    assert m.refunds_tiyn == 1500
    assert m.net_revenue_tiyn == 3000


def test_x_report_current_shift(tmp_path):
    Sm, now = _seed(tmp_path)
    with Sm() as s:
        rep = rs.x_report(s)
    assert rep is not None
    assert rep.orders_count == 2
    assert rep.revenue_tiyn == 4500
    assert rep.by_method == {"cash": 3000, "card": 1500}
    assert rep.refunds_tiyn == 1500
    assert rep.cashier_name == "Айгуль"


def test_shifts_and_cashiers(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        rep = rs.shifts_and_cashiers(s, p)
    assert len(rep.shifts) == 1
    sh = rep.shifts[0]
    assert sh.cashier_name == "Айгуль"
    assert sh.orders_count == 2
    assert sh.revenue_tiyn == 4500
    assert sh.margin_tiyn == 3300
    assert len(rep.by_cashier) == 1
    c = rep.by_cashier[0]
    assert c.cashier_name == "Айгуль"
    assert c.shifts_count == 1
    assert c.orders_count == 2
    assert c.revenue_tiyn == 4500
    assert c.margin_tiyn == 3300
