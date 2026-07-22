from nicegui import ui

from app.ui.guard import require_admin
from app.ui.layout import admin_header

# (заголовок, подпись, адрес)
_SECTIONS = [
    ("📊 Дашборд", "Выручка, остатки, бэкап", "/admin/dashboard"),
    ("📋 Меню и цены", "Товары, категории, цены", "/admin/menu"),
    ("🧊 Склад и тех-карты", "Ингредиенты, рецепты, пороги", "/admin/stock"),
    ("⚙️ Модификаторы", "Объём, молоко, сиропы, добавки", "/admin/modifiers"),
    ("💳 Kaspi терминал", "Подключение оплаты", "/admin/kaspi"),
    ("🛒 Открыть кассу", "Продажи и смены", "/cashier"),
]


@ui.page("/admin")
def admin_home_page() -> None:
    if not require_admin():
        return
    admin_header()

    ui.label("Админ-панель").classes("text-2xl font-bold")
    with ui.grid(columns=3).classes("w-full max-w-4xl gap-4"):
        for title, subtitle, url in _SECTIONS:
            card = ui.card().classes(
                "w-full h-32 items-start justify-center cursor-pointer "
                "p-4 gap-1 hover:bg-[#f5ece0] transition"
            )
            card.on("click", lambda u=url: ui.navigate.to(u))
            with card:
                ui.label(title).classes("text-lg font-bold")
                ui.label(subtitle).classes("text-sm text-gray-500")
