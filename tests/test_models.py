from app.models import (
    Category,
    Modifier,
    ModifierGroup,
    Product,
    ProductModifierGroup,
    User,
)


def test_user_roundtrip(session):
    u = User(telegram_id=111, name="Айгерим", role="cashier")
    session.add(u)
    session.commit()
    got = session.query(User).filter_by(telegram_id=111).one()
    assert got.role == "cashier"
    assert got.is_active is True
    assert got.discount_limit_percent == 10


def test_product_with_modifiers(session):
    cat = Category(name="Кофе", sort_order=1)
    session.add(cat)
    session.flush()

    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(latte)
    session.flush()

    sizes = ModifierGroup(name="Объём", is_required=True)
    session.add(sizes)
    session.flush()
    session.add_all([
        Modifier(group_id=sizes.id, name="M", price_delta_tiyn=0),
        Modifier(group_id=sizes.id, name="L", price_delta_tiyn=20000),
        ProductModifierGroup(product_id=latte.id, group_id=sizes.id),
    ])
    session.commit()

    groups = (
        session.query(ModifierGroup)
        .join(ProductModifierGroup, ProductModifierGroup.group_id == ModifierGroup.id)
        .filter(ProductModifierGroup.product_id == latte.id)
        .all()
    )
    assert [g.name for g in groups] == ["Объём"]
    mods = session.query(Modifier).filter_by(group_id=sizes.id).all()
    assert {m.name for m in mods} == {"M", "L"}
