import pytest

from app.models import Category, Ingredient, Product, StockCategory
from app.services import catalog_service as cs
from app.services import inventory_service as inv


def _ing(session, name: str, category_id=None) -> Ingredient:
    i = Ingredient(name=name, unit="шт", stock_qty=7, category_id=category_id)
    session.add(i)
    session.commit()
    return i


# --- разделы склада -------------------------------------------------------

def test_create_and_rename_stock_category(session):
    cat = inv.create_stock_category(session, "  Молочка  ")
    assert cat.name == "Молочка"
    inv.rename_stock_category(session, cat.id, "Молочные продукты")
    assert session.get(StockCategory, cat.id).name == "Молочные продукты"


def test_duplicate_stock_category_rejected(session):
    inv.create_stock_category(session, "Снеки")
    with pytest.raises(ValueError, match="уже есть"):
        inv.create_stock_category(session, "Снеки")


def test_rename_to_existing_name_rejected(session):
    a = inv.create_stock_category(session, "Снеки")
    inv.create_stock_category(session, "Заморозка")
    with pytest.raises(ValueError, match="уже есть"):
        inv.rename_stock_category(session, a.id, "Заморозка")


def test_empty_name_rejected(session):
    with pytest.raises(ValueError):
        inv.create_stock_category(session, "   ")


def test_delete_category_keeps_ingredients_and_stock(session):
    """Главное: удаление раздела не должно уносить позиции и остатки."""
    cat = inv.create_stock_category(session, "Заморозка")
    a = _ing(session, "Пельмени", cat.id)
    b = _ing(session, "Вареники", cat.id)

    moved = inv.delete_stock_category(session, cat.id)

    assert moved == 2
    assert session.get(StockCategory, cat.id) is None
    for i in (a, b):
        session.refresh(i)
        assert i.category_id is None
        assert i.stock_qty == 7  # остаток на месте
    assert session.query(Ingredient).count() == 2


def test_delete_empty_category(session):
    cat = inv.create_stock_category(session, "Пустой")
    assert inv.delete_stock_category(session, cat.id) == 0


def test_set_ingredient_category_and_clear(session):
    cat = inv.create_stock_category(session, "Молочка")
    i = _ing(session, "Молоко")
    inv.set_ingredient_category(session, i.id, cat.id)
    session.refresh(i)
    assert i.category_id == cat.id
    inv.set_ingredient_category(session, i.id, None)
    session.refresh(i)
    assert i.category_id is None


def test_set_unknown_category_rejected(session):
    i = _ing(session, "Молоко")
    with pytest.raises(ValueError, match="Раздел не найден"):
        inv.set_ingredient_category(session, i.id, 999)


# --- категории меню -------------------------------------------------------

def _cat_with_products(session, name: str, n: int) -> Category:
    cat = cs.create_category(session, name)
    for k in range(n):
        cs.create_product(session, name=f"{name}-{k}", category_id=cat.id,
                          kind="prepared", price_tiyn=10000)
    return cat


def test_rename_menu_category(session):
    cat = cs.create_category(session, "Кофе")
    cs.rename_category(session, cat.id, "Кофейные напитки")
    assert session.get(Category, cat.id).name == "Кофейные напитки"


def test_delete_empty_menu_category(session):
    cat = cs.create_category(session, "Пустая")
    assert cs.delete_category(session, cat.id) == 0
    assert session.get(Category, cat.id) is None


def test_delete_non_empty_menu_category_requires_target(session):
    """Товар не может остаться без категории — без переноса это отказ,
    иначе удаление уносило бы товары и продажи по ним."""
    cat = _cat_with_products(session, "Обеды", 3)
    with pytest.raises(ValueError, match="выберите, куда"):
        cs.delete_category(session, cat.id)
    assert session.get(Category, cat.id) is not None
    assert session.query(Product).count() == 3


def test_delete_menu_category_moves_products(session):
    src = _cat_with_products(session, "Обеды", 3)
    dst = cs.create_category(session, "Горячее")

    moved = cs.delete_category(session, src.id, move_to_id=dst.id)

    assert moved == 3
    assert session.get(Category, src.id) is None
    assert session.query(Product).count() == 3  # товары целы
    assert session.query(Product).filter(Product.category_id == dst.id).count() == 3


def test_cannot_move_products_into_deleted_category(session):
    cat = _cat_with_products(session, "Обеды", 1)
    with pytest.raises(ValueError, match="в удаляемую"):
        cs.delete_category(session, cat.id, move_to_id=cat.id)
