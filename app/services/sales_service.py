from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Modifier,
    Order,
    OrderItem,
    OrderItemModifier,
    Payment,
    Product,
    Refund,
    RefundItem,
    User,
)
from app.services import (costing, modifier_service, notification_service, pricing,
                          promo)
from app.services.inventory_service import apply_move
from app.services.pricing import CartLine, PaymentInput
from app.services.shift_service import current_open_shift
from app.timezone import to_almaty

_METHOD_LABELS = {"cash": "Наличные", "card": "Карта",
                  "kaspi_qr": "Kaspi QR", "kaspi_terminal": "Kaspi (терминал)"}


class PriceChanged(Exception):
    """Цена изменилась между сбором корзины и проведением чека.

    Отдельный тип, а не общий ValueError: причина не в кассире, а в том, что
    под ним поменялись цены — чаще всего началась или кончилась акция. Отличать
    это от ошибки со сдачей обязательно, иначе кассир получает сообщение
    про несходящуюся оплату и не понимает, что делать.
    """

    def __init__(self, expected_tiyn: int, actual_tiyn: int) -> None:
        self.expected_tiyn = expected_tiyn
        self.actual_tiyn = actual_tiyn
        direction = "выросла" if actual_tiyn > expected_tiyn else "снизилась"
        super().__init__(
            f"Цена {direction}, пока собирали чек: было {expected_tiyn / 100:.0f} тг, "
            f"стало {actual_tiyn / 100:.0f} тг. Проверьте чек и проведите заново."
        )


@dataclass
class SaleLineInput:
    product_id: int
    qty: int = 1
    modifier_ids: list[int] = field(default_factory=list)
    discount_kind: str | None = None
    discount_value: int = 0


def _resolve_lines(session: Session, lines: list[SaleLineInput], *,
                   limit: int, discount_approved: bool) -> list[tuple]:
    """Проверяет позиции и считает их цены. Общее для оценки и для проведения:
    разойтись они не должны, иначе терминал спишет одну сумму, а чек уйдёт с другой."""
    resolved = []  # (SaleLineInput, Product, [Modifier], CartLine)
    for li in lines:
        if li.qty <= 0:
            raise ValueError("Количество должно быть больше нуля")
        product = session.get(Product, li.product_id)
        if product is None or not product.is_active:
            raise ValueError(f"Товар {li.product_id} недоступен")
        mods = []
        for mid in li.modifier_ids:
            m = session.get(Modifier, mid)
            if m is None or not m.is_active:
                raise ValueError(f"Модификатор {mid} недоступен")
            mods.append(m)
        chosen_ids = set(li.modifier_ids)
        for group, group_mods in modifier_service.groups_for_product(session, product.id):
            if group.is_required and not (chosen_ids & {m.id for m in group_mods}):
                raise ValueError(f"Не выбрана обязательная группа: {group.name}")
        cart_line = CartLine(
            # Цену с учётом акции считает сервер по своим часам: браузер кассира
            # мог бы показать акционную цену за минуту до её начала или после конца.
            base_price_tiyn=promo.effective_price_tiyn(product),
            qty=li.qty,
            unit_cost_tiyn=costing.unit_cost_tiyn(session, product, li.modifier_ids),
            modifier_price_deltas=[m.price_delta_tiyn for m in mods],
            discount_kind=li.discount_kind,
            discount_value=li.discount_value,
        )
        # проверка лимита скидки кассира (позиция) — точное сравнение без округления
        line_gross = pricing.line_unit_price_tiyn(cart_line) * cart_line.qty
        if not discount_approved and not pricing.discount_within_limit_tiyn(
            line_gross, pricing.line_discount_tiyn(cart_line), limit
        ):
            raise PermissionError("Скидка превышает лимит кассира")
        resolved.append((li, product, mods, cart_line))
    return resolved


def quote_total_tiyn(session: Session, *, lines: list[SaleLineInput],
                     order_discount_kind: str | None = None,
                     order_discount_value: int = 0) -> int:
    """Итог чека по текущим ценам, ничего не записывая.

    Нужна там, где деньги списываются до проведения чека — оплата через
    терминал Kaspi. Узнать об изменившейся цене после списания значит оставить
    гостя с оплатой и без чека, поэтому сверяемся заранее.
    """
    resolved = _resolve_lines(session, lines, limit=100, discount_approved=True)
    cart_lines = [r[3] for r in resolved]
    subtotal = pricing.order_subtotal_tiyn(cart_lines)
    order_disc = pricing.order_discount_tiyn(subtotal, order_discount_kind,
                                             order_discount_value)
    return pricing.order_total_tiyn(subtotal, order_disc)


def _next_order_number(session: Session, shift_id: int) -> int:
    last = session.scalar(
        select(func.max(Order.number)).where(Order.shift_id == shift_id)
    )
    return (last or 0) + 1


