from app.models import (
    Category,
    Ingredient,
    Modifier,
    ModifierGroup,
    ModifierItem,
    Product,
    RecipeItem,
)
from app.services import costing


def _prepared_latte(session):
    cat = Category(name="Кофе")
    session.add(cat)
    session.flush()
    milk = Ingredient(name="Молоко", unit="мл", stock_qty=0, avg_cost_tiyn=50.0)
    beans = Ingredient(name="Кофе зерно", unit="г", stock_qty=0, avg_cost_tiyn=300.0)
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
    return latte, milk


def test_prepared_unit_cost_from_recipe(session):
    latte, _ = _prepared_latte(session)
    assert costing.unit_cost_tiyn(session, latte, []) == 15400


def test_modifier_adds_to_cost(session):
    latte, milk = _prepared_latte(session)
    grp = ModifierGroup(name="Молоко")
    session.add(grp)
    session.flush()
    extra = Modifier(group_id=grp.id, name="Двойное молоко", price_delta_tiyn=20000)
    session.add(extra)
    session.flush()
    session.add(ModifierItem(modifier_id=extra.id, ingredient_id=milk.id, qty=100))
    session.commit()
    assert costing.unit_cost_tiyn(session, latte, [extra.id]) == 20400


def test_retail_unit_cost_from_linked_ingredient(session):
    cat = Category(name="Снеки")
    session.add(cat)
    session.flush()
    cro = Ingredient(name="Круассан", unit="шт", stock_qty=0, avg_cost_tiyn=45000.0)
    session.add(cro)
    session.flush()
    prod = Product(name="Круассан", category_id=cat.id, kind="retail",
                   price_tiyn=90000, ingredient_id=cro.id)
    session.add(prod)
    session.commit()
    assert costing.unit_cost_tiyn(session, prod, []) == 45000
