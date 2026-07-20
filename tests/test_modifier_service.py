import pytest

from app.models import Category, Modifier, ModifierItem, Product, ProductModifierGroup
from app.services import modifier_service as ms


def _product(session):
    cat = Category(name="Кофе")
    session.add(cat)
    session.flush()
    p = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(p)
    session.commit()
    return p


def test_create_group_and_modifier(session):
    grp = ms.create_group(session, "Объём", is_required=True)
    m = ms.add_modifier(session, group_id=grp.id, name="L", price_delta_tiyn=20000)
    assert m.group_id == grp.id
    groups = ms.groups_for_product(session, _product(session).id)
    assert groups == []


def test_attach_group_to_product(session):
    p = _product(session)
    grp = ms.create_group(session, "Объём")
    ms.add_modifier(session, group_id=grp.id, name="M", price_delta_tiyn=0)
    ms.attach_group(session, product_id=p.id, group_id=grp.id)
    groups = ms.groups_for_product(session, p.id)
    assert len(groups) == 1
    g, mods = groups[0]
    assert g.name == "Объём"
    assert [m.name for m in mods] == ["M"]


def test_attach_is_idempotent(session):
    p = _product(session)
    grp = ms.create_group(session, "Молоко")
    ms.attach_group(session, product_id=p.id, group_id=grp.id)
    ms.attach_group(session, product_id=p.id, group_id=grp.id)
    assert session.query(ProductModifierGroup).count() == 1


def test_modifier_ingredient_link(session):
    from app.models import Ingredient
    milk = Ingredient(name="Молоко", unit="мл")
    session.add(milk)
    session.flush()
    grp = ms.create_group(session, "Молоко")
    m = ms.add_modifier(session, group_id=grp.id, name="Овсяное +50мл", price_delta_tiyn=15000)
    ms.set_modifier_item(session, modifier_id=m.id, ingredient_id=milk.id, qty=50)
    item = session.query(ModifierItem).one()
    assert item.qty == 50
