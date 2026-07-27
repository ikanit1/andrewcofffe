import pytest

from app.models import (
    Category,
    Ingredient,
    NotificationOutbox,
    Order,
    OrderItem,
    Payment,
    Product,
    RecipeItem,
    Refund,
    RefundItem,
    StockMove,
    User,
)
from app.services import sales_service as sales
from app.services import shift_service as ss
from app.services.pricing import PaymentInput


def _setup(session):
    cashier = User(telegram_id=1, name="Кассир", role="cashier", discount_limit_percent=10)
    session.add(cashier)
    cat = Category(name="Кофе")
    session.add(cat)
    session.flush()
    milk = Ingredient(name="Молоко", unit="мл", stock_qty=1000, avg_cost_tiyn=50.0)
    beans = Ingredient(name="Кофе зерно", unit="г", stock_qty=100, avg_cost_tiyn=300.0)
    session.add_all([milk, beans])
    session.flush()
    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(latte)
    session.flush()
    session.add_all([
        RecipeItem(product_id=latte.id, ingredient_id=beans.id, qty=18),
        RecipeItem(product_id=latte.id, ingredient_id=milk.id, qty=200),
    ])
    session.commit()
    shift = ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=0)
    return cashier, latte, milk, beans, shift


def _line(product_id, qty=1, modifier_ids=None, discount_kind=None, discount_value=0):
    return sales.SaleLineInput(
        product_id=product_id, qty=qty, modifier_ids=modifier_ids or [],
        discount_kind=discount_kind, discount_value=discount_value,
    )


def test_sale_persists_order_and_deducts_stock(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session,
        cashier_id=cashier.id,
        lines=[_line(latte.id, qty=2)],
        payments=[PaymentInput("cash", 300000, 300000)],
    )
    assert order.total_tiyn == 300000
    assert order.cost_tiyn == 2 * 15400
    assert order.number == 1
    assert session.get(Ingredient, milk.id).stock_qty == 600
    assert session.get(Ingredient, beans.id).stock_qty == 64
    moves = session.query(StockMove).filter_by(kind="sale").all()
    assert {m.ref_type for m in moves} == {"order"}
    assert all(m.ref_id == order.id for m in moves)


def test_order_numbers_increment_per_shift(session):
    cashier, latte, milk, beans, shift = _setup(session)
    o1 = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                           payments=[PaymentInput("cash", 150000, 150000)])
    o2 = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                           payments=[PaymentInput("cash", 150000, 150000)])
    assert (o1.number, o2.number) == (1, 2)


def test_split_payment_and_change(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("cash", 50000, 100000), PaymentInput("kaspi_qr", 100000)],
    )
    pays = session.query(Payment).filter_by(order_id=order.id).order_by(Payment.id).all()
    assert pays[0].change_tiyn == 50000
    assert pays[1].method == "kaspi_qr"


def test_payment_must_match_total(session):
    cashier, latte, milk, beans, shift = _setup(session)
    with pytest.raises(ValueError):
        sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                          payments=[PaymentInput("cash", 100000, 100000)])
    assert session.query(Order).count() == 0
    assert session.get(Ingredient, milk.id).stock_qty == 1000


def test_discount_within_limit_ok(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id,
        lines=[_line(latte.id, discount_kind="percent", discount_value=10)],
        payments=[PaymentInput("cash", 135000, 135000)],
    )
    assert order.total_tiyn == 135000


def test_discount_over_limit_blocked(session):
    cashier, latte, milk, beans, shift = _setup(session)
    with pytest.raises(PermissionError):
        sales.create_sale(
            session, cashier_id=cashier.id,
            lines=[_line(latte.id, discount_kind="percent", discount_value=20)],
            payments=[PaymentInput("cash", 120000, 120000)],
        )
    assert session.query(Order).count() == 0


def test_discount_over_limit_allowed_when_approved(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id,
        lines=[_line(latte.id, discount_kind="percent", discount_value=20)],
        payments=[PaymentInput("cash", 120000, 120000)],
        discount_approved=True,
    )
    assert order.total_tiyn == 120000


