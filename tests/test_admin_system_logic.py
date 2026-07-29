"""Чистая логика экрана «Сервер»: форматирование чисел и цвета вердиктов."""
import pytest

from app.ui.admin_system import (format_bytes, format_measure, format_uptime,
                                 verdict_bg, verdict_color)


@pytest.mark.parametrize("value, expected", [
    (0, "0 Б"),
    (512, "512 Б"),
    (1024, "1,0 КБ"),
    (229376, "224,0 КБ"),
    (4136512, "3,9 МБ"),
    (3 * 1024 ** 3, "3,0 ГБ"),
])
def test_format_bytes(value, expected):
    assert format_bytes(value) == expected


@pytest.mark.parametrize("seconds, expected", [
    (None, "—"),
    (0, "0 мин"),
    (59, "0 мин"),
    (420, "7 мин"),
    (3600, "1 ч 0 мин"),
    (18720, "5 ч 12 мин"),
    (86400, "1 сут 0 ч"),
    (273600, "3 сут 4 ч"),
])
def test_format_uptime(seconds, expected):
    assert format_uptime(seconds) == expected


def test_format_uptime_ignores_negative_clock_skew():
    """Часы на моноблоке могли перевести назад — «-3 мин» на экране пугает зря."""
    assert format_uptime(-120) == "0 мин"


@pytest.mark.parametrize("value, unit, expected", [
    (3.2, "мс", "3,2 мс"),
    (99.9, "мс", "99,9 мс"),
    (100.0, "мс", "100 мс"),
    (1450.0, "мс", "1450 мс"),
    (62.5, "МБ/с", "62,5 МБ/с"),
    (12.0, "ГБ", "12,0 ГБ"),
    (95.0, "%", "95,0%"),
    (100.0, "%", "100%"),
])
def test_format_measure(value, unit, expected):
    assert format_measure(value, unit) == expected


@pytest.mark.parametrize("verdict", ["ok", "warn", "bad"])
def test_verdict_styles_defined(verdict):
    assert verdict_color(verdict).startswith("var(--status-")
    assert verdict_bg(verdict).startswith("var(--status-")


def test_unknown_verdict_falls_back_to_neutral():
    """Неизвестный вердикт не должен красить строку в тревожный цвет."""
    assert verdict_color("что-то новое") == "var(--text-secondary)"
    assert verdict_bg("что-то новое") == "var(--surface-sunken)"
