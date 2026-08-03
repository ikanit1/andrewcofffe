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
    kind: Mapped[str]  # "prepared" (готовится) | "retail" (штучный)
    price_tiyn: Mapped[int]
    # Остаток в штуках самого товара. None — «не считаем»: у кофе, который варят
    # из общих запасов, количества не существует, и ноль там врал бы сильнее,
    # чем пустая ячейка. Заполнили число — товар начинает списываться продажами.
    stock_qty: Mapped[int | None] = mapped_column(default=None)
    low_stock_threshold: Mapped[int] = mapped_column(default=0)  # 0 = не предупреждать
    low_stock_notified: Mapped[bool] = mapped_column(default=False)
    cost_tiyn: Mapped[int] = mapped_column(default=0)  # закупочная цена за штуку
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


class ProductModifierGroup(Base):
    __tablename__ = "product_modifier_groups"
    __table_args__ = (UniqueConstraint("product_id", "group_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id"))
