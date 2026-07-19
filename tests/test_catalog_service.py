import pytest

from app.models import Category, Product
from app.services import catalog_service as cs


def test_create_and_list_menu(session):
    cat = cs.create_category(session, "Чай")
    p = cs.create_product(session, name="Пуэр", category_id=cat.id, kind="prepared", price_tiyn=120000)
    menu = cs.list_menu(session)
    assert menu == [(cat, [p])]


def test_update_price(session):
    cat = cs.create_category(session, "Снеки")
    p = cs.create_product(session, name="Круассан", category_id=cat.id, kind="retail", price_tiyn=90000)
    cs.update_product(session, p.id, price_tiyn=95000)
    assert session.get(Product, p.id).price_tiyn == 95000


def test_retail_requires_positive_price(session):
    cat = cs.create_category(session, "Банки")
    with pytest.raises(ValueError):
        cs.create_product(session, name="Кола", category_id=cat.id, kind="retail", price_tiyn=0)


def test_deactivate_hides_from_menu(session):
    cat = cs.create_category(session, "Кофе")
    p = cs.create_product(session, name="Раф", category_id=cat.id, kind="prepared", price_tiyn=160000)
    cs.update_product(session, p.id, is_active=False)
    assert cs.list_menu(session) == [(cat, [])]