def _stock_note(session: Session, product: Product) -> str:
    """Остаток по товару для уведомления — только если товар вообще считается.

    Про товары без учёта молчим: у кофе из общих запасов количества нет, и
    приписка «склад не списан» к каждой чашке была бы шумом, а не сигналом.
    """
    if product.stock_qty is None:
        return ""
    if product.stock_qty < 0:
        return f" ⚠ остаток {product.stock_qty} шт — продано больше, чем было"
    return f" (остаток {product.stock_qty} шт)"


def _sale_notification_text(session: Session, order: Order, resolved,
                            payments: list[PaymentInput], cashier: User) -> str:
    """Текст уведомления о продаже: состав чека, остатки, сумма, способ, время."""
    items = "\n".join(
        f"• {product.name}"
        + (f" ({', '.join(m.name for m in mods)})" if mods else "")
        + f" ×{li.qty}"
        + _stock_note(session, product)
        for li, product, mods, _ in resolved
    )
    if len(payments) == 1:
        pay_text = _METHOD_LABELS.get(payments[0].method, payments[0].method)
    else:
        # разделённая оплата — показываем сумму по каждому способу
        pay_text = " + ".join(
            f"{_METHOD_LABELS.get(p.method, p.method)} {p.amount_tiyn / 100:.2f} тг"
            for p in payments
        )
    when = to_almaty(order.created_at).strftime("%d.%m.%Y %H:%M")
    return (
        f"Продажа №{order.number} — {order.total_tiyn / 100:.2f} тг\n"
        f"{items}\n"
        f"Оплата: {pay_text}\n"
        f"{when}, кассир: {cashier.name}"
    )


def create_sale(
    session: Session,
    *,
    cashier_id: int,
    lines: list[SaleLineInput],
    payments: list[PaymentInput],
    order_discount_kind: str | None = None,
    order_discount_value: int = 0,
    discount_approved: bool = False,
    expected_total_tiyn: int | None = None,
) -> Order:
    """Атомарно проводит чек: заказ + позиции + модификаторы + оплаты + списание склада.

    Всё в одной транзакции — при любой ошибке откат, склад и заказ не меняются.

    expected_total_tiyn — итог, который показывала корзина. Если он не сошёлся
    с пересчитанным, бросается PriceChanged: цена изменилась под кассиром
    (началась или кончилась акция), и чек нужно пересобрать.
    """
    if not lines:
        raise ValueError("Чек не может быть пустым")
    shift = current_open_shift(session)
    if shift is None:
        raise ValueError("Нет открытой смены")
    cashier = session.get(User, cashier_id)
    if cashier is None:
        raise ValueError(f"Кассир {cashier_id} не найден")
    limit = cashier.discount_limit_percent

    resolved = _resolve_lines(session, lines, limit=limit,
                              discount_approved=discount_approved)

    cart_lines = [r[3] for r in resolved]
    line_totals = [pricing.line_total_tiyn(cl) for cl in cart_lines]
    subtotal = pricing.order_subtotal_tiyn(cart_lines)
    order_disc = pricing.order_discount_tiyn(subtotal, order_discount_kind, order_discount_value)
    if not discount_approved and not pricing.discount_within_limit_tiyn(subtotal, order_disc, limit):
        raise PermissionError("Скидка на чек превышает лимит кассира")
    total = pricing.order_total_tiyn(subtotal, order_disc)
    # Сверка с корзиной — до проверки оплаты: при изменившейся цене оплата тоже
    # не сойдётся, и без этой проверки кассир увидел бы следствие вместо причины.
    if expected_total_tiyn is not None and expected_total_tiyn != total:
        raise PriceChanged(expected_total_tiyn, total)
    # скидка чека разносится по строкам: возврат и отчёты считают деньги по ним
    order_disc_shares = pricing.spread_order_discount_tiyn(line_totals, order_disc)

    pricing.validate_payments(total, payments)

    try:
        order = Order(
            shift_id=shift.id,
            number=_next_order_number(session, shift.id),
            status="paid",
            subtotal_tiyn=subtotal,
            discount_tiyn=order_disc,
            total_tiyn=total,
            cost_tiyn=sum(cl.unit_cost_tiyn * cl.qty for cl in cart_lines),
        )
        session.add(order)
        session.flush()

        for (li, product, mods, cart_line), disc_share in zip(resolved, order_disc_shares):
            item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                name=product.name,
                unit_price_tiyn=pricing.line_unit_price_tiyn(cart_line),
                qty=li.qty,
                discount_tiyn=pricing.line_discount_tiyn(cart_line) + disc_share,
                line_total_tiyn=pricing.line_total_tiyn(cart_line) - disc_share,
                unit_cost_tiyn=cart_line.unit_cost_tiyn,
            )
            session.add(item)
            session.flush()
            for m in mods:
                session.add(OrderItemModifier(
                    order_item_id=item.id, modifier_id=m.id,
                    name=m.name, price_delta_tiyn=m.price_delta_tiyn,
                ))
            _deduct_stock(session, product, mods, li.qty, order.id)

        for pay in payments:
            change = None
            if pay.method == "cash" and pay.tendered_tiyn is not None:
                change = max(pay.tendered_tiyn - pay.amount_tiyn, 0)
            session.add(Payment(
                order_id=order.id, method=pay.method, amount_tiyn=pay.amount_tiyn,
                tendered_tiyn=pay.tendered_tiyn, change_tiyn=change,
                provider=pay.provider, terminal_method=pay.terminal_method,
                transaction_id=pay.transaction_id,
            ))

        if order_disc > 0:
            notification_service.enqueue(
                session, kind="discount",
                text=(f"Скидка {order_disc / 100:.2f} тг на заказ №{order.number}, "
                      f"кассир: {cashier.name}"),
            )

        notification_service.enqueue(
            session, kind="sale",
            # Уведомление собирается ПОСЛЕ списания склада: в него попадают
            # уже уменьшенные остатки, а не те, что были до чека.
            text=_sale_notification_text(session, order, resolved, payments, cashier),
        )

        session.commit()
    except Exception:
        session.rollback()
        raise
    return order


