"""Текстовая сводка за день — для отправки владельцу в Telegram.

Считает по датам, а не по сменам: смену могут забыть закрыть, и тогда
отчёт «по текущей смене» смешает несколько суток. Про такую смену
сводка предупреждает отдельной строкой.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Shift, User
from app.services import reporting_service as rs
from app.timezone import to_almaty

_METHOD_NAMES = {
    "cash": "наличные",
    "card": "карта",
    "kaspi_qr": "Kaspi QR",
    "kaspi_terminal": "Kaspi терминал",
}

_TOP_LIMIT = 5


def _tg(tiyn: int) -> str:
    return f"{tiyn / 100:.2f} тг"


def daily_summary_text(session: Session, *, now: datetime | None = None) -> str:
    period = rs.period_from_preset("today", now)
    day = to_almaty(period.start).strftime("%d.%m.%Y")

    methods = rs.revenue_by_method(session, period)
    lines = [f"Итоги дня {day}", ""]

    if methods.orders_count == 0:
        lines.append("Продаж не было.")
        lines.extend(_open_shift_warning(session, now))
        return "\n".join(lines).rstrip()

    lines.append(f"Чеков: {methods.orders_count}")
    lines.append(f"Выручка: {_tg(methods.gross_tiyn)}")
    if methods.refunds_tiyn:
        lines.append(f"Возвраты: {_tg(methods.refunds_tiyn)}")
        lines.append(f"Итого: {_tg(methods.net_tiyn)}")

    if methods.by_method:
        lines.append("")
        lines.append("Оплата:")
        for method, amount in sorted(methods.by_method.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {_METHOD_NAMES.get(method, method)}: {_tg(amount)}")

    margin = rs.cost_and_margin(session, period)
    lines.append("")
    lines.append(f"Себестоимость: {_tg(margin.cogs_tiyn)}")
    lines.append(f"Маржа: {_tg(margin.margin_tiyn)} ({margin.margin_pct}%)")

    top = rs.top_products(session, period, limit=_TOP_LIMIT)
    if top:
        lines.append("")
        lines.append("Топ товаров:")
        for i, row in enumerate(top, start=1):
            lines.append(f"  {i}. {row.name} — {row.qty_net} шт, {_tg(row.revenue_tiyn)}")

    lines.extend(_open_shift_warning(session, now))
    return "\n".join(lines).rstrip()


def stock_remains_text(session: Session) -> list[str]:
    """Остатки склада по разделам. Позиции ниже порога помечены «!».

    Владельцу нужно видеть не только выручку, но и с чем кассир оставил точку:
    закупку делают вечером, а не утром перед открытием.
    """
    from app.models import Ingredient, StockCategory

    rows = session.scalars(
        select(Ingredient).where(Ingredient.is_active).order_by(Ingredient.name)
    ).all()
    if not rows:
        return []
    sections = {c.id: c.name for c in session.scalars(
        select(StockCategory).order_by(StockCategory.sort_order, StockCategory.name)).all()}

    grouped: dict[int | None, list] = {}
    for ing in rows:
        key = ing.category_id if ing.category_id in sections else None
        grouped.setdefault(key, []).append(ing)

    lines = ["", "Остатки склада:"]
    order = [(cid, sections[cid]) for cid in sections if cid in grouped]
    if None in grouped:
        order.append((None, "Без раздела"))
    for cid, name in order:
        lines.append(f"  {name}")
        for ing in grouped[cid]:
            low = ing.low_stock_threshold > 0 and ing.stock_qty < ing.low_stock_threshold
            mark = " !" if low else ""
            lines.append(f"    {ing.name}: {ing.stock_qty} {ing.unit}{mark}")
    if any(i.low_stock_threshold > 0 and i.stock_qty < i.low_stock_threshold for i in rows):
        lines.append("  ! — ниже порога, пора закупать")
    return lines


def shift_close_summary_text(session: Session, shift, *, now: datetime | None = None) -> str:
    """Сводка после закрытия смены: итоги дня, сверка кассы и остатки склада."""
    from app.models import User

    cashier = session.get(User, shift.cashier_id)
    diff = (shift.counted_cash_tiyn or 0) - (shift.expected_cash_tiyn or 0)

    lines = [daily_summary_text(session, now=now), ""]
    lines.append(f"Смена №{shift.id} закрыта"
                 + (f", кассир: {cashier.name}" if cashier else ""))
    lines.append(f"  Ожидалось в кассе: {_tg(shift.expected_cash_tiyn or 0)}")
    lines.append(f"  По факту: {_tg(shift.counted_cash_tiyn or 0)}")
    lines.append(f"  Расхождение: {diff / 100:+.2f} тг"
                 + ("" if diff == 0 else "  ⚠"))
    lines.extend(stock_remains_text(session))
    return "\n".join(lines).rstrip()


def enqueue_shift_close_summary(session: Session, shift, *, now: datetime | None = None):
    """Кладёт сводку в очередь. Не коммитит — участвует в транзакции закрытия смены."""
    from app.services import notification_service

    return notification_service.enqueue(
        session, kind="shift_summary",
        text=shift_close_summary_text(session, shift, now=now),
    )


def enqueue_daily_summary(session: Session, *, now: datetime | None = None):
    """Кладёт сводку в общую очередь уведомлений — с ретраями и рассылкой всем админам."""
    from app.services import notification_service

    return notification_service.enqueue(
        session, kind="daily_summary", text=daily_summary_text(session, now=now)
    )


async def run_daily_summary_scheduler() -> None:
    """Раз в сутки в settings.daily_summary_time ставит сводку в очередь.

    Время берём то же, что и для отчётов, — Asia/Almaty. Ошибка одного дня
    не должна убивать цикл, иначе сводка молча пропадёт навсегда.
    """
    import asyncio
    import logging

    from app.config import settings
    from app.db import SessionLocal
    from app.models.inventory import utcnow
    from app.services.backup_scheduler import seconds_until

    logger = logging.getLogger(__name__)
    while True:
        await asyncio.sleep(seconds_until(settings.daily_summary_time, to_almaty(utcnow())))
        try:
            with SessionLocal() as session:
                enqueue_daily_summary(session)
                session.commit()
            logger.info("Сводка за день поставлена в очередь")
        except Exception:
            logger.exception("Не удалось подготовить сводку за день")


def _open_shift_warning(session: Session, now: datetime | None) -> list[str]:
    """Предупреждение о смене, открытой раньше сегодняшнего дня."""
    shift = session.scalars(select(Shift).where(Shift.status == "open")).first()
    if shift is None:
        return []
    opened = to_almaty(shift.opened_at)
    today = to_almaty(rs.period_from_preset("today", now).start).date()
    if opened.date() >= today:
        return []
    cashier = session.get(User, shift.cashier_id)
    who = cashier.name if cashier is not None else "?"
    return [
        "",
        f"⚠ Смена №{shift.id} не закрыта с {opened:%d.%m %H:%M} (кассир: {who}).",
        "Пока она открыта, сверка наличности в кассе смешивает несколько дней.",
    ]
