from app.models import (
    CashCollection,
    Category,
    Order,
    OrderItem,
    OrderItemModifier,
    Product,
    Shift,
    User,
)


def _cashier(session):
    u = User(telegram_id=555, name="Кассир", role="cashier")
    session.add(u)
    session.flush()
    return u


def test_shift_open_defaults(session):
    c = _cashier(session)
    sh = Shift(cashier_id=c.id, opening_cash_tiyn=500000)
    session.add(sh)
    session.commit()
    got = session.query(Shift).one()
    assert got.status == "open"
    assert got.closed_at is None
    assert got.opening_cash_tiyn == 500000
    assert got.opened_at is not None


def test_cash_collection(session):
    c = _cashier(session)
    sh = Shift(cashier_id=c.id, opening_cash_tiyn=0)
    session.add(sh)
    session.flush()
    session.add(CashCollection(shift_id=sh.id, amount_tiyn=300000, note="в сейф"))
    session.commit()
    coll = session.query(CashCollection).one()
    assert coll.amount_tiyn == 300000
    assert coll.note == "в сейф"


def _paid_order(session):
    c = _cashier(session)
    sh = Shift(cashier_id=c.id, opening_cash_tiyn=0)
    session.add(sh)
    session.flush()
    order = Order(
        shift_id=sh.id, number=1, status="paid",
        subtotal_tiyn=170000, discount_tiyn=0, total_tiyn=170000, cost_tiyn=40000,
    )
    session.add(order)
    session.flush()
    return order


def test_order_items_and_modifiers(session):
    order = _paid_order(session)
    item = OrderItem(
        order_id=order.id, product_id=None, name="Латте",
        unit_price_tiyn=170000, qty=1, discount_tiyn=0,
        line_total_tiyn=170000, unit_cost_tiyn=40000,
    )
    session.add(item)
    session.flush()
    session.add(OrderItemModifier(
        order_item_id=item.id, modifier_id=None, name="L", price_delta_tiyn=20000,
    ))
    session.commit()

    got = session.query(OrderItem).one()
    assert got.name == "Латте"
    assert got.refunded_qty == 0
    mod = session.query(OrderItemModifier).one()
    assert mod.name == "L"
    assert mod.price_delta_tiyn == 20000
