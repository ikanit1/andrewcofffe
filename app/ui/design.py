"""Общие элементы оформления из дизайн-системы «Coffee POS»: иконки и карточки.

Иконки категорий подбираются по названию, а не хранятся в БД: категории заводит
владелец, и отдельное поле пришлось бы заполнять руками для каждой новой.
"""
import inspect

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

PAYMENT_LABELS = {
    "cash": "Наличные",
    "card": "Карта",
    "kaspi_qr": "Kaspi QR",
    "kaspi_terminal": "Kaspi (терминал)",
}


def money_tg(tiyn: int) -> str:
    """Сумма в тенге с неразрывными тысячами: «12 450 тг»."""
    return f"{tiyn / 100:,.0f} тг".replace(",", " ")


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """«1 чек» / «2 чека» / «5 чеков» — иначе подписи выглядят машинно.

    Исключение 11–14 обязательно: без него 11 давало бы «11 чек», а 112 — «112 чека».
    """
    if 11 <= n % 100 <= 14:
        return f"{n} {many}"
    if n % 10 == 1:
        return f"{n} {one}"
    return f"{n} {few}" if 2 <= n % 10 <= 4 else f"{n} {many}"


def checks_word(n: int) -> str:
    return plural_ru(n, "чек", "чека", "чеков")


def category_icon(name: str) -> str:
    low = (name or "").lower()
    for keys, icon in _CATEGORY_ICONS:
        if any(k in low for k in keys):
            return icon
    return _CATEGORY_FALLBACK


def product_media(*, product_id: int, has_image: bool, fallback_icon: str,
                  height: int) -> None:
    """Верхняя полоса плитки товара: фото или единообразная заглушка.

    Высота фиксирована, кадрирование — cover. Иначе ряд плиток «пляшет»: у фото
    произвольные пропорции, и без обрезки Quasar показал бы их целиком, добавив
    поля по краям, а товар без фото занимал бы меньше места, чем соседи.

    Заглушка нужна именно как блок той же высоты: если у одного товара фото есть,
    а у другого нет, разнобой заметнее, чем отсутствие картинок вообще.
    """
    box = ui.element("div").classes("w-full flex items-center justify-center shrink-0") \
        .style(f"height:{height}px;background:var(--surface-sunken);overflow:hidden")
    with box:
        if has_image:
            # fit=cover — свойство QImg; CSS-класс на обёртке сюда не доходит,
            # внутри лежит собственный контейнер Quasar.
            ui.image(f"/product-image/{product_id}").props("fit=cover no-spinner") \
                .classes("w-full h-full")
        else:
            ui.icon(fallback_icon, size="34px") \
                .style("color: var(--brand-primary); opacity:.35")


def empty_state(*, icon: str, title: str, hint: str = "",
                action_label: str | None = None, action_icon: str | None = None,
                on_action=None) -> None:
    """Заглушка для пустого экрана: иконка, объяснение и, если есть куда идти, кнопка.

    Сообщение вида «добавьте их в /admin/stock» — тупик: путь написан текстом,
    нажать нельзя. Здесь переход даётся кнопкой, а вызывающий код решает,
    показывать ли её: вести кассира в админский раздел бессмысленно.
    """
    with ui.column().classes("w-full items-center gap-3 py-12 px-5 rounded-2xl") \
            .style("background: var(--surface-card); "
                   "border: 1px dashed var(--border-default)"):
        ui.icon(icon, size="34px").style("color: var(--text-muted)")
        ui.label(title).classes("text-lg font-bold text-center")
        if hint:
            ui.label(hint).classes("text-sm text-center max-w-md") \
                .style("color: var(--text-secondary)")
        if action_label and on_action is not None:
            ui.button(action_label, icon=action_icon, on_click=on_action) \
                .props("no-caps").classes("mt-1")


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


def confirm_with_pin(*, title: str, question: str, action_label: str, on_confirm) -> None:
    """Подтверждение опасного действия PIN-кодом администратора.

    Касса смотрит в интернет через Tailscale Funnel. Одной открытой вкладки для
    перезапуска сервера или перестройки базы мало: пусть тот, кто нажимает,
    подтвердит, что он администратор, а не перехваченная сессия.

    on_confirm может быть как обычной функцией, так и корутиной: перезапуск
    планируется синхронно, а обслуживание базы уходит в поток и ждёт результата.
    """
    from app.db import SessionLocal
    from app.services import user_service
    from app.services.login_throttle import LockedOut

    with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
        ui.label(title).classes("text-lg font-bold")
        ui.label(question).classes("text-sm").style("color: var(--text-secondary)")
        pin = ui.input("PIN", password=True).props("inputmode=numeric readonly") \
            .classes("w-full")
        numpad(pin, money=False, max_len=6)

        async def confirm() -> None:
            try:
                with SessionLocal() as session:
                    admin = user_service.admin_by_pin(session, (pin.value or "").strip())
            except LockedOut as e:
                pin.value = ""
                ui.notify(f"Слишком много попыток. Подождите {e.retry_after_seconds} с.",
                          color="red")
                return
            if admin is None:
                pin.value = ""
                ui.notify("Неверный PIN администратора", color="red")
                return
            dlg.close()
            result = on_confirm()
            if inspect.isawaitable(result):
                await result

        with ui.row().classes("gap-2"):
            ui.button(action_label, on_click=confirm).props("no-caps")
            ui.button("Отмена", on_click=dlg.close).props("flat no-caps")
    dlg.open()


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
