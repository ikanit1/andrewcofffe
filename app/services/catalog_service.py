from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Product


def create_category(session: Session, name: str, sort_order: int = 0) -> Category:
    cat = Category(name=name, sort_order=sort_order)
    session.add(cat)
    session.commit()
    return cat


def create_product(
    session: Session,
    *,
    name: str,
    category_id: int,
    kind: str,
    price_tiyn: int,
    ingredient_id: int | None = None,
    sort_order: int = 0,
) -> Product:
    if kind not in ("prepared", "retail"):
        raise ValueError(f"Неизвестный тип товара: {kind}")
    if price_tiyn <= 0:
        raise ValueError("Цена должна быть больше нуля")
    p = Product(
        name=name,
        category_id=category_id,
        kind=kind,
        price_tiyn=price_tiyn,
        ingredient_id=ingredient_id,
        sort_order=sort_order,
    )
    session.add(p)
    session.commit()
    return p


def update_product(session: Session, product_id: int, **fields) -> Product:
    p = session.get(Product, product_id)
    if p is None:
        raise ValueError(f"Товар {product_id} не найден")
    if "price_tiyn" in fields and fields["price_tiyn"] <= 0:
        raise ValueError("Цена должна быть больше нуля")
    for k, v in fields.items():
        if not hasattr(p, k):
            raise ValueError(f"Нет поля {k}")
        setattr(p, k, v)
    session.commit()
    return p


def list_menu(session: Session) -> list[tuple[Category, list[Product]]]:
    """Активные категории с активными товарами, в порядке sort_order."""
    cats = session.scalars(
        select(Category).where(Category.is_active).order_by(Category.sort_order, Category.name)
    ).all()
    result = []
    for cat in cats:
        prods = session.scalars(
            select(Product)
            .where(Product.category_id == cat.id, Product.is_active)
            .order_by(Product.sort_order, Product.name)
        ).all()
        result.append((cat, list(prods)))
    return result
