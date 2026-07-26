import pytest

from app.models import Category, Product
from app.services import catalog_service as cs


def test_create_and_list_menu(session):
    cat = cs.create_category(session, "Чай")
    p = cs.create_product(session, name="Пуэр", category_id=cat.id, kind="prepared", price_tiyn=120000)
    menu = cs.list_menu(session)
    assert menu == [(cat, [p])]


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_product_image_roundtrip(session):
    cat = cs.create_category(session, "Кофе")
    p = cs.create_product(session, name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    assert p.has_image is False
    cs.set_product_image(session, p.id, PNG_BYTES, "image/png")
    assert cs.get_product_image(session, p.id) == (PNG_BYTES, "image/png")
    assert session.get(Product, p.id).has_image is True
    cs.clear_product_image(session, p.id)
    assert cs.get_product_image(session, p.id) is None
    assert session.get(Product, p.id).has_image is False


def test_set_product_image_rejects_non_image(session):
    """Валидация в сервисе, а не только в UI: маршрут отдаёт файл обратно
    с сохранённым типом, и SVG со скриптом стал бы хранимым XSS."""
    cat = cs.create_category(session, "Кофе")
    p = cs.create_product(session, name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(ValueError):
        cs.set_product_image(session, p.id, svg, "image/svg+xml")
    assert session.get(Product, p.id).has_image is False


def test_set_product_image_stores_detected_mime_not_claimed(session):
    cat = cs.create_category(session, "Кофе")
    p = cs.create_product(session, name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    cs.set_product_image(session, p.id, PNG_BYTES, "text/html")
    _, mime = cs.get_product_image(session, p.id)
    assert mime == "image/png"


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


def test_list_menu_admin_includes_hidden_products(session):
    """В отличие от list_menu (для кассы), админский список должен видеть скрытые
    товары — иначе их нельзя ни показать приглушёнными, ни вернуть в меню."""
    cat = cs.create_category(session, "Кофе")
    visible = cs.create_product(session, name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    hidden = cs.create_product(session, name="Раф", category_id=cat.id, kind="prepared", price_tiyn=160000)
    cs.update_product(session, hidden.id, is_active=False)

    menu = cs.list_menu_admin(session)

    assert len(menu) == 1
    got_cat, products = menu[0]
    assert got_cat.id == cat.id
    assert {p.id for p in products} == {visible.id, hidden.id}
    by_id = {p.id: p for p in products}
    assert by_id[visible.id].is_active is True
    assert by_id[hidden.id].is_active is False


def test_list_menu_admin_only_lists_active_categories(session):
    cat = cs.create_category(session, "Кофе")
    hidden_cat = cs.create_category(session, "Архив")
    cs.create_product(session, name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    hidden_cat.is_active = False
    session.commit()

    menu = cs.list_menu_admin(session)

    assert [c.id for c, _ in menu] == [cat.id]
