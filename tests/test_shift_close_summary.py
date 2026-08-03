"""Сводка, которая уходит владельцу после закрытия смены кассиром."""
from app.models import NotificationOutbox, User
from app.services import sales_service as sales
from app.services import shift_service as ss
from app.services.pricing import PaymentInput


def _setup(session):
    """Кофе продаётся без учёта остатка, выпечка — со счётчиком штук."""
    from app.models import Category, Product

    cashier = User(telegram_id=1, name="Айгуль", role="cashier", discount_limit_percent=0)
    coffee = Category(name="Кофе", sort_order=0)
    bakery = Category(name="Выпечка", sort_order=1)
    session.add_all([cashier, coffee, bakery])
    session.flush()
    latte = Product(name="Латте", category_id=coffee.id, kind="prepared",
                    price_tiyn=110000)
    cro = Product(name="Круассан", category_id=bakery.id, kind="retail",
                  price_tiyn=85000, stock_qty=5000, low_stock_threshold=2000)
    cheesecake = Product(name="Чизкейк", category_id=bakery.id, kind="retail",
                         price_tiyn=120000, stock_qty=100, low_stock_threshold=500)
    session.add_all([latte, cro, cheesecake])
    session.commit()
    shift = ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=100000)
    return cashier, latte, cro, cheesecake, shift


def _summary_text(session) -> str:
    notes = session.query(NotificationOutbox).filter_by(kind="shift_summary").all()
    assert len(notes) == 1, "сводка должна уходить ровно одна"
    return notes[0].text


def test_close_shift_sends_day_revenue(session):
    cashier, latte, cro, cheesecake, shift = _setup(session)
    sales.create_sale(session, cashier_id=cashier.id,
                      lines=[sales.SaleLineInput(product_id=latte.id, qty=2)],
                      payments=[PaymentInput("cash", 220000, 220000)])
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=320000)

    text = _summary_text(session)
    assert "2200.00" in text          # выручка за день
    assert "Итоги дня" in text


def test_close_shift_summary_lists_stock_remains(session):
    cashier, latte, cro, cheesecake, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=100000)

    text = _summary_text(session)
    assert "Круассан" in text and "5000" in text
    assert "Чизкейк" in text and "100" in text
    assert "Латте" not in text.split("Остатки склада:")[1]  # без учёта — не в сводке


def test_close_shift_summary_marks_low_stock(session):
    """Позиция ниже порога должна быть видна сразу — ради этого сводку и шлют."""
    cashier, latte, cro, cheesecake, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=100000)

    text = _summary_text(session)
    # чизкейк: 100 при пороге 500 — на исходе; круассан 5000 при пороге 2000 — нет
    low_line = next(l for l in text.splitlines() if "Чизкейк" in l)
    ok_line = next(l for l in text.splitlines() if "Круассан" in l)
    assert "!" in low_line
    assert "!" not in ok_line


def test_close_shift_summary_groups_stock_by_menu_category(session):
    cashier, latte, cro, cheesecake, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=100000)

    assert "Выпечка" in _summary_text(session)


def test_close_shift_summary_reports_cash_reconciliation(session):
    cashier, latte, cro, cheesecake, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=95000)

    text = _summary_text(session)
    assert "расхождение" in text.lower()
    assert "-50.00" in text or "−50.00" in text


def test_close_shift_still_sends_the_short_notification(session):
    """Прежнее короткое уведомление о закрытии остаётся: сводка его дополняет."""
    cashier, latte, cro, cheesecake, shift = _setup(session)
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
