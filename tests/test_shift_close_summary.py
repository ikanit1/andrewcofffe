"""Сводка, которая уходит владельцу после закрытия смены кассиром."""
from app.models import Ingredient, NotificationOutbox, StockCategory, User
from app.services import sales_service as sales
from app.services import shift_service as ss
from app.services.pricing import PaymentInput


def _setup(session):
    from app.models import Category, Product, RecipeItem

    cashier = User(telegram_id=1, name="Айгуль", role="cashier", discount_limit_percent=0)
    cat = Category(name="Кофе")
    session.add_all([cashier, cat])
    session.flush()
    milk = Ingredient(name="Молоко", unit="мл", stock_qty=5000,
                      avg_cost_tiyn=1.0, low_stock_threshold=2000)
    beans = Ingredient(name="Кофе зерно", unit="г", stock_qty=100,
                       avg_cost_tiyn=3.0, low_stock_threshold=500)
    session.add_all([milk, beans])
    session.flush()
    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=110000)
    session.add(latte)
    session.flush()
    session.add(RecipeItem(product_id=latte.id, ingredient_id=milk.id, qty=200))
    session.commit()
    shift = ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=100000)
    return cashier, latte, milk, beans, shift


def _summary_text(session) -> str:
    notes = session.query(NotificationOutbox).filter_by(kind="shift_summary").all()
    assert len(notes) == 1, "сводка должна уходить ровно одна"
    return notes[0].text


def test_close_shift_sends_day_revenue(session):
    cashier, latte, milk, beans, shift = _setup(session)
    sales.create_sale(session, cashier_id=cashier.id,
                      lines=[sales.SaleLineInput(product_id=latte.id, qty=2)],
                      payments=[PaymentInput("cash", 220000, 220000)])
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=320000)

    text = _summary_text(session)
    assert "2200.00" in text          # выручка за день
    assert "Итоги дня" in text


def test_close_shift_summary_lists_stock_remains(session):
    cashier, latte, milk, beans, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=100000)

    text = _summary_text(session)
    assert "Молоко" in text and "5000" in text
    assert "Кофе зерно" in text and "100" in text


def test_close_shift_summary_marks_low_stock(session):
    """Позиция ниже порога должна быть видна сразу — ради этого сводку и шлют."""
    cashier, latte, milk, beans, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=100000)

    text = _summary_text(session)
    # зерно: 100 при пороге 500 — на исходе; молоко 5000 при пороге 2000 — нет
    low_line = next(l for l in text.splitlines() if "Кофе зерно" in l)
    ok_line = next(l for l in text.splitlines() if "Молоко" in l)
    assert "!" in low_line
    assert "!" not in ok_line


def test_close_shift_summary_groups_stock_by_section(session):
    cashier, latte, milk, beans, shift = _setup(session)
    section = StockCategory(name="Молочка")
    session.add(section)
    session.flush()
    milk.category_id = section.id
    session.commit()
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=100000)

    assert "Молочка" in _summary_text(session)


def test_close_shift_summary_reports_cash_reconciliation(session):
    cashier, latte, milk, beans, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=95000)

    text = _summary_text(session)
    assert "расхождение" in text.lower()
    assert "-50.00" in text or "−50.00" in text


def test_close_shift_still_sends_the_short_notification(session):
    """Прежнее короткое уведомление о закрытии остаётся: сводка его дополняет."""
    cashier, latte, milk, beans, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=100000)

    kinds = [n.kind for n in session.query(NotificationOutbox).all()]
    assert "shift_close" in kinds and "shift_summary" in kinds


def test_summary_survives_empty_stock(session):
    """Пустой склад не должен ронять закрытие смены."""
    from app.models import Category, Product

    cashier = User(telegram_id=2, name="Кассир", role="cashier")
    session.add(cashier)
    session.commit()
    shift = ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=0)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=0)

    assert "Итоги дня" in _summary_text(session)
