from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Ingredient, Order, OrderItem, Payment, Product, Refund, User
from app.services import reporting_service as rs
from app.services import shift_service as ss
from app.timezone import now_almaty, to_almaty, today_bounds_utc

# Сколько прошлых тех же дней недели берём за ориентир дневного плана. Именно
# день недели, а не последние N дней подряд: суббота в кофейне даёт другую
# выручку, чем вторник, и «средняя за неделю» занижала бы план на выходных.
PLAN_WEEKS = 4
# Сколько строк показываем в списках правой колонки — дальше карточка вытягивает
# страницу, а смысла в хвосте нет: за подробностями владелец идёт в отчёты.
TOP_LIMIT = 6
RECENT_LIMIT = 6
STOCK_LIMIT = 6
# Рабочее окно графика по часам, когда продаж нет ни сегодня, ни вчера: без него
# пустой дашборд рисовал бы все 24 столбца, включая ночь.
_DEFAULT_HOURS = (8, 21)


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
    order_ids = [o.id for o in orders]
    gross_revenue = sum(o.total_tiyn for o in orders)
    refunded_amount = 0
    items_count = 0
    if order_ids:
        refunded_amount = session.scalar(
            select(func.sum(Refund.amount_tiyn)).where(Refund.order_id.in_(order_ids))
        ) or 0
        items_count = session.scalar(
            select(func.sum(OrderItem.qty - OrderItem.refunded_qty))
            .where(OrderItem.order_id.in_(order_ids))
        ) or 0
    return TodaySummary(
        revenue_tiyn=gross_revenue - refunded_amount,
        orders_count=len(orders),
        items_count=items_count,
    )


def low_stock_ingredients(session: Session) -> list[Ingredient]:
    return list(session.scalars(
        select(Ingredient)
        .where(Ingredient.is_active, Ingredient.stock_qty < Ingredient.low_stock_threshold)
        .order_by(Ingredient.name)
    ).all())


# --------------------------------------------------------------------------
# Дашборд: один снимок за один заход в базу
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ShiftLine:
    """Строка состояния под заголовком: какая смена и сколько уже идёт."""

    shift_id: int
    cashier_name: str
    opened_at: datetime  # уже местное время
    elapsed: timedelta


@dataclass(frozen=True)
class HourBar:
    hour: int
    today_tiyn: int
    yesterday_tiyn: int
    orders_count: int
    is_future: bool


@dataclass(frozen=True)
class DayPlan:
    """Ориентир на день, посчитанный по прошлым тем же дням недели.

    norm_pct — какая доля выручки к этому часу набиралась в те дни. Без неё
    процент выполнения ни о чём не говорит: 40% плана в 10 утра — это хорошо,
    а в 19 вечера — провал.
    """

    target_tiyn: int
    revenue_tiyn: int
    done_pct: int
    norm_pct: int
    basis_days: int

    @property
    def ahead(self) -> bool:
        return self.done_pct >= self.norm_pct

    @property
    def left_tiyn(self) -> int:
        return max(0, self.target_tiyn - self.revenue_tiyn)


@dataclass(frozen=True)
class TopProduct:
    name: str
    category: str
    qty: int
    revenue_tiyn: int


@dataclass(frozen=True)
class MethodRow:
    method: str
    amount_tiyn: int
    orders_count: int


@dataclass(frozen=True)
class StockRow:
    name: str
    unit: str
    stock_qty: int
    threshold: int

    @property
    def pct(self) -> int:
        if self.threshold <= 0:
            return 100
        return min(100, max(0, round(self.stock_qty / self.threshold * 100)))

    @property
    def is_low(self) -> bool:
        return self.stock_qty < self.threshold


@dataclass(frozen=True)
class Dashboard:
    day: date
    now: datetime                     # местное время сборки снимка
    shift: ShiftLine | None
    today: rs.Summary
    yesterday: rs.Summary             # вчера к этому же часу — база для «ко вчера»
    refunded_orders_count: int
    plan: DayPlan | None
    hours: tuple[HourBar, ...]
    peak: HourBar | None
    last_receipt_at: datetime | None
    top: tuple[TopProduct, ...]
    recent: tuple[rs.Receipt, ...]
    cash: ss.CashBreakdown | None
    methods: tuple[MethodRow, ...]
    stock: tuple[StockRow, ...]
    week: tuple[rs.DayRow, ...]

    @property
    def cash_share_pct(self) -> int:
        if self.cash is None or not self.today.gross_tiyn:
            return 0
        return round(self.cash.cash_sales_tiyn / self.today.gross_tiyn * 100)


