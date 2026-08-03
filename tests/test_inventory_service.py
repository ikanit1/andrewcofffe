import pytest

from app.models import Category, NotificationOutbox, Product, StockMove
from app.services import inventory_service as inv


def _product(session, *, name="Круассан", stock_qty=None, threshold=0, cost_tiyn=0,
             kind="retail", price_tiyn=90000, category="Выпечка", sort_order=0):
    cat = session.query(Category).filter_by(name=category).one_or_none()
    if cat is None:
        cat = Category(name=category, sort_order=sort_order)
        session.add(cat)
        session.flush()
    p = Product(name=name, category_id=cat.id, kind=kind, price_tiyn=price_tiyn,
                stock_qty=stock_qty, low_stock_threshold=threshold, cost_tiyn=cost_tiyn)
    session.add(p)
    session.commit()
    return p


# --------------------------------------------------------------------------
# движения и остаток
# --------------------------------------------------------------------------


def test_purchase_increases_stock_and_sets_cost(session):
    cro = _product(session)
    inv.receive_purchase(session, cro.id, qty=20, total_cost_tiyn=900000)  # 450 тг/шт
    assert cro.stock_qty == 20
    assert cro.cost_tiyn == 45000


def test_purchase_starts_tracking_untracked_product(session):
    """Раз товар закупили штуками — считать есть что, даже если раньше не считали."""
    cro = _product(session, stock_qty=None)
    assert inv.tracked(cro) is False
    inv.receive_purchase(session, cro.id, qty=5, total_cost_tiyn=100000)
    assert (cro.stock_qty, cro.cost_tiyn) == (5, 20000)


def test_weighted_average_cost(session):
    cro = _product(session)
    inv.receive_purchase(session, cro.id, qty=10, total_cost_tiyn=400000)   # 400 тг/шт
    inv.receive_purchase(session, cro.id, qty=10, total_cost_tiyn=600000)   # 600 тг/шт
    assert cro.stock_qty == 20
    assert cro.cost_tiyn == 50000                                          # 500 тг/шт


def test_purchase_without_sum_keeps_previous_cost(session):
    cro = _product(session, stock_qty=0, cost_tiyn=45000)
    inv.receive_purchase(session, cro.id, qty=5, total_cost_tiyn=0)
    assert (cro.stock_qty, cro.cost_tiyn) == (5, 45000)


def test_purchase_rejects_bad_input(session):
    cro = _product(session)
    with pytest.raises(ValueError, match="больше нуля"):
        inv.receive_purchase(session, cro.id, qty=0, total_cost_tiyn=1000)
    with pytest.raises(ValueError, match="отрицательной"):
        inv.receive_purchase(session, cro.id, qty=1, total_cost_tiyn=-1)


def test_apply_move_writes_journal_and_cache(session):
    cro = _product(session, stock_qty=10)
    inv.apply_move(session, cro.id, qty_delta=-2, kind="sale", ref_type="order", ref_id=1)
    session.commit()
    assert cro.stock_qty == 8
    moves = session.query(StockMove).filter_by(product_id=cro.id).all()
    assert [(m.kind, m.qty_delta) for m in moves] == [("sale", -2)]


def test_apply_move_skips_untracked_products(session):
    """У кофе из общих запасов количества нет — журнал по нему не заводится."""
    latte = _product(session, name="Латте", kind="prepared", stock_qty=None)
    assert inv.apply_move(session, latte.id, qty_delta=-1, kind="sale", commit=True) is None
    assert session.query(StockMove).count() == 0
    assert session.get(Product, latte.id).stock_qty is None


def test_stock_can_go_negative(session):
    """Склад не мешает продавать: остаток уходит в минус, но чек проходит."""
    cro = _product(session, stock_qty=1)
    inv.apply_move(session, cro.id, qty_delta=-3, kind="sale", commit=True)
    assert session.get(Product, cro.id).stock_qty == -2


# --------------------------------------------------------------------------
# ручная правка остатка
# --------------------------------------------------------------------------


def test_set_stock_writes_difference_as_adjustment(session):
    cro = _product(session, stock_qty=10)
    inv.set_stock(session, cro.id, new_qty=7, note="инвентаризация")
    assert session.get(Product, cro.id).stock_qty == 7
    move = session.query(StockMove).one()
    assert (move.kind, move.qty_delta, move.note) == ("adjustment", -3, "инвентаризация")


def test_set_stock_starts_tracking_from_zero(session):
    cro = _product(session, stock_qty=None)
    inv.set_stock(session, cro.id, new_qty=12)
    assert session.get(Product, cro.id).stock_qty == 12
    assert session.query(StockMove).one().qty_delta == 12


def test_set_stock_none_stops_tracking(session):
    cro = _product(session, stock_qty=5)
    inv.set_stock(session, cro.id, new_qty=None)
    assert session.get(Product, cro.id).stock_qty is None
    assert session.query(StockMove).count() == 0


def test_set_stock_without_change_writes_nothing(session):
    cro = _product(session, stock_qty=5)
    assert inv.set_stock(session, cro.id, new_qty=5) is None
    assert session.query(StockMove).count() == 0


