from dataclasses import dataclass, field


@dataclass
class CartLine:
    base_price_tiyn: int
    qty: int
    unit_cost_tiyn: int
    modifier_price_deltas: list[int] = field(default_factory=list)
    discount_kind: str | None = None  # "percent" | "amount" | None
    discount_value: int = 0  # процент 0..100 или сумма в тиынах


@dataclass
class PaymentInput:
    method: str  # "cash" | "card" | "kaspi_qr" | "kaspi_terminal"
    amount_tiyn: int
    tendered_tiyn: int | None = None
    provider: str = "manual"  # "manual" | "terminal"
    terminal_method: str | None = None  # "qr" | "card" | "alaqan"
    transaction_id: str | None = None


def line_unit_price_tiyn(line: CartLine) -> int:
    return line.base_price_tiyn + sum(line.modifier_price_deltas)


def _gross_tiyn(line: CartLine) -> int:
    return line_unit_price_tiyn(line) * line.qty


def line_discount_tiyn(line: CartLine) -> int:
    gross = _gross_tiyn(line)
    if line.discount_kind is None:
        return 0
    if line.discount_kind == "percent":
        if not 0 <= line.discount_value <= 100:
            raise ValueError("Процент скидки должен быть в диапазоне 0..100")
        return gross * line.discount_value // 100
    if line.discount_kind == "amount":
        if line.discount_value < 0:
            raise ValueError("Сумма скидки не может быть отрицательной")
        return min(line.discount_value, gross)
    raise ValueError(f"Неизвестный тип скидки: {line.discount_kind}")


def line_total_tiyn(line: CartLine) -> int:
    return _gross_tiyn(line) - line_discount_tiyn(line)


def effective_discount_percent(line: CartLine) -> int:
    """Скидка позиции в процентах (для отображения; округление вниз)."""
    gross = _gross_tiyn(line)
    if gross == 0 or line.discount_kind is None:
        return 0
    return line_discount_tiyn(line) * 100 // gross


def discount_within_limit_tiyn(gross_tiyn: int, discount_tiyn: int, limit_percent: int) -> bool:
    """True, если скидка не превышает лимит. Точное сравнение без округления:
    discount/gross <= limit/100  ⇔  discount*100 <= limit*gross."""
    if gross_tiyn <= 0:
        return True
    return discount_tiyn * 100 <= limit_percent * gross_tiyn


def order_subtotal_tiyn(lines: list[CartLine]) -> int:
    return sum(line_total_tiyn(l) for l in lines)


def order_discount_tiyn(subtotal_tiyn: int, kind: str | None, value: int) -> int:
    if kind is None:
        return 0
    if kind == "percent":
        if not 0 <= value <= 100:
            raise ValueError("Процент скидки должен быть в диапазоне 0..100")
        return subtotal_tiyn * value // 100
    if kind == "amount":
        if value < 0:
            raise ValueError("Сумма скидки не может быть отрицательной")
        return min(value, subtotal_tiyn)
    raise ValueError(f"Неизвестный тип скидки: {kind}")


def order_total_tiyn(subtotal_tiyn: int, order_discount_tiyn_value: int) -> int:
    return subtotal_tiyn - order_discount_tiyn_value


def spread_order_discount_tiyn(line_totals: list[int], order_discount: int) -> list[int]:
    """Делит скидку чека между позициями пропорционально их сумме.

    Неделимый остаток кладётся на последнюю позицию, поэтому сумма долей всегда
    точно равна order_discount — иначе строки чека не сошлись бы с итогом, а
    возврат и отчёты считают деньги именно по строкам.
    """
    if not line_totals:
        return []
    subtotal = sum(line_totals)
    if subtotal <= 0 or order_discount <= 0:
        return [0] * len(line_totals)
    shares = [order_discount * lt // subtotal for lt in line_totals[:-1]]
    shares.append(order_discount - sum(shares))
    return shares


def validate_payments(total_tiyn: int, payments: list[PaymentInput]) -> None:
    for pay in payments:
        if pay.amount_tiyn < 0:
            raise ValueError("Сумма оплаты не может быть отрицательной")
        if pay.method not in ("cash", "card", "kaspi_qr", "kaspi_terminal"):
            raise ValueError(f"Неизвестный способ оплаты: {pay.method}")
    covered = sum(pay.amount_tiyn for pay in payments)
    if covered != total_tiyn:
        raise ValueError(f"Оплата {covered} не покрывает итог {total_tiyn}")


def cash_change_tiyn(payments: list[PaymentInput]) -> int:
    change = 0
    for pay in payments:
        if pay.method == "cash" and pay.tendered_tiyn is not None:
            change += max(pay.tendered_tiyn - pay.amount_tiyn, 0)
    return change
