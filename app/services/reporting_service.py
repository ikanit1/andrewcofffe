from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Order, OrderItem, Payment, Product, Refund, Shift, User
from app.timezone import ALMATY, now_almaty, to_almaty


@dataclass
class Period:
    start: datetime  # aware UTC, включительно
    end: datetime    # aware UTC, исключительно


def period_from_preset(preset: str, now: datetime | None = None) -> Period:
    local_now = to_almaty(now) if now is not None else now_almaty()
    today_start = datetime.combine(local_now.date(), time.min, tzinfo=ALMATY)
    today_end = today_start + timedelta(days=1)
    if preset == "today":
        s, e = today_start, today_end
    elif preset == "yesterday":
        s, e = today_start - timedelta(days=1), today_start
    elif preset == "week":
        s, e = today_start - timedelta(days=6), today_end
    elif preset == "month":
        s, e = today_start.replace(day=1), today_end
    else:
        raise ValueError(f"Неизвестный период: {preset}")
    return Period(s.astimezone(timezone.utc), e.astimezone(timezone.utc))


def period_from_dates(start_date: date, end_date: date) -> Period:
    s = datetime.combine(start_date, time.min, tzinfo=ALMATY)
    e = datetime.combine(end_date, time.min, tzinfo=ALMATY) + timedelta(days=1)
    return Period(s.astimezone(timezone.utc), e.astimezone(timezone.utc))


@dataclass
class RevenueByMethod:
    by_method: dict[str, int]
    gross_tiyn: int
    refunds_tiyn: int
    net_tiyn: int
    orders_count: int


@dataclass
class ProductRow:
    name: str
    qty_sold: int
    qty_refunded: int
    qty_net: int
    revenue_tiyn: int


@dataclass
class CategoryRow:
    category: str
    revenue_tiyn: int
    qty_net: int


@dataclass
class CostMargin:
    revenue_tiyn: int
    cogs_tiyn: int
    margin_tiyn: int
    margin_pct: float
    refunds_tiyn: int
    net_revenue_tiyn: int


@dataclass
class ShiftRow:
    shift_id: int
    cashier_name: str
    opened_at: datetime
    closed_at: datetime | None
    orders_count: int
    revenue_tiyn: int
    cogs_tiyn: int
    margin_tiyn: int


@dataclass
class CashierRow:
    cashier_name: str
    shifts_count: int
    orders_count: int
    revenue_tiyn: int
    margin_tiyn: int


@dataclass
class ShiftsReport:
    shifts: list[ShiftRow] = field(default_factory=list)
    by_cashier: list[CashierRow] = field(default_factory=list)


@dataclass
class XReport:
    shift_id: int
    opened_at: datetime
    cashier_name: str
    orders_count: int
    revenue_tiyn: int
    by_method: dict[str, int]
    refunds_tiyn: int
    expected_cash_tiyn: int


def x_report(session: Session) -> XReport | None:
    """Сводка по текущей открытой смене без её закрытия. None — смена не открыта."""
    from app.services.shift_service import current_open_shift, expected_cash_tiyn

    shift = current_open_shift(session)
    if shift is None:
        return None
    orders = session.scalars(select(Order).where(Order.shift_id == shift.id)).all()
    order_ids = [o.id for o in orders]
    revenue = sum(o.total_tiyn for o in orders)
    by_method: dict[str, int] = {}
    refunds = 0
    if order_ids:
        rows = session.execute(
            select(Payment.method, func.sum(Payment.amount_tiyn))
            .where(Payment.order_id.in_(order_ids))
            .group_by(Payment.method)
        ).all()
        by_method = {m: int(t or 0) for m, t in rows}
        refunds = int(session.scalar(
            select(func.coalesce(func.sum(Refund.amount_tiyn), 0))
            .where(Refund.order_id.in_(order_ids))
        ) or 0)
    cashier = session.get(User, shift.cashier_id)
    return XReport(
        shift_id=shift.id, opened_at=shift.opened_at,
        cashier_name=cashier.name if cashier is not None else "?",
        orders_count=len(orders), revenue_tiyn=revenue, by_method=by_method,
        refunds_tiyn=refunds, expected_cash_tiyn=expected_cash_tiyn(session, shift.id),
    )


def _refunds_tiyn(session: Session, period: Period) -> int:
    return int(session.scalar(
        select(func.coalesce(func.sum(Refund.amount_tiyn), 0))
        .where(Refund.created_at >= period.start, Refund.created_at < period.end)
    ) or 0)


