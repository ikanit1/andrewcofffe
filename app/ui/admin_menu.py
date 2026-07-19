from nicegui import ui

from app.db import SessionLocal
from app.services import catalog_service as cs

KIND_LABELS = {"prepared": "Приготовленный", "retail": "Штучный"}


@ui.page("/admin/menu")
def admin_menu_page() -> None:
    ui.label("Меню и цены").classes("text-2xl font-bold")

    container = ui.column().classes("w-full max-w-3xl gap-2")

    def refresh() -> None:
        container.clear()
        with container, SessionLocal() as session:
            for cat, products in cs.list_menu(session):
                ui.label(cat.name).classes("text-xl mt-4")
                for p in products:
                    with ui.row().classes("items-center gap-4"):
                        ui.label(p.name).classes("w-48")
                        ui.label(KIND_LABELS[p.kind]).classes("text-gray-500 w-36")
                        price = ui.number(
                            label="Цена, тг", value=p.price_tiyn / 100, min=1, format="%.0f"
                        )

                        def save(pid=p.id, field=price) -> None:
                            with SessionLocal() as s:
                                cs.update_product(s, pid, price_tiyn=int(field.value * 100))
                            ui.notify("Цена сохранена")

                        ui.button("Сохранить", on_click=save)

                        def deactivate(pid=p.id) -> None:
                            with SessionLocal() as s:
                                cs.update_product(s, pid, is_active=False)
                            refresh()

                        ui.button("Убрать", on_click=deactivate, color="red")

    with ui.expansion("Добавить категорию").classes("w-full max-w-3xl"):
        cat_name = ui.input("Название категории")

        def add_category() -> None:
            if not cat_name.value:
                return
            with SessionLocal() as s:
                cs.create_category(s, cat_name.value)
            cat_name.value = ""
            refresh()

        ui.button("Добавить", on_click=add_category)

    with ui.expansion("Добавить товар").classes("w-full max-w-3xl"):
        with SessionLocal() as session:
            cat_options = {c.id: c.name for c, _ in cs.list_menu(session)}
        p_name = ui.input("Название")
        p_cat = ui.select(cat_options, label="Категория")
        p_kind = ui.select(KIND_LABELS, label="Тип", value="prepared")
        p_price = ui.number(label="Цена, тг", value=0, min=1, format="%.0f")

        def add_product() -> None:
            if not (p_name.value and p_cat.value and p_price.value):
                ui.notify("Заполните все поля", color="red")
                return
            with SessionLocal() as s:
                cs.create_product(
                    s,
                    name=p_name.value,
                    category_id=p_cat.value,
                    kind=p_kind.value,
                    price_tiyn=int(p_price.value * 100),
                )
            p_name.value = ""
            refresh()

        ui.button("Добавить товар", on_click=add_product)

    refresh()
