from app.auth import hash_pin
from app.models import Category, Ingredient, Product, RecipeItem, User
from app.services import sales_service as sales
from app.services import shift_service as ss
from app.services import user_service as us
from app.services.pricing import PaymentInput


def test_end_to_end_login_shift_sale_refund_close(session):
    # пользователь и меню
    cashier = User(telegram_id=100, name="Кассир", role="cashier",
                   discount_limit_percent=10, pin_hash=hash_pin("4821"))
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

    # вход по пину
    assert us.authenticate(session, user_id=cashier.id, pin="4821") is not None

    # смена
    shift = ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=500000)

    # продажа
    order = sales.create_sale(
        session, cashier_id=cashier.id,
        lines=[sales.SaleLineInput(product_id=latte.id, qty=2)],
        payments=[PaymentInput("cash", 300000, 300000)],
    )
    assert order.total_tiyn == 300000
    assert session.get(Ingredient, milk.id).stock_qty == 600

    # частичный возврат одной порции — приготовленный напиток склад не возвращает
    from app.models import OrderItem
    oi = session.query(OrderItem).filter_by(order_id=order.id).one()
    sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                      reason="одну убрать", item_qty={oi.id: 1})

    # ожидаемая наличность: 500000 старт + 300000 продажа - 150000 возврат
    assert ss.expected_cash_tiyn(session, shift.id) == 650000

    # закрытие смены
    closed = ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=650000)
    assert closed.status == "closed"
    assert closed.expected_cash_tiyn == 650000
