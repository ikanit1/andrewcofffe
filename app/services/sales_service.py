from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Ingredient,
    Modifier,
    ModifierItem,
    Order,
    OrderItem,
    OrderItemModifier,
    Payment,
    Product,
    RecipeItem,
    Refund,
    RefundItem,
    User,
)
from app.services import costing, modifier_service, notification_service, pricing
from app.services.inventory_service import apply_move
from app.services.pricing import CartLine, PaymentInput
from app.services.shift_service import current_open_shift


@dataclass
class SaleLineInput:
    product_id: int
    qty: int = 1
    modifier_ids: list[int] = field(default_factory=list)
    discount_kind: str | None = None
    discount_value: int = 0


def _next_order_number(session: Session, shift_id: int) -> int:
    last = session.scalar(
        select(func.max(Order.number)).where(Order.shift_id == shift_id)
    )
    return (last or 0) + 1


def create_sale(
    session: Session,
    *,
    cashier_id: int,
    lines: list[SaleLineInput],
    payments: list[PaymentInput],
    order_discount_kind: str | None = None,
    order_discount_value: int = 0,
    discount_approved: bool = False,
) -> Order:
    """Атомарно проводит чек: заказ + позиции + модификаторы + оплаты + списание склада.

    Всё в одной транзакции — при любой ошибке откат, склад и заказ не меняются.
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
            base_price_tiyn=product.price_tiyn,
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

    cart_lines = [r[3] for r in resolved]
    line_totals = [pricing.line_total_tiyn(cl) for cl in cart_lines]
    subtotal = pricing.order_subtotal_tiyn(cart_lines)
    order_disc = pricing.order_discount_tiyn(subtotal, order_discount_kind, order_discount_value)
    if not discount_approved and not pricing.discount_within_limit_tiyn(subtotal, order_disc, limit):
        raise PermissionError("Скидка на чек превышает лимит кассира")
    total = pricing.order_total_tiyn(subtotal, order_disc)
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

        session.commit()
    except Exception:
        session.rollback()
        raise
    return order


def _deduct_stock(session: Session, product: Product, mods, qty: int, order_id: int) -> None:
    """Списание по тех-карте (prepared) или по привязке (retail) + модификаторы."""
    def move(ingredient_id: int, per_unit_qty: int) -> None:
        ing = session.get(Ingredient, ingredient_id)
        total_qty = per_unit_qty * qty
        apply_move(
            session, ingredient_id,
            qty_delta=-total_qty, kind="sale",
            cost_tiyn=round(ing.avg_cost_tiyn * total_qty),
            ref_type="order", ref_id=order_id, commit=False,
        )

    if product.kind == "prepared":
        for r in session.scalars(select(RecipeItem).where(RecipeItem.product_id == product.id)).all():
            move(r.ingredient_id, r.qty)
    elif product.kind == "retail" and product.ingredient_id is not None:
        move(product.ingredient_id, 1)

    for m in mods:
        for mi in session.scalars(select(ModifierItem).where(ModifierItem.modifier_id == m.id)).all():
            move(mi.ingredient_id, mi.qty)


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
            product = session.get(Product, it.product_id) if it.product_id else None
            if product is not None and product.kind == "retail" and product.ingredient_id is not None:
                apply_move(
                    session, product.ingredient_id,
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