def test_order_discount_enqueues_notification(session):
    cashier, latte, milk, beans, shift = _setup(session)
    sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("cash", 135000, 135000)],
        order_discount_kind="percent", order_discount_value=10,
    )
    notes = session.query(NotificationOutbox).filter_by(kind="discount").all()
    assert len(notes) == 1
    assert "150.00" in notes[0].text  # 10% от 1500 тг = 150 тг


def test_order_discount_is_spread_over_line_totals(session):
    """Скидка на чек должна уменьшать позиции: сумма строк = итог чека."""
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("cash", 135000, 135000)],
        order_discount_kind="percent", order_discount_value=10,
    )
    items = session.query(OrderItem).filter_by(order_id=order.id).all()
    assert sum(it.line_total_tiyn for it in items) == order.total_tiyn == 135000


def test_order_discount_remainder_lands_on_last_line(session):
    """Неделимый остаток скидки не теряется: сумма строк точно равна итогу."""
    cashier, latte, milk, beans, shift = _setup(session)
    # 3 позиции по 1500 тг, скидка 100 тг: 10000/3 = 3333 с остатком 1 тиын
    order = sales.create_sale(
        session, cashier_id=cashier.id,
        lines=[_line(latte.id), _line(latte.id), _line(latte.id)],
        payments=[PaymentInput("cash", 440000, 440000)],
        order_discount_kind="amount", order_discount_value=10000,
    )
    items = session.query(OrderItem).filter_by(order_id=order.id).order_by(OrderItem.id).all()
    assert [it.line_total_tiyn for it in items] == [146667, 146667, 146666]
    assert sum(it.line_total_tiyn for it in items) == order.total_tiyn == 440000


def test_full_refund_returns_exactly_what_guest_paid(session):
    """Возврат чека со скидкой не должен превышать уплаченную сумму."""
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("cash", 135000, 135000)],
        order_discount_kind="percent", order_discount_value=10,
    )
    refund = sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                               reason="не понравилось")
    assert refund.amount_tiyn == order.total_tiyn == 135000


def test_sale_requires_open_shift(session):
    cashier, latte, milk, beans, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=0)
    with pytest.raises(ValueError):
        sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                          payments=[PaymentInput("cash", 150000, 150000)])


def test_full_refund_marks_order_and_restocks_retail(session):
    cashier = User(telegram_id=2, name="Кассир", role="cashier")
    session.add(cashier)
    cat = Category(name="Снеки")
    session.add(cat)
    session.flush()
    cro = Ingredient(name="Круассан", unit="шт", stock_qty=10, avg_cost_tiyn=45000.0)
    session.add(cro)
    session.flush()
    prod = Product(name="Круассан", category_id=cat.id, kind="retail",
                   price_tiyn=90000, ingredient_id=cro.id)
    session.add(prod)
    session.commit()
    ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=0)
    order = sales.create_sale(session, cashier_id=cashier.id,
                              lines=[_line(prod.id, qty=2)],
                              payments=[PaymentInput("cash", 180000, 180000)])
    assert session.get(Ingredient, cro.id).stock_qty == 8

    refund = sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                               reason="передумал", item_qty=None)
    assert refund.amount_tiyn == 180000
    assert session.get(Order, order.id).status == "refunded"
    assert session.get(Ingredient, cro.id).stock_qty == 10


def test_partial_refund_sets_partial_status(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id, qty=3)],
                              payments=[PaymentInput("cash", 450000, 450000)])
    item = session.query(OrderItem).filter_by(order_id=order.id).one()
    refund = sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                               reason="одну убрать", item_qty={item.id: 1})
    assert refund.amount_tiyn == 150000
    assert session.get(Order, order.id).status == "partially_refunded"
    assert session.get(OrderItem, item.id).refunded_qty == 1
    assert session.get(Ingredient, milk.id).stock_qty == 1000 - 600


def test_cannot_refund_more_than_bought(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id, qty=1)],
                              payments=[PaymentInput("cash", 150000, 150000)])
    item = session.query(OrderItem).filter_by(order_id=order.id).one()
    with pytest.raises(ValueError):
        sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                          reason="слишком много", item_qty={item.id: 5})


