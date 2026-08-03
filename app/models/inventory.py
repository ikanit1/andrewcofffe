from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StockMove(Base):
    """Журнал изменений остатка товара. Остаток = сумма qty_delta (кэшируется в Product).

    Ведётся по самому товару меню: отдельных ингредиентов и тех-карт в системе нет,
    склад кофейни — это «сколько круассанов лежит», а не «сколько граммов муки».
    """

    __tablename__ = "stock_moves"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    qty_delta: Mapped[int]  # + приход, − списание
    kind: Mapped[str]  # "purchase" | "sale" | "refund" | "adjustment"
    cost_tiyn: Mapped[int | None] = mapped_column(default=None)  # стоимость движения в тиынах
    ref_type: Mapped[str | None] = mapped_column(default=None)  # напр. "order"
    ref_id: Mapped[int | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
