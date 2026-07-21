from datetime import datetime, timedelta, timezone

from app.models import Ingredient, Order, OrderItem, Shift, User
from app.services import dashboard_service as ds


def _shift(session):
    u = User(telegram_id=1, name="Кассир", role="cashier")
    session.add(u)
    session.flush()
    sh = Shift(cashier_id=u.id, opening_cash_tiyn=0)
    session.add(sh)
    session.commit()
    return sh


def _order(session, shift_id, *, number, created_at, total_tiyn=150000,
           status="paid", items_qty=1, refunded_qty=0):
    order = Order(shift_id=shift_id, number=number, status=status,
                  subtotal_tiyn=total_tiyn, total_tiyn=total_tiyn, created_at=created_at)
    session.add(order)
    session.flush()
    session.add(OrderItem(order_id=order.id, product_id=None, name="Латте",
                          unit_price_tiyn=total_tiyn, qty=items_qty,
                          line_total_tiyn=total_tiyn, refunded_qty=refunded_qty))
    session.commit()
    return order


def test_today_summary_counts_only_today(session):
    sh = _shift(session)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    _order(session, sh.id, number=1, created_at=now, total_tiyn=150000, items_qty=2)
    _order(session, sh.id, number=2, created_at=now - timedelta(hours=25),
           total_tiyn=999999, items_qty=9)  # вчера — не должно попасть в сводку
    summary = ds.today_summary(session, now=now)
    assert summary.revenue_tiyn == 150000
    assert summary.orders_count == 1
    assert summary.items_count == 2


def test_today_summary_excludes_refunded_orders(session):
    sh = _shift(session)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    _order(session, sh.id, number=1, created_at=now, total_tiyn=150000, status="refunded")
    summary = ds.today_summary(session, now=now)
    assert summary.orders_count == 0
    assert summary.revenue_tiyn == 0


def test_today_summary_subtracts_refunded_qty(session):
    sh = _shift(session)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    _order(session, sh.id, number=1, created_at=now, total_tiyn=150000,
           items_qty=3, refunded_qty=1)
    summary = ds.today_summary(session, now=now)
    assert summary.items_count == 2


def test_low_stock_ingredients_lists_only_active_below_threshold(session):
    ok = Ingredient(name="Сахар", unit="г", stock_qty=1000, low_stock_threshold=500)
    low = Ingredient(name="Молоко", unit="мл", stock_qty=100, low_stock_threshold=500)
    inactive_low = Ingredient(name="Старое", unit="шт", stock_qty=0,
                             low_stock_threshold=10, is_active=False)
    session.add_all([ok, low, inactive_low])
    session.commit()
    result = ds.low_stock_ingredients(session)
    assert [i.name for i in result] == ["Молоко"]
