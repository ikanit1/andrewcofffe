from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Product

_PRODUCT_UPDATABLE_FIELDS = {
    "name",
    "category_id",
    "kind",
    "price_tiyn",
    "ingredient_id",
    "sort_order",
    "is_active",
}


def _validate_kind(kind: str) -> None:
    if kind not in ("prepared", "retail"):
        raise ValueError(f"Неизвестный тип товара: {kind}")


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
    _validate_kind(kind)
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
    for k in fields:
        if k not in _PRODUCT_UPDATABLE_FIELDS:
            raise ValueError(f"Нет поля {k}")
    if "kind" in fields:
        _validate_kind(fields["kind"])
    if "price_tiyn" in fields and fields["price_tiyn"] <= 0:
        raise ValueError("Цена должна быть больше нуля")
    for k, v in fields.items():
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
