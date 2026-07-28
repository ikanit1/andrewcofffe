"""Чистая логика экрана отчётов: подписи периода и фильтры чеков."""
from datetime import date, datetime, timezone

import pytest

from app.services.reporting_service import DayRow, Receipt, ReceiptLine
from app.ui.reports import range_label, receipt_matches


def _day(d: date) -> DayRow:
    return DayRow(day=d, revenue_tiyn=0, refunds_tiyn=0, cogs_tiyn=0,
                  orders_count=0, items_count=0)


def test_range_label_for_empty_period():
    assert range_label([]) == "—"


def test_range_label_for_single_day():
    assert range_label([_day(date(2026, 7, 28))]) == "28.07.2026 · 1 день"


@pytest.mark.parametrize("n, tail", [(2, "2 дня"), (4, "4 дня"), (5, "5 дней"),
                                     (7, "7 дней"), (11, "11 дней"), (21, "21 день"), (31, "31 день"),
                                     (22, "22 дня"), (25, "25 дней")])
def test_range_label_declines_days_correctly(n, tail):
    """11–14 — исключение: «11 дней», а не «11 дня», хотя оканчивается на 1."""
    days = [_day(date(2026, 7, 1)) for _ in range(n)]
    assert range_label(days).endswith(tail)


def _receipt(hour: int, *, methods=("cash",), refunded: int = 0) -> Receipt:
    return Receipt(
        number=1, at=datetime(2026, 7, 28, hour, 15, tzinfo=timezone.utc),
        total_tiyn=100000, method=methods[0], methods=tuple(methods),
        lines=(ReceiptLine("Латте", 1, 100000, 100000),),
        refunded_tiyn=refunded, refund_reason="брак" if refunded else "",
    )


def test_filter_all_passes_everything():
    assert receipt_matches(_receipt(9), hour=None, method_filter="all") is True


def test_filter_by_hour():
    r = _receipt(9)
    assert receipt_matches(r, hour=9, method_filter="all") is True
    assert receipt_matches(r, hour=10, method_filter="all") is False


def test_filter_by_method():
    r = _receipt(9, methods=("kaspi_qr",))
    assert receipt_matches(r, hour=None, method_filter="kaspi_qr") is True
    assert receipt_matches(r, hour=None, method_filter="cash") is False


def test_split_payment_matches_any_of_its_methods():
    """Чек, оплаченный наличными и картой, обязан находиться по обоим фильтрам."""
    r = _receipt(9, methods=("cash", "card"))
    assert receipt_matches(r, hour=None, method_filter="cash") is True
    assert receipt_matches(r, hour=None, method_filter="card") is True


def test_filter_refunds_only():
    assert receipt_matches(_receipt(9, refunded=5000), hour=None,
                           method_filter="refunds") is True
    assert receipt_matches(_receipt(9), hour=None, method_filter="refunds") is False


def test_hour_and_method_filters_combine():
    """Час из графика и способ из пилюль работают вместе, а не вытесняют друг друга."""
    r = _receipt(9, methods=("cash",))
    assert receipt_matches(r, hour=9, method_filter="cash") is True
    assert receipt_matches(r, hour=8, method_filter="cash") is False
    assert receipt_matches(r, hour=9, method_filter="kaspi_qr") is False