def test_update_stock_settings_validates(session):
    cro = _product(session, stock_qty=5)
    inv.update_product_stock_settings(session, cro.id, low_stock_threshold=3,
                                      cost_tiyn=45000)
    fresh = session.get(Product, cro.id)
    assert (fresh.low_stock_threshold, fresh.cost_tiyn) == (3, 45000)
    with pytest.raises(ValueError, match="Порог"):
        inv.update_product_stock_settings(session, cro.id, low_stock_threshold=-1)
    with pytest.raises(ValueError, match="Закупочная цена"):
        inv.update_product_stock_settings(session, cro.id, cost_tiyn=-1)


# --------------------------------------------------------------------------
# уведомления о низком остатке
# --------------------------------------------------------------------------


def test_low_stock_notifies_once(session):
    cro = _product(session, stock_qty=10, threshold=5)
    inv.apply_move(session, cro.id, qty_delta=-6, kind="sale", commit=True)  # 4 — ниже порога
    notes = session.query(NotificationOutbox).filter_by(kind="low_stock").all()
    assert len(notes) == 1 and "Круассан" in notes[0].text

    inv.apply_move(session, cro.id, qty_delta=-1, kind="sale", commit=True)  # 3 — всё ещё ниже
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1


def test_low_stock_notifies_again_after_restock_and_fall(session):
    cro = _product(session, stock_qty=10, threshold=5)
    inv.apply_move(session, cro.id, qty_delta=-6, kind="sale", commit=True)
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1

    inv.receive_purchase(session, cro.id, qty=10, total_cost_tiyn=0)         # 14 — выше порога
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1

    inv.apply_move(session, cro.id, qty_delta=-12, kind="sale", commit=True)  # 2 — снова ниже
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 2


def test_zero_threshold_stays_silent_even_in_minus(session):
    cro = _product(session, stock_qty=1, threshold=0)
    inv.apply_move(session, cro.id, qty_delta=-5, kind="sale", commit=True)
    assert session.get(Product, cro.id).stock_qty == -4
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 0


def test_low_stock_products_lists_only_tracked_below_threshold(session):
    _product(session, name="Круассан", stock_qty=2, threshold=5)
    _product(session, name="Чизкейк", stock_qty=9, threshold=5)
    _product(session, name="Латте", kind="prepared", stock_qty=None, threshold=5)
    _product(session, name="Печенье", stock_qty=1, threshold=0)  # порог не задан
    hidden = _product(session, name="Старый пирог", stock_qty=0, threshold=5)
    hidden.is_active = False
    session.commit()

    assert [p.name for p in inv.low_stock_products(session)] == ["Круассан"]


# --------------------------------------------------------------------------
# экранные выборки
# --------------------------------------------------------------------------


def test_stock_rows_group_by_menu_category_and_filter(session):
    _product(session, name="Круассан", category="Выпечка", stock_qty=4, sort_order=1)
    _product(session, name="Чизкейк", category="Выпечка", stock_qty=2, sort_order=1)
    _product(session, name="Латте", category="Кофе", kind="prepared", stock_qty=None,
             sort_order=0)
    hidden = _product(session, name="Глинтвейн", category="Кофе", stock_qty=0)
    hidden.is_active = False
    session.commit()

    rows = inv.stock_rows(session)
    assert [(r.name, r.category) for r in rows] == [
        ("Латте", "Кофе"), ("Круассан", "Выпечка"), ("Чизкейк", "Выпечка")]
    assert [r.tracked for r in rows] == [False, True, True]

    assert [r.name for r in inv.stock_rows(session, only_tracked=True)] \
        == ["Круассан", "Чизкейк"]
    assert [r.name for r in inv.stock_rows(session, query="чиз")] == ["Чизкейк"]
    assert "Глинтвейн" in [r.name for r in inv.stock_rows(session, include_hidden=True)]


def test_stock_row_flags(session):
    low = inv.stock_rows(session)  # пустой склад не падает
    assert low == []
    _product(session, name="Круассан", stock_qty=2, threshold=5)
    _product(session, name="Латте", kind="prepared", stock_qty=None, threshold=5)
    rows = {r.name: r for r in inv.stock_rows(session)}
    assert rows["Круассан"].is_low is True
    assert rows["Латте"].is_low is False      # не считается — не «на исходе»
    assert rows["Латте"].tracked is False


def test_stock_value_counts_only_positive_tracked_stock(session):
    _product(session, name="Круассан", stock_qty=10, cost_tiyn=45000)   # 4500 тг
    _product(session, name="Чизкейк", stock_qty=-2, cost_tiyn=60000)    # минус не считаем
    _product(session, name="Латте", kind="prepared", stock_qty=None, cost_tiyn=30000)
    assert inv.stock_value_tiyn(session) == 450000


def test_recent_moves_and_clear(session):
    cro = _product(session, stock_qty=0)
    inv.receive_purchase(session, cro.id, qty=10, total_cost_tiyn=100000)
    inv.apply_move(session, cro.id, qty_delta=-1, kind="sale", commit=True)

    moves = inv.recent_moves(session)
    assert [(m.product_name, m.kind, m.qty_delta) for m in moves] == [
        ("Круассан", "sale", -1), ("Круассан", "purchase", 10)]
    assert moves[0].kind_label == "Продажа"
    assert [m.kind for m in inv.recent_moves(session, kind="purchase")] == ["purchase"]

    assert inv.clear_moves(session, cro.id) == 2
    assert inv.recent_moves(session) == []
    assert session.get(Product, cro.id).stock_qty == 9   # остаток не тронут
