from datetime import datetime

import pytest

from app.services import promo
from app.timezone import ALMATY


def at(hour: int, minute: int) -> datetime:
    """Момент по времени Алматы — акция привязана к местным часам."""
    return datetime(2026, 7, 27, hour, minute, tzinfo=ALMATY)


class _P:
    def __init__(self, name: str, price_tiyn: int) -> None:
        self.name = name
        self.price_tiyn = price_tiyn


CAPPUCCINO = _P("Капучино", 110000)
LATTE = _P("Латте", 110000)
FLAT = _P("Флэтуайт", 120000)
ESPRESSO = _P("Эспрессо", 60000)


@pytest.mark.parametrize("product", [CAPPUCCINO, LATTE, FLAT])
def test_promo_price_during_window(product):
    assert promo.effective_price_tiyn(product, now=at(9, 0)) == 99000


@pytest.mark.parametrize("moment", [at(8, 30), at(10, 59)])
def test_promo_boundaries_included(moment):
    assert promo.effective_price_tiyn(CAPPUCCINO, now=moment) == 99000


@pytest.mark.parametrize("moment", [at(8, 29), at(11, 0), at(11, 1), at(0, 0), at(23, 59)])
def test_promo_not_active_outside(moment):
    """В 11:00 акция уже не действует: интервал полуоткрытый."""
    assert promo.effective_price_tiyn(CAPPUCCINO, now=moment) == 110000


def test_promo_does_not_touch_other_products():
    assert promo.effective_price_tiyn(ESPRESSO, now=at(9, 0)) == 60000


def test_flat_white_drops_from_1200_to_990():
    """У флэт-уайта обычная цена выше — акция всё равно делает её общей."""
    assert promo.effective_price_tiyn(FLAT, now=at(10, 0)) == 99000
    assert promo.effective_price_tiyn(FLAT, now=at(12, 0)) == 120000


def test_active_promos_listing():
    assert [p.name for p in promo.active_promos(now=at(9, 0))] == ["Утренний кофе"]
    assert promo.active_promos(now=at(12, 0)) == []


def test_name_matching_ignores_case_and_spaces():
    assert promo.active_promo_for("  капучино  ", now=at(9, 0)) is not None
    assert promo.active_promo_for("КАПУЧИНО", now=at(9, 0)) is not None
    assert promo.active_promo_for("Айс кофе", now=at(9, 0)) is None
