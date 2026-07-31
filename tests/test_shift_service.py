import pytest

from app.models import NotificationOutbox, Order, Payment, Refund, Shift, User
from app.services import shift_service as ss


def _cashier(session):
    u = User(telegram_id=555, name="Кассир", role="cashier")
    session.add(u)
    session.commit()
    return u


def test_open_shift(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=500000)
    assert sh.status == "open"
    assert ss.current_open_shift(session) is not None


def test_cannot_open_two_shifts(session):
    c = _cashier(session)
    ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=0)
    with pytest.raises(ValueError):
        ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=0)


def test_collection_reduces_expected_cash(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=500000)
    ss.add_collection(session, shift_id=sh.id, amount_tiyn=200000, note="в сейф")
    assert ss.expected_cash_tiyn(session, sh.id) == 300000


def test_expected_cash_counts_only_cash_sales(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    order = Order(shift_id=sh.id, number=1, status="paid",
                  subtotal_tiyn=170000, total_tiyn=170000)
    session.add(order)
    session.flush()
    session.add_all([
        Payment(order_id=order.id, method="cash", amount_tiyn=100000),
        Payment(order_id=order.id, method="kaspi_qr", amount_tiyn=70000),
    ])
    session.commit()
    assert ss.expected_cash_tiyn(session, sh.id) == 200000


def test_cash_breakdown_splits_expected_cash_into_parts(session):
    """Дашборд показывает слагаемые ящика, а не только итог — они должны сходиться."""
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    order = Order(shift_id=sh.id, number=1, status="paid",
                  subtotal_tiyn=80000, total_tiyn=80000)
    session.add(order)
    session.flush()
    session.add(Payment(order_id=order.id, method="cash", amount_tiyn=80000))
    session.add(Refund(order_id=order.id, amount_tiyn=30000, reason="брак", cashier_id=c.id))
    session.commit()
    ss.add_collection(session, shift_id=sh.id, amount_tiyn=20000)

    cash = ss.cash_breakdown(session, sh.id)
    assert (cash.opening_tiyn, cash.cash_sales_tiyn) == (100000, 80000)
    assert (cash.collections_tiyn, cash.cash_refunds_tiyn) == (20000, 30000)
    assert cash.expected_tiyn == 130000
    assert cash.expected_tiyn == ss.expected_cash_tiyn(session, sh.id)


def test_refund_reduces_expected_cash(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    order = Order(shift_id=sh.id, number=1, status="paid",
                  subtotal_tiyn=50000, total_tiyn=50000)
    session.add(order)
    session.flush()
    session.add(Payment(order_id=order.id, method="cash", amount_tiyn=50000))
    session.add(Refund(order_id=order.id, amount_tiyn=50000, reason="брак", cashier_id=c.id))
    session.commit()
    assert ss.expected_cash_tiyn(session, sh.id) == 100000


def test_non_cash_refund_does_not_reduce_expected_cash(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    order = Order(shift_id=sh.id, number=1, status="paid",
                  subtotal_tiyn=50000, total_tiyn=50000)
    session.add(order)
    session.flush()
    session.add(Payment(order_id=order.id, method="kaspi_qr", amount_tiyn=50000))
    session.add(Refund(order_id=order.id, amount_tiyn=50000, reason="брак", cashier_id=c.id))
    session.commit()
    # Kaspi-оплата не входит в кэш-продажи, и её возврат не должен уменьшать ожидаемую наличность
    assert ss.expected_cash_tiyn(session, sh.id) == 100000


def _split_paid_order(session, sh, cashier, *, total, cash, non_cash):
    order = Order(shift_id=sh.id, number=1, status="paid",
                  subtotal_tiyn=total, total_tiyn=total)
    session.add(order)
    session.flush()
    session.add_all([
        Payment(order_id=order.id, method="cash", amount_tiyn=cash),
        Payment(order_id=order.id, method="card", amount_tiyn=non_cash),
    ])
    session.commit()
    return order


def test_split_paid_refund_reduces_cash_by_cash_share(session):
    """Чек 400 наличными + 600 картой: полный возврат забирает из ящика 400."""
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    order = _split_paid_order(session, sh, c, total=100000, cash=40000, non_cash=60000)
    session.add(Refund(order_id=order.id, amount_tiyn=100000, reason="брак", cashier_id=c.id))
    session.commit()
    assert ss.expected_cash_tiyn(session, sh.id) == 100000


def test_split_paid_partial_refund_takes_proportional_cash(session):
    """Возврат половины чека, оплаченного на 40% наличными, забирает 40% от возврата."""
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    order = _split_paid_order(session, sh, c, total=100000, cash=40000, non_cash=60000)
    session.add(Refund(order_id=order.id, amount_tiyn=50000, reason="одну убрать", cashier_id=c.id))
    session.commit()
    # 100000 старт + 40000 налом − 20000 (40% от возврата 50000)
    assert ss.expected_cash_tiyn(session, sh.id) == 120000


def test_close_shift_records_discrepancy(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    closed = ss.close_shift(session, shift_id=sh.id, counted_cash_tiyn=95000)
    assert closed.status == "closed"
    assert closed.closed_at is not None
    assert closed.expected_cash_tiyn == 100000
    assert closed.counted_cash_tiyn == 95000
    assert ss.current_open_shift(session) is None


def test_cannot_close_twice(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=0)
    ss.close_shift(session, shift_id=sh.id, counted_cash_tiyn=0)
    with pytest.raises(ValueError):
        ss.close_shift(session, shift_id=sh.id, counted_cash_tiyn=0)


def test_open_shift_enqueues_notification(session):
    c = _cashier(session)
    ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=500000)
    notes = session.query(NotificationOutbox).filter_by(kind="shift_open").all()
    assert len(notes) == 1
    assert "Кассир" in notes[0].text


def test_close_shift_enqueues_notification(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    ss.close_shift(session, shift_id=sh.id, counted_cash_tiyn=95000)
    notes = session.query(NotificationOutbox).filter_by(kind="shift_close").all()
    assert len(notes) == 1
    assert "Кассир" in notes[0].text


def test_collection_enqueues_notification(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=500000)
    ss.add_collection(session, shift_id=sh.id, amount_tiyn=200000, note="в сейф")
    notes = session.query(NotificationOutbox).filter_by(kind="collection").all()
    assert len(notes) == 1
    assert "Кассир" in notes[0].text


def test_collection_rejects_unknown_shift(session):
    with pytest.raises(ValueError):
        ss.add_collection(session, shift_id=999, amount_tiyn=1000)
