"""Общие элементы оформления из дизайн-системы «Coffee POS»: иконки и карточки.

Иконки категорий подбираются по названию, а не хранятся в БД: категории заводит
владелец, и отдельное поле пришлось бы заполнять руками для каждой новой.
"""
from nicegui import ui

# Порядок важен: первое совпадение подстроки выигрывает.
_CATEGORY_ICONS: list[tuple[tuple[str, ...], str]] = [
    (("кофе", "эспрессо", "капучино", "латте"), "local_cafe"),
    (("чай", "матча"), "emoji_food_beverage"),
    (("выпеч", "десерт", "булоч", "круассан", "торт", "пирож"), "bakery_dining"),
    (("холод", "айс", "лёд", "лед", "смузи", "лимонад"), "ac_unit"),
    (("обед", "еда", "бургер", "сэндвич", "сендвич", "салат", "суп"), "restaurant"),
    (("завтрак", "каша"), "egg_alt"),
    (("снек", "закус", "чипс", "орех"), "cookie"),
    (("вода", "сок", "напит"), "local_drink"),
]
_CATEGORY_FALLBACK = "restaurant_menu"

PAYMENT_ICONS = {
    "cash": "payments",
    "card": "credit_card",
    "kaspi_qr": "qr_code_2",
    "kaspi_terminal": "contactless",
}


def category_icon(name: str) -> str:
    low = (name or "").lower()
    for keys, icon in _CATEGORY_ICONS:
        if any(k in low for k in keys):
            return icon
    return _CATEGORY_FALLBACK


def section_title(text: str) -> None:
    """Мелкий заголовок раздела капсом — как в макете над группами карточек."""
    ui.label(text).classes("text-xs uppercase tracking-wider mt-2") \
        .style("color: var(--text-secondary)")


def nav_card(*, icon: str, title: str, subtitle: str, on_click) -> None:
    """Карточка-ссылка: иконка фирменного цвета слева, заголовок и подпись справа."""
    card = ui.card().classes("w-full cursor-pointer p-4 cp-hover").style("min-height:88px")
    card.on("click", on_click)
    with card, ui.row().classes("items-start gap-3 no-wrap w-full"):
        ui.icon(icon, size="28px").style("color: var(--brand-primary)")
        with ui.column().classes("gap-0 min-w-0"):
            ui.label(title).classes("text-lg font-bold leading-tight")
            ui.label(subtitle).classes("text-sm leading-tight") \
                .style("color: var(--text-secondary)")


def stat_tile(label: str, value: str) -> None:
    """Плитка показателя: подпись сверху, крупное значение снизу."""
    with ui.column().classes("gap-1 rounded-2xl p-4 flex-1") \
            .style("min-width:140px; background: var(--surface-sunken)"):
        ui.label(label).classes("text-xs").style("color: var(--text-secondary)")
        ui.label(value).classes("text-2xl font-black leading-tight")


# Купюры Казахстана — быстрый ввод полученной суммы одним нажатием.
BANKNOTES = (500, 1000, 2000, 5000, 10000)

# Причины возврата: на моноблоке нет клавиатуры, а причина обязательна.
REFUND_REASONS = (
    "Клиент передумал",
    "Ошибка кассира",
    "Не понравился напиток",
    "Долго готовили",
    "Брак / качество",
    "Пробили не то",
)


def reason_picker(target) -> None:
    """Готовые причины возврата кнопками — набрать текст мышью иначе нечем."""
    with ui.row().classes("gap-2 flex-wrap w-full"):
        for r in REFUND_REASONS:
            ui.button(r, on_click=lambda r=r: target.set_value(r)) \
                .props("outline no-caps").classes("h-11 text-sm")


def numpad(target, *, money: bool = True, max_len: int | None = None,
           quick: tuple[int, ...] | None = None, exact: int | None = None,
           on_change=None) -> None:
    """Экранная цифровая клавиатура: касса стоит на моноблоке с одной мышью.

    target — ui.number (money=True) или ui.input (money=False, например пин-код).
    quick — номиналы купюр: нажатие подставляет сумму целиком.
    exact — сумма чека для кнопки «Без сдачи».
    """
    def text() -> str:
        v = target.value
        if v is None or v == "":
            return ""
        return str(int(v)) if money else str(v)

    def write(s: str) -> None:
        if money:
            target.value = int(s) if s else 0
        else:
            target.value = s
        if on_change is not None:
            on_change()

    def press(d: str) -> None:
        s = text()
        if s == "0":
            s = ""
        if max_len is not None and len(s) + len(d) > max_len:
            return
        write(s + d)

    def backspace() -> None:
        write(text()[:-1])

    with ui.column().classes("gap-2 w-full").style("max-width:320px"):
        if quick:
            with ui.row().classes("gap-2 flex-wrap"):
                for n in quick:
                    ui.button(f"{n:,}".replace(",", " "),
                              on_click=lambda n=n: write(str(n))) \
                        .props("outline no-caps").classes("h-12 text-base flex-1")
        if exact is not None:
            ui.button("Без сдачи", icon="done_all",
                      on_click=lambda: write(str(exact))) \
                .props("outline no-caps").classes("w-full h-12 text-base")
        with ui.grid(columns=3).classes("gap-2 w-full"):
            for d in "123456789":
                ui.button(d, on_click=lambda d=d: press(d)) \
                    .props("outline").classes("h-16 text-2xl font-bold")
            if money:
                ui.button("00", on_click=lambda: press("00")) \
                    .props("outline").classes("h-16 text-2xl font-bold")
            else:
                ui.button("C", on_click=lambda: write("")) \
                    .props("outline").classes("h-16 text-2xl font-bold")
            ui.button("0", on_click=lambda: press("0")) \
                .props("outline").classes("h-16 text-2xl font-bold")
            ui.button(icon="backspace", on_click=backspace) \
                .props("outline").classes("h-16")
