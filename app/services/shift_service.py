from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models import CashCollection, Order, Payment, Refund, Shift, User
from app.models.inventory import utcnow
from app.services import notification_service
from app.timezone import to_almaty


def current_open_shift(session: Session) -> Shift | None:
    return session.scalars(select(Shift).where(Shift.status == "open")).first()


def open_shift(session: Session, *, cashier_id: int, opening_cash_tiyn: int) -> Shift:
    if current_open_shift(session) is not None:
        raise ValueError("Уже есть открытая смена")
    if opening_cash_tiyn < 0:
        raise ValueError("Стартовая наличность не может быть отрицательной")
    cashier = session.get(User, cashier_id)
    if cashier is None:
        raise ValueError(f"Кассир {cashier_id} не найден")
    sh = Shift(cashier_id=cashier_id, opening_cash_tiyn=opening_cash_tiyn, status="open")
    session.add(sh)
    session.flush()
    notification_service.enqueue(
        session, kind="shift_open",
        text=(
            f"Смена открыта: {to_almaty(sh.opened_at):%d.%m.%Y %H:%M}, "
            f"старт {opening_cash_tiyn / 100:.2f} тг, кассир: {cashier.name}"
        ),
    )
    session.commit()
    return sh


def add_collection(session: Session, *, shift_id: int, amount_tiyn: int, note: str | None = None) -> CashCollection:
    if amount_tiyn <= 0:
        raise ValueError("Сумма инкассации должна быть больше нуля")
    sh = session.get(Shift, shift_id)
    if sh is None:
        raise ValueError(f"Смена {shift_id} не найдена")
    cashier = session.get(User, sh.cashier_id)
    if cashier is None:
        raise ValueError(f"Кассир {sh.cashier_id} не найден")
    coll = CashCollection(shift_id=shift_id, amount_tiyn=amount_tiyn, note=note)
    session.add(coll)
    notification_service.enqueue(
        session, kind="collection",
        text=f"Инкассация {amount_tiyn / 100:.2f} тг, смена №{shift_id}, кассир: {cashier.name}",
    )
    session.commit()
    return coll


def _sum(session: Session, stmt) -> int:
    return session.scalar(stmt) or 0


def expected_cash_tiyn(session: Session, shift_id: int) -> int:
    """Ожидаемая наличность = старт + продажи наличными − инкассации − возвраты по наличным чекам."""
    sh = session.get(Shift, shift_id)
    if sh is None:
        raise ValueError(f"Смена {shift_id} не найдена")
    cash_sales = _sum(
        session,
        select(func.sum(Payment.amount_tiyn))
        .join(Order, Order.id == Payment.order_id)
        .where(Order.shift_id == shift_id, Payment.method == "cash"),
    )
    collections = _sum(
        session,
        select(func.sum(CashCollection.amount_tiyn)).where(CashCollection.shift_id == shift_id),
    )
    # В кассе физически лежат только наличные — возврат Kaspi/карты не трогает кассу.
    # Заказ считается "наличным" только если ВСЕ его оплаты — cash (сплит-оплата
    # наличные+безнал сейчас не создаётся из UI, это упрощение задокументировано).
    non_cash_payment = select(Payment.id).where(
        Payment.order_id == Order.id, Payment.method != "cash"
    )
    refunds = _sum(
        session,
        select(func.sum(Refund.amount_tiyn))
        .join(Order, Order.id == Refund.order_id)
        .where(Order.shift_id == shift_id, ~exists(non_cash_payment)),
    )
    return sh.opening_cash_tiyn + cash_sales - collections - refunds


def close_shift(session: Session, *, shift_id: int, counted_cash_tiyn: int) -> Shift:
    sh = session.get(Shift, shift_id)
    if sh is None:
        raise ValueError(f"Смена {shift_id} не найдена")
    if sh.status != "open":
        raise ValueError("Смена уже закрыта")
    sh.expected_cash_tiyn = expected_cash_tiyn(session, shift_id)
    sh.counted_cash_tiyn = counted_cash_tiyn
    sh.closed_at = utcnow()
    sh.status = "closed"
    cashier = session.get(User, sh.cashier_id)
    if cashier is None:
        raise ValueError(f"Кассир {sh.cashier_id} не найден")
    diff = sh.counted_cash_tiyn - sh.expected_cash_tiyn
    notification_service.enqueue(
        session, kind="shift_close",
        text=(
            f"Смена закрыта: {to_almaty(sh.closed_at):%d.%m.%Y %H:%M}, "
            f"ожидалось {sh.expected_cash_tiyn / 100:.2f} тг, "
            f"по факту {sh.counted_cash_tiyn / 100:.2f} тг, расхождение {diff / 100:+.2f} тг, "
            f"кассир: {cashier.name}"
        ),
    )
    session.commit()
    return sh
