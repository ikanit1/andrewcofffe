from nicegui import ui

from app.ui.design import nav_card, section_title
from app.ui.guard import require_admin
from app.ui.layout import admin_header

# Разделы админки, сгруппированные как в макете: (иконка, заголовок, подпись, адрес)
_GROUPS: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    ("Продажи", [
        ("insights", "Дашборд", "Выручка, остатки, бэкап", "/admin/dashboard"),
        ("bar_chart", "Отчёты", "Выручка, маржа, Excel", "/admin/reports"),
        ("point_of_sale", "Открыть кассу", "Продажи и смены", "/cashier"),
    ]),
    ("Каталог", [
        ("restaurant_menu", "Меню и цены", "Товары, категории, цены", "/admin/menu"),
        ("inventory_2", "Склад и тех-карты", "Ингредиенты, рецепты, пороги", "/admin/stock"),
        ("tune", "Модификаторы", "Объём, молоко, сиропы, добавки", "/admin/modifiers"),
    ]),
    ("Настройки", [
        ("group", "Пользователи", "Кассиры, роли, PIN", "/admin/users"),
        ("contactless", "Kaspi терминал", "Подключение оплаты", "/admin/kaspi"),
        ("system_update", "Версия и обновление", "Проверить, вышла ли новая", "/admin/about"),
    ]),
]


@ui.page("/admin")
def admin_home_page() -> None:
    if not require_admin():
        return
    admin_header()

    with ui.column().classes("w-full max-w-4xl gap-5 p-1"):
        ui.label("Админ-панель").classes("text-2xl font-black")
        for title, items in _GROUPS:
            section_title(title)
            with ui.grid(columns=3).classes("w-full gap-3"):
                for icon, name, subtitle, url in items:
                    nav_card(icon=icon, title=name, subtitle=subtitle,
                             on_click=lambda u=url: ui.navigate.to(u))