def test_write_failure_rolls_back(session, monkeypatch):
    cashier, latte, milk, beans, shift = _setup(session)
    import app.services.sales_service as s
    # заставим списание упасть уже после создания заказа
    monkeypatch.setattr(s, "_deduct_stock",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bdb")))
    with pytest.raises(RuntimeError):
        s.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                      payments=[PaymentInput("cash", 150000, 150000)])
    # откат: заказа нет, склад не тронут, сессия пригодна для дальнейших запросов
    assert session.query(Order).count() == 0
    assert session.get(Ingredient, milk.id).stock_qty == 1000


def test_required_modifier_group_enforced_server_side(session):
    cashier, latte, milk, beans, shift = _setup(session)
    from app.models import ModifierGroup, Modifier, ProductModifierGroup
    grp = ModifierGroup(name="Объём", is_required=True)
    session.add(grp)
    session.flush()
    m = Modifier(group_id=grp.id, name="L", price_delta_tiyn=20000)
    session.add(m)
    session.flush()
    session.add(ProductModifierGroup(product_id=latte.id, group_id=grp.id))
    session.commit()

    # без выбора обязательного модификатора — отказ, ничего не создаётся
    with pytest.raises(ValueError):
        sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                          payments=[PaymentInput("cash", 150000, 150000)])
    assert session.query(Order).count() == 0

    # с выбором — проходит
    order = sales.create_sale(
        session, cashier_id=cashier.id,
        lines=[_line(latte.id, modifier_ids=[m.id])],
        payments=[PaymentInput("cash", 170000, 170000)],
    )
    assert order.total_tiyn == 170000


def test_create_sale_stores_terminal_payment_fields(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("kaspi_terminal", 150000, None,
                               provider="terminal", terminal_method="qr",
                               transaction_id="504711333")],
    )
    from app.models import Payment
    pay = session.query(Payment).filter_by(order_id=order.id).one()
    assert pay.method == "kaspi_terminal"
    assert pay.provider == "terminal"
    assert pay.terminal_method == "qr"
    assert pay.transaction_id == "504711333"


def test_refund_enqueues_notification(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                              payments=[PaymentInput("cash", 150000, 150000)])
    sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id, reason="брак")
    notes = session.query(NotificationOutbox).filter_by(kind="refund").all()
    assert len(notes) == 1
    assert "150000" not in notes[0].text  # сумма должна быть в тенге, не в тиынах
    assert "1500.00" in notes[0].text
    assert "брак" in notes[0].text


def test_sale_enqueues_notification(session):
    cashier, latte, milk, beans, shift = _setup(session)
    sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id, qty=2)],
                      payments=[PaymentInput("cash", 300000, 300000)])
    note = session.query(NotificationOutbox).filter_by(kind="sale").one()
    assert "Латте ×2" in note.text
    assert "3000.00" in note.text          # сумма в тенге, не в тиынах
    assert "300000" not in note.text
    assert "Наличные" in note.text
    assert "Кассир" in note.text
    assert ":" in note.text.splitlines()[-1]  # строка с датой и временем


def test_sale_notification_shows_split_payment_methods(session):
    cashier, latte, milk, beans, shift = _setup(session)
    sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("cash", 50000, 50000), PaymentInput("card", 100000, None)],
    )
    note = session.query(NotificationOutbox).filter_by(kind="sale").one()
    assert "Наличные 500.00 тг" in note.text
    assert "Карта 1000.00 тг" in note.text


def _at_almaty(hour: int, minute: int = 0):
    from datetime import datetime

    from app.timezone import ALMATY
    return datetime(2026, 7, 27, hour, minute, tzinfo=ALMATY)


def test_sale_charges_promo_price_in_the_morning(session, monkeypatch):
    """Утром «Латте» проводится по акционной цене, а не по базовой из карточки."""
    from app.services import promo

    cashier, latte, milk, beans, shift = _setup(session)
    monkeypatch.setattr(promo, "now_almaty", lambda: _at_almaty(9, 0))

    order = sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("cash", 99000, 99000)],
    )
    assert order.total_tiyn == 99000  # 990 тг вместо 1500


def test_sale_charges_base_price_after_promo_ends(session, monkeypatch):
    from app.services import promo

    cashier, latte, milk, beans, shift = _setup(session)
    monkeypatch.setattr(promo, "now_almaty", lambda: _at_almaty(11, 0))

    order = sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("cash", 150000, 150000)],
    )
    assert order.total_tiyn == 150000
