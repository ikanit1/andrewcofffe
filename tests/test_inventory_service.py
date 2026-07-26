import pytest

from app.models import Ingredient, NotificationOutbox, StockMove
from app.services import inventory_service as inv


def _milk(session):
    m = Ingredient(name="Молоко", unit="мл", low_stock_threshold=2000)
    session.add(m)
    session.commit()
    return m


def test_purchase_increases_stock_and_sets_cost(session):
    milk = _milk(session)
    # 10 л молока за 5000 тг = 10000 мл за 500000 тиын → 50 тиын/мл
    inv.receive_purchase(session, milk.id, qty=10000, total_cost_tiyn=500000)
    assert milk.stock_qty == 10000
    assert milk.avg_cost_tiyn == pytest.approx(50.0)


def test_weighted_average_cost(session):
    milk = _milk(session)
    inv.receive_purchase(session, milk.id, qty=10000, total_cost_tiyn=500000)  # 50/мл
    inv.receive_purchase(session, milk.id, qty=10000, total_cost_tiyn=700000)  # 70/мл
    assert milk.stock_qty == 20000
    assert milk.avg_cost_tiyn == pytest.approx(60.0)


def test_apply_move_writes_journal_and_cache(session):
    milk = _milk(session)
    inv.receive_purchase(session, milk.id, qty=10000, total_cost_tiyn=500000)
    inv.apply_move(session, milk.id, qty_delta=-200, kind="sale", ref_type="order", ref_id=1)
    session.commit()  # apply_move больше не коммитит по умолчанию — коммитит вызывающий
    assert milk.stock_qty == 9800
    moves = session.query(StockMove).filter_by(ingredient_id=milk.id).all()
    assert [m.kind for m in moves] == ["purchase", "sale"]


def test_purchase_rejects_bad_input(session):
    milk = _milk(session)
    with pytest.raises(ValueError):
        inv.receive_purchase(session, milk.id, qty=0, total_cost_tiyn=100)
    with pytest.raises(ValueError):
        inv.receive_purchase(session, milk.id, qty=100, total_cost_tiyn=-1)


def test_low_stock_triggers_notification_once(session):
    milk = Ingredient(name="Молоко", unit="мл", low_stock_threshold=1000)
    session.add(milk)
    session.commit()
    inv.receive_purchase(session, milk.id, qty=5000, total_cost_tiyn=100000)  # 5000, выше порога
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 0

    inv.apply_move(session, milk.id, qty_delta=-4500, kind="sale", commit=True)  # 500, ниже порога
    notes = session.query(NotificationOutbox).filter_by(kind="low_stock").all()
    assert len(notes) == 1
    assert "Молоко" in notes[0].text

    inv.apply_move(session, milk.id, qty_delta=-100, kind="sale", commit=True)  # 400, всё ещё ниже
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1  # без дублей


def test_zero_threshold_stays_silent_when_stock_goes_negative(session):
    """Порог 0 = отслеживание выключено, даже если остаток ушёл в минус."""
    sugar = Ingredient(name="Сахар", unit="г", stock_qty=10, low_stock_threshold=0)
    session.add(sugar)
    session.commit()
    inv.apply_move(session, sugar.id, qty_delta=-30, kind="sale", commit=True)
    assert session.get(Ingredient, sugar.id).stock_qty == -20
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 0


def test_low_stock_notifies_again_after_restock_and_fall(session):
    milk = Ingredient(name="Молоко", unit="мл", low_stock_threshold=1000)
    session.add(milk)
    session.commit()
    inv.receive_purchase(session, milk.id, qty=5000, total_cost_tiyn=100000)
    inv.apply_move(session, milk.id, qty_delta=-4500, kind="sale", commit=True)  # 500 → уведомление №1
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1

    inv.receive_purchase(session, milk.id, qty=5000, total_cost_tiyn=100000)  # 5500, выше порога — сброс флага
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1  # само пополнение не уведомляет

    inv.apply_move(session, milk.id, qty_delta=-4600, kind="sale", commit=True)  # 900 → уведомление №2
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 2
