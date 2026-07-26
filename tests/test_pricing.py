import pytest

from app.services import pricing as p


def _line(**kw):
    base = dict(
        base_price_tiyn=150000, qty=1, modifier_price_deltas=[],
        discount_kind=None, discount_value=0, unit_cost_tiyn=40000,
    )
    base.update(kw)
    return p.CartLine(**base)


def test_unit_price_includes_modifiers():
    line = _line(modifier_price_deltas=[20000, 5000])
    assert p.line_unit_price_tiyn(line) == 175000


def test_line_percent_discount_floors():
    line = _line(base_price_tiyn=100000, qty=3, discount_kind="percent", discount_value=10)
    assert p.line_discount_tiyn(line) == 30000
    assert p.line_total_tiyn(line) == 270000


def test_line_amount_discount_capped_at_gross():
    line = _line(base_price_tiyn=100000, qty=1, discount_kind="amount", discount_value=150000)
    assert p.line_discount_tiyn(line) == 100000
    assert p.line_total_tiyn(line) == 0


def test_order_totals_and_order_discount():
    lines = [_line(base_price_tiyn=100000, qty=2), _line(base_price_tiyn=150000, qty=1)]
    subtotal = p.order_subtotal_tiyn(lines)
    assert subtotal == 350000
    disc = p.order_discount_tiyn(subtotal, "percent", 20)
    assert disc == 70000
    assert p.order_total_tiyn(subtotal, disc) == 280000


def test_effective_discount_percent_for_limit_check():
    line = _line(base_price_tiyn=100000, qty=1, discount_kind="amount", discount_value=25000)
    assert p.effective_discount_percent(line) == 25
    line2 = _line(discount_kind="percent", discount_value=15)
    assert p.effective_discount_percent(line2) == 15
    line3 = _line()
    assert p.effective_discount_percent(line3) == 0


def test_discount_within_limit_is_exact():
    # лимит 10%, gross 150000 → ровно 15000 разрешено, 15001 (10.0006%) нет
    assert p.discount_within_limit_tiyn(150000, 15000, 10) is True
    assert p.discount_within_limit_tiyn(150000, 15001, 10) is False
    # floor в процентах округлил бы 16499/150000=10.99% до 10 и пропустил — здесь нет
    assert p.discount_within_limit_tiyn(150000, 16499, 10) is False
    # нулевой gross не блокирует
    assert p.discount_within_limit_tiyn(0, 0, 10) is True


def test_validate_payments_must_cover_total():
    pays = [p.PaymentInput("cash", 100000, 200000), p.PaymentInput("card", 80000, None)]
    p.validate_payments(180000, pays)
    with pytest.raises(ValueError):
        p.validate_payments(200000, pays)


def test_cash_change_from_tendered():
    pays = [p.PaymentInput("cash", 100000, 200000), p.PaymentInput("kaspi_qr", 80000, None)]
    assert p.cash_change_tiyn(pays) == 100000


def test_negative_and_bad_inputs_rejected():
    with pytest.raises(ValueError):
        p.line_discount_tiyn(_line(discount_kind="percent", discount_value=150))
    with pytest.raises(ValueError):
        p.validate_payments(100000, [p.PaymentInput("cash", -1, None)])


def test_spread_order_discount_is_proportional():
    assert p.spread_order_discount_tiyn([100000, 300000], 40000) == [10000, 30000]


def test_spread_order_discount_remainder_goes_to_last_line():
    # 10000/3 = 3333 с остатком 1 тиын — сумма долей должна точно равняться скидке
    shares = p.spread_order_discount_tiyn([150000, 150000, 150000], 10000)
    assert shares == [3333, 3333, 3334]
    assert sum(shares) == 10000


def test_spread_order_discount_handles_zero_cases():
    assert p.spread_order_discount_tiyn([150000], 0) == [0]
    assert p.spread_order_discount_tiyn([0, 0], 0) == [0, 0]
    assert p.spread_order_discount_tiyn([], 0) == []


def test_cart_line_from_dict_shape():
    # форма данных, которую cashier.py кладёт в корзину: base_price + список дельт модификаторов
    line = p.CartLine(base_price_tiyn=150000, qty=2, unit_cost_tiyn=0,
                      modifier_price_deltas=[20000, 5000])
    assert p.line_total_tiyn(line) == (150000 + 20000 + 5000) * 2
