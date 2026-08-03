from app.models import Category, Modifier, ModifierGroup, Product
from app.services import costing


def _product(session, *, cost_tiyn=0, name="Латте"):
    cat = session.query(Category).filter_by(name="Кофе").one_or_none()
    if cat is None:
        cat = Category(name="Кофе")
        session.add(cat)
        session.flush()
    p = Product(name=name, category_id=cat.id, kind="prepared", price_tiyn=150000,
                cost_tiyn=cost_tiyn)
    session.add(p)
    session.commit()
    return p


def test_unit_cost_is_purchase_price_of_product(session):
    latte = _product(session, cost_tiyn=45000)
    assert costing.unit_cost_tiyn(session, latte, []) == 45000


def test_unit_cost_is_zero_until_purchase_price_is_set(session):
    latte = _product(session)
    assert costing.unit_cost_tiyn(session, latte, []) == 0


def test_modifiers_do_not_change_cost(session):
    """Сироп и второй шот отражаются наценкой к цене, а не расходом со склада."""
    latte = _product(session, cost_tiyn=45000)
    grp = ModifierGroup(name="Молоко")
    session.add(grp)
    session.flush()
    extra = Modifier(group_id=grp.id, name="Двойное молоко", price_delta_tiyn=20000)
    session.add(extra)
    session.commit()
    assert costing.unit_cost_tiyn(session, latte, [extra.id]) == 45000
