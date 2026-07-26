from app.models import Category, KaspiSettings, Modifier, ModifierGroup, Product, User
from app.services import modifier_service as ms
from seed import apply_seed


def test_seed_creates_owner_and_cashier(session):
    assert apply_seed(session, 100) is True
    users = {u.role: u for u in session.query(User).all()}
    assert users["admin"].telegram_id == 100
    assert users["cashier"].discount_limit_percent == 10


def test_seed_is_skipped_when_users_exist(session):
    apply_seed(session, 100)
    products_before = session.query(Product).count()
    assert apply_seed(session, 200) is False
    assert session.query(Product).count() == products_before


def test_seed_creates_menu_categories(session):
    apply_seed(session, 100)
    names = [c.name for c in session.query(Category).order_by(Category.sort_order).all()]
    assert names == ["Кофе", "Холодные напитки", "Чай"]


def test_seed_prices_match_the_menu_board(session):
    apply_seed(session, 100)
    price = {p.name: p.price_tiyn for p in session.query(Product).all()}
    assert price["Эспрессо"] == 60000
    assert price["Американо"] == 90000
    assert price["Капучино"] == 110000
    assert price["Флэтуайт"] == 120000
    assert price["Раф"] == 130000
    assert price["Милкшейк"] == 135000
    assert price["Чай классический"] == 40000
    assert price["Чай авторский"] == 100000


def test_seed_attaches_volume_choice_to_double_size_drinks(session):
    apply_seed(session, 100)
    latte = session.query(Product).filter_by(name="Латте").one()
    groups = ms.groups_for_product(session, latte.id)
    assert [g.name for g, _ in groups] == ["Объём"]
    volumes = {m.name: m.price_delta_tiyn for _, mods in groups for m in mods}
    assert volumes == {"0.3 л": 0, "0.4 л": 10000}


def test_seed_espresso_has_no_modifier_groups(session):
    apply_seed(session, 100)
    espresso = session.query(Product).filter_by(name="Эспрессо").one()
    assert ms.groups_for_product(session, espresso.id) == []


def test_seed_lemonade_and_mojito_share_one_flavour_group(session):
    apply_seed(session, 100)
    ids = []
    for name in ("Лимонад", "Мохито"):
        p = session.query(Product).filter_by(name=name).one()
        ids.append([g.id for g, _ in ms.groups_for_product(session, p.id)])
    assert ids[0] == ids[1]


def test_seed_flavour_choices_are_free(session):
    apply_seed(session, 100)
    shake = session.query(ModifierGroup).filter_by(name="Вкус милкшейка").one()
    mods = session.query(Modifier).filter_by(group_id=shake.id).all()
    assert {m.name for m in mods} == {"Ваниль", "Шоколад", "Ягодный", "Клубничный"}
    assert all(m.price_delta_tiyn == 0 for m in mods)


def test_seed_creates_kaspi_settings_row(session):
    apply_seed(session, 100)
    assert session.get(KaspiSettings, 1) is not None