def _period(start_local: datetime, end_local: datetime) -> rs.Period:
    return rs.Period(start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc))


def _refunded_orders_count(session: Session, period: rs.Period) -> int:
    """Сколько чеков задето возвратами. Именно чеков, а не возвратов: по одному
    чеку могут оформить несколько частичных, и «3 возврата» ввело бы в заблуждение."""
    return int(session.scalar(
        select(func.count(func.distinct(Refund.order_id)))
        .where(Refund.created_at >= period.start, Refund.created_at < period.end)
    ) or 0)


def _top_products(session: Session, period: rs.Period, limit: int) -> list[TopProduct]:
    """Топ товаров с названием категории — в отличие от reporting_service.top_products,
    который категорию не знает, а на дашборде она отличает «Латте» от одноимённого сиропа."""
    rows = session.execute(
        select(
            OrderItem.name,
            func.coalesce(Category.name, "Без категории"),
            func.sum(OrderItem.qty - OrderItem.refunded_qty),
            func.sum(OrderItem.line_total_tiyn),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .outerjoin(Product, OrderItem.product_id == Product.id)
        .outerjoin(Category, Product.category_id == Category.id)
        .where(Order.created_at >= period.start, Order.created_at < period.end)
        .group_by(OrderItem.name, Category.name)
    ).all()
    top = [
        TopProduct(name=name, category=cat, qty=int(qty or 0), revenue_tiyn=int(revenue or 0))
        for name, cat, qty, revenue in rows
    ]
    top.sort(key=lambda p: p.revenue_tiyn, reverse=True)
    return top[:limit]


def _methods(session: Session, period: rs.Period) -> list[MethodRow]:
    rows = session.execute(
        select(
            Payment.method,
            func.sum(Payment.amount_tiyn),
            func.count(func.distinct(Payment.order_id)),
        )
        .where(Payment.created_at >= period.start, Payment.created_at < period.end)
        .group_by(Payment.method)
    ).all()
    result = [
        MethodRow(method=method, amount_tiyn=int(amount or 0), orders_count=int(count or 0))
        for method, amount, count in rows
    ]
    result.sort(key=lambda m: m.amount_tiyn, reverse=True)
    return result


def _stock_rows(session: Session, limit: int) -> list[StockRow]:
    """Позиции с заданным порогом, ближайшие к нулю первыми.

    Позиции без порога (threshold = 0) пропускаем: отслеживание по ним выключено
    владельцем, и показывать их «в норме» значило бы обещать контроль, которого нет.
    """
    rows = session.scalars(
        select(Ingredient)
        .where(Ingredient.is_active, Ingredient.low_stock_threshold > 0)
    ).all()
    stock = [
        StockRow(name=i.name, unit=i.unit, stock_qty=i.stock_qty,
                 threshold=i.low_stock_threshold)
        for i in rows
    ]
    stock.sort(key=lambda s: s.pct)
    return stock[:limit]


def _hours(today_rows: list[rs.HourRow], yesterday_rows: list[rs.HourRow],
           now_hour: int) -> list[HourBar]:
    """Окно графика — только часы, в которые хоть когда-то торговали.

    Границы берём по продажам за оба дня и обязательно включаем текущий час:
    иначе в начале смены график схлопывался бы в один столбец, а пустая ночь
    занимала бы две трети карточки.
    """
    active = [h.hour for h in today_rows + yesterday_rows if h.revenue_tiyn]
    if active:
        first, last = min(active), max(active)
    else:
        first, last = _DEFAULT_HOURS
    first, last = min(first, now_hour), max(last, now_hour)
    by_hour_y = {h.hour: h for h in yesterday_rows}
    return [
        HourBar(
            hour=h.hour,
            today_tiyn=h.revenue_tiyn,
            yesterday_tiyn=by_hour_y[h.hour].revenue_tiyn if h.hour in by_hour_y else 0,
            orders_count=h.orders_count,
            is_future=h.hour > now_hour,
        )
        for h in today_rows if first <= h.hour <= last
    ]


def _day_plan(session: Session, day: date, *, revenue_tiyn: int,
              now_hour: int) -> DayPlan | None:
    """Ориентир на день по прошлым тем же дням недели. None — сравнивать не с чем.

    Дни без выручки в расчёт не берём: закрытый на ремонт понедельник обнулил бы
    план на все следующие понедельники.
    """
    totals: list[int] = []
    to_now: list[int] = []
    for back in range(1, PLAN_WEEKS + 1):
        past = day - timedelta(days=7 * back)
        rows = rs.revenue_by_hour(session, past)
        total = sum(h.revenue_tiyn for h in rows)
        if not total:
            continue
        totals.append(total)
        to_now.append(sum(h.revenue_tiyn for h in rows if h.hour <= now_hour))
    if not totals:
        return None
    target = round(sum(totals) / len(totals))
    if target <= 0:
        return None
    norm = round(sum(to_now) / sum(totals) * 100)
    return DayPlan(
        target_tiyn=target,
        revenue_tiyn=revenue_tiyn,
        done_pct=min(100, round(revenue_tiyn / target * 100)),
        norm_pct=min(100, norm),
        basis_days=len(totals),
    )


def dashboard(session: Session, *, now: datetime | None = None) -> Dashboard:
    """Снимок дашборда целиком: собирается разом, чтобы экран не дёргал базу по частям.

    Всё считается за календарные сутки Алматы, а не за смену: смена может быть
    открыта со вчерашнего вечера, и «выручка смены» тогда не сходится ни с одним
    отчётом за день. Смена показывается отдельной строкой состояния, и по ней же
    считается ящик — наличные лежат именно в открытой смене.
    """
    local_now = to_almaty(now) if now is not None else now_almaty()
    day = local_now.date()
    yesterday = day - timedelta(days=1)
    now_hour = local_now.hour

    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_period = _period(day_start, local_now)
    # Вчера ровно до этого же момента суток: сравнивать неполный день с полным
    # значило бы каждое утро показывать «−80% ко вчера».
    yesterday_period = _period(day_start - timedelta(days=1), local_now - timedelta(days=1))

    today = rs.summary(session, today_period)
    yesterday_summary = rs.summary(session, yesterday_period)

    shift_line = None
    cash = None
    shift = ss.current_open_shift(session)
    if shift is not None:
        cashier = session.get(User, shift.cashier_id)
        opened_local = to_almaty(shift.opened_at)
        shift_line = ShiftLine(
            shift_id=shift.id,
            cashier_name=cashier.name if cashier is not None else "неизвестен",
            opened_at=opened_local,
            elapsed=local_now - opened_local,
        )
        cash = ss.cash_breakdown(session, shift.id)

    hours = _hours(rs.revenue_by_hour(session, day),
                   rs.revenue_by_hour(session, yesterday), now_hour)
    sold = [h for h in hours if h.today_tiyn]
    peak = max(sold, key=lambda h: h.today_tiyn) if sold else None

    receipts = rs.day_receipts(session, day)
    week = rs.revenue_by_day(session, _period(day_start - timedelta(days=6),
                                              day_start + timedelta(days=1)))

    return Dashboard(
        day=day,
        now=local_now,
        shift=shift_line,
        today=today,
        yesterday=yesterday_summary,
        refunded_orders_count=_refunded_orders_count(session, today_period),
        plan=_day_plan(session, day, revenue_tiyn=today.gross_tiyn, now_hour=now_hour),
        hours=tuple(hours),
        peak=peak,
        last_receipt_at=receipts[-1].at if receipts else None,
        top=tuple(_top_products(session, today_period, TOP_LIMIT)),
        recent=tuple(reversed(receipts[-RECENT_LIMIT:])),
        cash=cash,
        methods=tuple(_methods(session, today_period)),
        stock=tuple(_stock_rows(session, STOCK_LIMIT)),
        week=tuple(week),
    )
