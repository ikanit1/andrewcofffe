import pytest

from app.models import Ingredient, StockMove
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
    assert milk.stock_qty == 9800
    moves = session.query(StockMove).filter_by(ingredient_id=milk.id).all()
    assert [m.kind for m in moves] == ["purchase", "sale"]


def test_purchase_rejects_bad_input(session):
    milk = _milk(session)
    with pytest.raises(ValueError):
        inv.receive_purchase(session, milk.id, qty=0, total_cost_tiyn=100)
    with pytest.raises(ValueError):
        inv.receive_purchase(session, milk.id, qty=100, total_cost_tiyn=-1)
