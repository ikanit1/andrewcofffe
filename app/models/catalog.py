from sqlalchemy import ForeignKey, LargeBinary, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    kind: Mapped[str]  # "prepared" (по тех-карте) | "retail" (штучный)
    price_tiyn: Mapped[int]
    inventory_policy: Mapped[str] = mapped_column(default="track")
    # для retail-товара — складская позиция, которая списывается поштучно
    ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredients.id"), default=None)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    # Фото товара хранится в БД (попадает в бэкап). Блоб отложенный — не грузится
    # в обычных выборках меню; has_image — дешёвый флаг для показа плитки.
    image: Mapped[bytes | None] = mapped_column(LargeBinary, default=None, deferred=True)
    image_mime: Mapped[str | None] = mapped_column(default=None)
    has_image: Mapped[bool] = mapped_column(default=False)


class ModifierGroup(Base):
    __tablename__ = "modifier_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    is_required: Mapped[bool] = mapped_column(default=False)


class Modifier(Base):
    __tablename__ = "modifiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id"))
    name: Mapped[str]
    price_delta_tiyn: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class ModifierItem(Base):
    """Списание ингредиентов, которое добавляет модификатор (сироп +30 мл и т.п.)."""

    __tablename__ = "modifier_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    modifier_id: Mapped[int] = mapped_column(ForeignKey("modifiers.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    qty: Mapped[int]  # в базовых единицах ингредиента (г/мл/шт)


class ProductModifierGroup(Base):
    __tablename__ = "product_modifier_groups"
    __table_args__ = (UniqueConstraint("product_id", "group_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id"))
