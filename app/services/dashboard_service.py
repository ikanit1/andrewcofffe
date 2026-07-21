from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ingredient, Order, OrderItem
from app.timezone import today_bounds_utc


@dataclass
class TodaySummary:
    revenue_tiyn: int
    orders_count: int
    items_count: int


def today_summary(session: Session, *, now: datetime | None = None) -> TodaySummary:
    start_utc, end_utc = today_bounds_utc(now)
    orders = session.scalars(
        select(Order).where(
            Order.created_at >= start_utc,
            Order.created_at < end_utc,
            Order.status != "refunded",
        )
    ).all()
    revenue = sum(o.total_tiyn for o in orders)
    order_ids = [o.id for o in orders]
    items_count = 0
    if order_ids:
        items_count = session.scalar(
            select(func.sum(OrderItem.qty - OrderItem.refunded_qty))
            .where(OrderItem.order_id.in_(order_ids))
        ) or 0
    return TodaySummary(revenue_tiyn=revenue, orders_count=len(orders), items_count=items_count)


def low_stock_ingredients(session: Session) -> list[Ingredient]:
    return list(session.scalars(
        select(Ingredient)
        .where(Ingredient.is_active, Ingredient.stock_qty < Ingredient.low_stock_threshold)
        .order_by(Ingredient.name)
    ).all())
