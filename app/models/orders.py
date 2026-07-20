from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inventory import utcnow


class Order(Base):
    """Оплаченный чек. Корзина редактируется в UI; в БД заказ уже проведён."""

    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("shift_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    number: Mapped[int]  # порядковый номер заказа в смене
    status: Mapped[str] = mapped_column(default="paid")  # paid|refunded|partially_refunded
    subtotal_tiyn: Mapped[int]  # сумма строк после позиционных скидок, до скидки на чек
    discount_tiyn: Mapped[int] = mapped_column(default=0)  # скидка на чек
    total_tiyn: Mapped[int]  # итог к оплате
    cost_tiyn: Mapped[int] = mapped_column(default=0)  # снимок себестоимости (COGS)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), default=None)
    name: Mapped[str]  # снимок названия товара
    unit_price_tiyn: Mapped[int]  # цена товара + модификаторы, за единицу, до скидки
    qty: Mapped[int]
    discount_tiyn: Mapped[int] = mapped_column(default=0)  # позиционная скидка, сумма
    line_total_tiyn: Mapped[int]  # unit_price*qty - discount
    unit_cost_tiyn: Mapped[int] = mapped_column(default=0)  # себестоимость за единицу
    refunded_qty: Mapped[int] = mapped_column(default=0)


class OrderItemModifier(Base):
    __tablename__ = "order_item_modifiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"), index=True)
    modifier_id: Mapped[int | None] = mapped_column(ForeignKey("modifiers.id"), default=None)
    name: Mapped[str]  # снимок названия модификатора
    price_delta_tiyn: Mapped[int] = mapped_column(default=0)