def revenue_by_method(session: Session, period: Period) -> RevenueByMethod:
    rows = session.execute(
        select(Payment.method, func.sum(Payment.amount_tiyn))
        .where(Payment.created_at >= period.start, Payment.created_at < period.end)
        .group_by(Payment.method)
    ).all()
    by_method = {m: int(total or 0) for m, total in rows}
    gross = sum(by_method.values())
    refunds = _refunds_tiyn(session, period)
    orders_count = int(session.scalar(
        select(func.count(Order.id))
        .where(Order.created_at >= period.start, Order.created_at < period.end)
    ) or 0)
    return RevenueByMethod(by_method=by_method, gross_tiyn=gross,
                           refunds_tiyn=refunds, net_tiyn=gross - refunds,
                           orders_count=orders_count)


def top_products(session: Session, period: Period, limit: int = 20) -> list[ProductRow]:
    rows = session.execute(
        select(
            OrderItem.name,
            func.sum(OrderItem.qty),
            func.sum(OrderItem.refunded_qty),
            func.sum(OrderItem.line_total_tiyn),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.created_at >= period.start, Order.created_at < period.end)
        .group_by(OrderItem.name)
    ).all()
    result = [
        ProductRow(name=name, qty_sold=int(qty), qty_refunded=int(refunded),
                   qty_net=int(qty) - int(refunded), revenue_tiyn=int(revenue))
        for name, qty, refunded, revenue in rows
    ]
    result.sort(key=lambda r: r.revenue_tiyn, reverse=True)
    return result[:limit]


def revenue_by_category(session: Session, period: Period) -> list[CategoryRow]:
    rows = session.execute(
        select(
            Category.name,
            func.sum(OrderItem.line_total_tiyn),
            func.sum(OrderItem.qty - OrderItem.refunded_qty),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .outerjoin(Product, OrderItem.product_id == Product.id)
        .outerjoin(Category, Product.category_id == Category.id)
        .where(Order.created_at >= period.start, Order.created_at < period.end)
        .group_by(Category.name)
    ).all()
    result = [
        CategoryRow(category=(name or "Без категории"),
                    revenue_tiyn=int(revenue), qty_net=int(qty_net))
        for name, revenue, qty_net in rows
    ]
    result.sort(key=lambda c: c.revenue_tiyn, reverse=True)
    return result


def cost_and_margin(session: Session, period: Period) -> CostMargin:
    revenue = int(session.scalar(
        select(func.coalesce(func.sum(Order.total_tiyn), 0))
        .where(Order.created_at >= period.start, Order.created_at < period.end)
    ) or 0)
    cogs = int(session.scalar(
        select(func.coalesce(func.sum(Order.cost_tiyn), 0))
        .where(Order.created_at >= period.start, Order.created_at < period.end)
    ) or 0)
    refunds = _refunds_tiyn(session, period)
    margin = revenue - cogs
    margin_pct = round(margin / revenue * 100, 1) if revenue else 0.0
    return CostMargin(revenue_tiyn=revenue, cogs_tiyn=cogs, margin_tiyn=margin,
                      margin_pct=margin_pct, refunds_tiyn=refunds,
                      net_revenue_tiyn=revenue - refunds)


def shifts_and_cashiers(session: Session, period: Period) -> ShiftsReport:
    shifts = session.scalars(
        select(Shift)
        .where(Shift.opened_at >= period.start, Shift.opened_at < period.end)
        .order_by(Shift.opened_at)
    ).all()
    rows: list[ShiftRow] = []
    agg: dict[str, list[int]] = {}  # name -> [shifts, orders, revenue, margin]
    for sh in shifts:
        cashier = session.get(User, sh.cashier_id)
        name = cashier.name if cashier is not None else "?"
        oc, revenue, cogs = session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_tiyn), 0),
                func.coalesce(func.sum(Order.cost_tiyn), 0),
            ).where(Order.shift_id == sh.id)
        ).one()
        oc, revenue, cogs = int(oc), int(revenue), int(cogs)
        margin = revenue - cogs
        rows.append(ShiftRow(shift_id=sh.id, cashier_name=name, opened_at=sh.opened_at,
                             closed_at=sh.closed_at, orders_count=oc,
                             revenue_tiyn=revenue, cogs_tiyn=cogs, margin_tiyn=margin))
        a = agg.setdefault(name, [0, 0, 0, 0])
        a[0] += 1
        a[1] += oc
        a[2] += revenue
        a[3] += margin
    by_cashier = [
        CashierRow(cashier_name=name, shifts_count=v[0], orders_count=v[1],
                   revenue_tiyn=v[2], margin_tiyn=v[3])
        for name, v in agg.items()
    ]
    return ShiftsReport(shifts=rows, by_cashier=by_cashier)