def _deduct_stock(session: Session, product: Product, mods, qty: int, order_id: int) -> None:
    """Списание проданных штук. Товары без учёта остатка пропускаются самим apply_move.

    Продажа при этом не блокируется никогда: остаток уходит в минус, и это видно
    на складе и в уведомлении — но чек касса обязана пробить.
    """
    apply_move(
        session, product.id,
        qty_delta=-qty, kind="sale",
        cost_tiyn=(product.cost_tiyn or 0) * qty,
        ref_type="order", ref_id=order_id, commit=False,
    )


def refund_sale(
    session: Session,
    *,
    order_id: int,
    cashier_id: int,
    reason: str,
    item_qty: dict[int, int] | None = None,
) -> Refund:
    """Возврат. item_qty=None — полный возврат всех оставшихся позиций.

    Штучные (retail) позиции возвращаются на склад; приготовленные — нет.
    """
    if not reason or not reason.strip():
        raise ValueError("Причина возврата обязательна")
    order = session.get(Order, order_id)
    if order is None:
        raise ValueError(f"Заказ {order_id} не найден")
    if order.status == "refunded":
        raise ValueError("Заказ уже полностью возвращён")

    items = session.scalars(select(OrderItem).where(OrderItem.order_id == order_id)).all()
    by_id = {it.id: it for it in items}

    if item_qty is None:
        plan = {it.id: it.qty - it.refunded_qty for it in items if it.qty - it.refunded_qty > 0}
    else:
        plan = {}
        for item_id, q in item_qty.items():
            it = by_id.get(item_id)
            if it is None:
                raise ValueError(f"Позиция {item_id} не в этом заказе")
            if q <= 0 or q > it.qty - it.refunded_qty:
                raise ValueError("Некорректное количество возврата")
            plan[item_id] = q

    if not plan:
        raise ValueError("Нечего возвращать")

    try:
        refund = Refund(order_id=order_id, amount_tiyn=0, reason=reason.strip(), cashier_id=cashier_id)
        session.add(refund)
        session.flush()

        refunded_amount = 0
        for item_id, q in plan.items():
            it = by_id[item_id]
            item_amount = it.line_total_tiyn * q // it.qty  # доля строки, при полном возврате = line_total
            refunded_amount += item_amount
            it.refunded_qty += q
            session.add(RefundItem(refund_id=refund.id, order_item_id=item_id, qty=q,
                                   amount_tiyn=item_amount))
            # Штучный товар возвращается на полку; приготовленный вылить обратно
            # нельзя, поэтому его остаток не восстанавливается.
            product = session.get(Product, it.product_id) if it.product_id else None
            if product is not None and product.kind == "retail":
                apply_move(
                    session, product.id,
                    qty_delta=q, kind="refund",
                    ref_type="order", ref_id=order_id, commit=False,
                )

        refund.amount_tiyn = refunded_amount
        all_refunded = all(it.refunded_qty >= it.qty for it in items)
        order.status = "refunded" if all_refunded else "partially_refunded"
        cashier = session.get(User, cashier_id)
        if cashier is None:
            raise ValueError(f"Кассир {cashier_id} не найден")
        notification_service.enqueue(
            session, kind="refund",
            text=(
                f"Возврат {refunded_amount / 100:.2f} тг по заказу №{order.number}, "
                f"причина: {refund.reason}, кассир: {cashier.name}"
            ),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return refund
