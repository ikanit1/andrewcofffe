from datetime import datetime, timedelta, timezone

from app.models import Category, Ingredient, Order, OrderItem, Product, Refund, Shift, User
from app.services import dashboard_service as ds
from app.services import sales_service as sales
from app.services.pricing import PaymentInput


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


def test_today_summary_subtracts_actual_refund_amount(session):
    sh = _shift(session)
    cat = Category(name="Кофе")
    session.add(cat)
    session.commit()
    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=100000)
    session.add(latte)
    session.commit()

    order = sales.create_sale(
        session, cashier_id=sh.cashier_id,
        lines=[sales.SaleLineInput(product_id=latte.id, qty=2)],
        payments=[PaymentInput("cash", 200000, 200000)],
    )
    item = session.query(OrderItem).filter_by(order_id=order.id).one()
    sales.refund_sale(session, order_id=order.id, cashier_id=sh.cashier_id,
                      reason="одну убрать", item_qty={item.id: 1})

    # order.created_at теряет tzinfo при перечитывании из SQLite после commit
    # (expire_on_commit=True в тестовой фикстуре session) — значение по факту в UTC;
    # to_almaty теперь сам трактует naive datetime как UTC.
    summary = ds.today_summary(session, now=order.created_at)
    assert summary.revenue_tiyn == 100000  # 200000 продано − 100000 реально возвращено
    assert summary.items_count == 1


def test_low_stock_ingredients_lists_only_active_below_threshold(session):
    ok = Ingredient(name="Сахар", unit="г", stock_qty=1000, low_stock_threshold=500)
    low = Ingredient(name="Молоко", unit="мл", stock_qty=100, low_stock_threshold=500)
    inactive_low = Ingredient(name="Старое", unit="шт", stock_qty=0,
                             low_stock_threshold=10, is_active=False)
    session.add_all([ok, low, inactive_low])
    session.commit()
    result = ds.low_stock_ingredients(session)
    assert [i.name for i in result] == ["Молоко"]
