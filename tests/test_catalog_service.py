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


def test_new_product_starts_without_stock_tracking(session):
    """Новый товар не считается, пока владелец не заведёт остаток на складе."""
    cat = cs.create_category(session, "Снеки")
    p = cs.create_product_with_stock(session, name="Кола", category_id=cat.id,
                                     kind="retail", price_tiyn=50000)
    assert p.stock_qty is None
    assert (p.low_stock_threshold, p.cost_tiyn) == (0, 0)


def test_sale_deducts_stock_only_when_it_is_tracked(session):
    from app.models import Shift, User
    from app.services import sales_service as sales
    from app.services.pricing import PaymentInput

    cat = cs.create_category(session, "Снеки")
    tracked = cs.create_product(session, name="Кола", category_id=cat.id,
                                kind="retail", price_tiyn=50000)
    free = cs.create_product(session, name="Латте", category_id=cat.id,
                             kind="prepared", price_tiyn=110000)
    tracked.stock_qty = 10
    session.commit()

    u = User(telegram_id=1, name="Кассир", role="cashier")
    session.add(u)
    session.flush()
    session.add(Shift(cashier_id=u.id, opening_cash_tiyn=0, status="open"))
    session.commit()

    sales.create_sale(session, cashier_id=u.id,
                      lines=[sales.SaleLineInput(product_id=tracked.id, qty=2),
                             sales.SaleLineInput(product_id=free.id, qty=1)],
                      payments=[PaymentInput("cash", 210000, 210000)])

    assert session.get(Product, tracked.id).stock_qty == 8
    assert session.get(Product, free.id).stock_qty is None


def test_delete_product_removes_it_with_stock_journal_and_modifier_links(session):
    from app.models import ModifierGroup, ProductModifierGroup

    from app.models import StockMove

    cat = cs.create_category(session, "Кофе")
    grp = ModifierGroup(name="Объём", is_required=True)
    session.add(grp)
    session.flush()
    p = cs.create_product(session, name="Латте", category_id=cat.id,
                          kind="prepared", price_tiyn=110000)
    session.add_all([
        StockMove(product_id=p.id, qty_delta=10, kind="purchase"),
        ProductModifierGroup(product_id=p.id, group_id=grp.id),
    ])
    session.commit()

    cs.delete_product(session, p.id)

    assert session.get(Product, p.id) is None
    assert session.query(StockMove).filter_by(product_id=p.id).count() == 0
    assert session.query(ProductModifierGroup).filter_by(product_id=p.id).count() == 0


def test_delete_product_refuses_when_it_was_sold(session):
    """Удалить проданный товар нельзя: строки чеков ссылаются на него, и без
    этой связи прошлые продажи перестали бы попадать в свою категорию —
    отчёты за закрытые периоды задним числом изменились бы."""
    from app.models import Order, OrderItem, Shift, User

    cat = cs.create_category(session, "Кофе")
    p = cs.create_product(session, name="Латте", category_id=cat.id,
                          kind="prepared", price_tiyn=110000)
    u = User(telegram_id=1, name="Кассир", role="cashier")
    session.add(u); session.flush()
    sh = Shift(cashier_id=u.id, status="closed", opening_cash_tiyn=0)
    session.add(sh); session.flush()
    o = Order(shift_id=sh.id, number=1, status="paid", subtotal_tiyn=110000,
              total_tiyn=110000)
    session.add(o); session.flush()
    session.add(OrderItem(order_id=o.id, product_id=p.id, name="Латте",
                          unit_price_tiyn=110000, qty=1, line_total_tiyn=110000))
    session.commit()

    with pytest.raises(ValueError, match="продавался"):
        cs.delete_product(session, p.id)
    assert session.get(Product, p.id) is not None


def test_delete_product_reports_unknown_id(session):
    with pytest.raises(ValueError):
        cs.delete_product(session, 4242)


def test_product_can_be_deleted_regardless_of_kind(session):
    cat = cs.create_category(session, "Снеки")
    retail = cs.create_product(session, name="Кола", category_id=cat.id,
                               kind="retail", price_tiyn=50000)
    cs.delete_product(session, retail.id)
    assert session.get(Product, retail.id) is None
