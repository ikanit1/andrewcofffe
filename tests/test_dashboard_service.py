from datetime import datetime, timedelta, timezone

from app.models import Category, Ingredient, Order, OrderItem, Product, Refund, Shift, User
from app.services import dashboard_service as ds
from app.services import sales_service as sales
from app.services.pricing import PaymentInput
from app.timezone import ALMATY


def _shift(session, *, opening_cash_tiyn=0):
    u = User(telegram_id=1, name="Кассир", role="cashier")
    session.add(u)
    session.flush()
    sh = Shift(cashier_id=u.id, opening_cash_tiyn=opening_cash_tiyn)
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


# --------------------------------------------------------------------------
# Снимок дашборда
# --------------------------------------------------------------------------

# 28.07.2026 — вторник; 21.07 и 14.07 те же вторники, на них опирается план.
NOW = datetime(2026, 7, 28, 15, 0, tzinfo=ALMATY)


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    """Местное время со сдвигом в днях — в UTC, как хранит база."""
    local = NOW.replace(hour=hour, minute=minute) - timedelta(days=day_offset)
    return local.astimezone(timezone.utc)


def test_dashboard_compares_with_same_hour_yesterday(session):
    sh = _shift(session)
    _order(session, sh.id, number=1, created_at=_at(0, 10), total_tiyn=100000)
    _order(session, sh.id, number=2, created_at=_at(1, 10), total_tiyn=300000)
    # Вчерашний вечерний чек — уже позже «сейчас», в сравнение попасть не должен.
    _order(session, sh.id, number=3, created_at=_at(1, 20), total_tiyn=900000)

    dash = ds.dashboard(session, now=NOW)
    assert dash.today.gross_tiyn == 100000
    assert dash.yesterday.gross_tiyn == 300000


def test_dashboard_plan_averages_same_weekday(session):
    sh = _shift(session)
    _order(session, sh.id, number=1, created_at=_at(7, 12), total_tiyn=100000)
    _order(session, sh.id, number=2, created_at=_at(14, 12), total_tiyn=300000)
    _order(session, sh.id, number=3, created_at=_at(0, 10), total_tiyn=50000)

    dash = ds.dashboard(session, now=NOW)
    assert dash.plan is not None
    assert dash.plan.basis_days == 2
    assert dash.plan.target_tiyn == 200000          # среднее двух прошлых вторников
    assert dash.plan.done_pct == 25                 # 50 000 из 200 000
    assert dash.plan.norm_pct == 100                # оба дня к 15:00 уже отторговали
    assert dash.plan.left_tiyn == 150000
    assert dash.plan.ahead is False


def test_dashboard_plan_ignores_days_without_sales(session):
    sh = _shift(session)
    _order(session, sh.id, number=1, created_at=_at(7, 12), total_tiyn=100000)
    dash = ds.dashboard(session, now=NOW)
    assert dash.plan is not None
    assert dash.plan.basis_days == 1
    assert dash.plan.target_tiyn == 100000


def test_dashboard_plan_absent_without_history(session):
    sh = _shift(session)
    _order(session, sh.id, number=1, created_at=_at(0, 10), total_tiyn=50000)
    assert ds.dashboard(session, now=NOW).plan is None


def test_dashboard_hours_window_spans_sales_and_now(session):
    sh = _shift(session)
    _order(session, sh.id, number=1, created_at=_at(0, 9), total_tiyn=50000)
    _order(session, sh.id, number=2, created_at=_at(1, 19), total_tiyn=50000)

    dash = ds.dashboard(session, now=NOW)
    hours = [h.hour for h in dash.hours]
    assert hours == list(range(9, 20))              # от первой продажи до вчерашней последней
    assert [h.hour for h in dash.hours if h.is_future] == [16, 17, 18, 19]
    assert dash.peak is not None and dash.peak.hour == 9


def test_dashboard_hours_fall_back_to_working_window_when_empty(session):
    _shift(session)
    dash = ds.dashboard(session, now=NOW)
    assert [h.hour for h in dash.hours] == list(range(8, 22))
    assert dash.peak is None


def test_dashboard_recent_receipts_are_newest_first(session):
    sh = _shift(session)
    for i in range(1, 4):
        _order(session, sh.id, number=i, created_at=_at(0, 9 + i), total_tiyn=10000 * i)
    dash = ds.dashboard(session, now=NOW)
    assert [r.number for r in dash.recent] == [3, 2, 1]


def test_dashboard_stock_skips_positions_without_threshold(session):
    session.add_all([
        Ingredient(name="Молоко", unit="мл", stock_qty=100, low_stock_threshold=500),
        Ingredient(name="Зерно", unit="г", stock_qty=4000, low_stock_threshold=1000),
        Ingredient(name="Салфетки", unit="шт", stock_qty=5, low_stock_threshold=0),
    ])
    session.commit()

    stock = ds.dashboard(session, now=NOW).stock
    assert [s.name for s in stock] == ["Молоко", "Зерно"]   # ближайшие к нулю первыми
    assert stock[0].pct == 20 and stock[0].is_low
    assert stock[1].pct == 100 and not stock[1].is_low


def test_dashboard_counts_orders_touched_by_refunds_not_refunds(session):
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
    for _ in range(2):  # два частичных возврата по одному и тому же чеку
        sales.refund_sale(session, order_id=order.id, cashier_id=sh.cashier_id,
                          reason="передумали", item_qty={item.id: 1})

    # Минутой позже продажи: возвраты и оплаты записаны уже после неё, а снимок
    # берёт всё до указанного момента.
    dash = ds.dashboard(session, now=order.created_at + timedelta(minutes=1))
    assert dash.refunded_orders_count == 1
    assert dash.today.refunds_tiyn == 200000
    assert [(m.method, m.orders_count) for m in dash.methods] == [("cash", 1)]
    assert [(p.name, p.category, p.qty) for p in dash.top] == [("Латте", "Кофе", 0)]


def test_dashboard_cash_box_follows_open_shift(session):
    sh = _shift(session, opening_cash_tiyn=50000)
    cat = Category(name="Кофе")
    session.add(cat)
    session.commit()
    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=100000)
    session.add(latte)
    session.commit()
    sales.create_sale(
        session, cashier_id=sh.cashier_id,
        lines=[sales.SaleLineInput(product_id=latte.id, qty=1)],
        payments=[PaymentInput("cash", 100000, 100000)],
    )

    dash = ds.dashboard(session, now=NOW)
    assert dash.cash is not None
    assert dash.cash.opening_tiyn == 50000
    assert dash.cash.cash_sales_tiyn == 100000
    assert dash.cash.expected_tiyn == 150000
    assert dash.shift is not None and dash.shift.shift_id == sh.id


def test_dashboard_without_open_shift_has_no_cash_box(session):
    sh = _shift(session)
    sh.status = "closed"
    session.commit()
    dash = ds.dashboard(session, now=NOW)
    assert dash.cash is None
    assert dash.shift is None
