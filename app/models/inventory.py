from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Ingredient(Base):
    """Складская позиция: ингредиент (г/мл) или штучный товар (шт)."""

    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    unit: Mapped[str]  # "г" | "мл" | "шт"
    stock_qty: Mapped[int] = mapped_column(default=0)  # кэш остатка в базовых единицах
    avg_cost_tiyn: Mapped[float] = mapped_column(default=0.0)  # тиын за базовую единицу
    low_stock_threshold: Mapped[int] = mapped_column(default=0)  # 0 = отслеживание низкого остатка выключено
    low_stock_notified: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)


class RecipeItem(Base):
    """Строка тех-карты: сколько ингредиента уходит на 1 порцию товара."""

    __tablename__ = "recipe_items"
    __table_args__ = (UniqueConstraint("product_id", "ingredient_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    qty: Mapped[int]  # базовые единицы ингредиента


class StockMove(Base):
    """Журнал движений склада. Остаток = сумма qty_delta (кэшируется в Ingredient)."""

    __tablename__ = "stock_moves"

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    qty_delta: Mapped[int]  # + приход, − списание
    kind: Mapped[str]  # "purchase" | "sale" | "refund" | "adjustment"
    cost_tiyn: Mapped[int | None] = mapped_column(default=None)  # стоимость движения в тиынах
    ref_type: Mapped[str | None] = mapped_column(default=None)  # напр. "order"
    ref_id: Mapped[int | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
