from nicegui import ui
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.services import catalog_service as cs
from app.ui.layout import admin_header

KIND_LABELS = {"prepared": "Приготовленный", "retail": "Штучный"}


@ui.page("/admin/menu")
def admin_menu_page() -> None:
    from app.ui.guard import require_admin
    if not require_admin():
        return
    admin_header()

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
                            if field.value is None or field.value <= 0:
                                ui.notify("Введите цену", color="red")
                                return
                            with SessionLocal() as s:
                                try:
                                    cs.update_product(s, pid, price_tiyn=round(field.value * 100))
                                except (ValueError, IntegrityError) as e:
                                    s.rollback()
                                    ui.notify(str(e), color="red")
                                    return
                            ui.notify("Цена сохранена")

                        ui.button("Сохранить", on_click=save)

                        def deactivate(pid=p.id, pname=p.name) -> None:
                            with ui.dialog() as dialog, ui.card():
                                ui.label(f"Убрать «{pname}» из меню?")
                                with ui.row():
                                    def do_remove() -> None:
                                        with SessionLocal() as s:
                                            try:
                                                cs.update_product(s, pid, is_active=False)
                                            except (ValueError, IntegrityError) as e:
                                                s.rollback()
                                                ui.notify(str(e), color="red")
                                                return
                                        dialog.close()
                                        refresh()

                                    ui.button("Убрать", on_click=do_remove, color="red")
                                    ui.button("Отмена", on_click=dialog.close)
                            dialog.open()

                        ui.button("Убрать", on_click=deactivate, color="red")

    def reload_cat_options() -> None:
        with SessionLocal() as session:
            p_cat.set_options({c.id: c.name for c, _ in cs.list_menu(session)})

    with ui.expansion("Добавить категорию").classes("w-full max-w-3xl"):
        cat_name = ui.input("Название категории")

        def add_category() -> None:
            if not cat_name.value:
                return
            with SessionLocal() as s:
                try:
                    cs.create_category(s, cat_name.value)
                except (ValueError, IntegrityError) as e:
                    s.rollback()
                    ui.notify(str(e), color="red")
                    return
            cat_name.value = ""
            refresh()
            reload_cat_options()

        ui.button("Добавить", on_click=add_category)

    with ui.expansion("Добавить товар").classes("w-full max-w-3xl"):
        with SessionLocal() as session:
            cat_options = {c.id: c.name for c, _ in cs.list_menu(session)}
        p_name = ui.input("Название")
        p_cat = ui.select(cat_options, label="Категория")
        p_kind = ui.select(KIND_LABELS, label="Тип", value="prepared")
        p_price = ui.number(label="Цена, тг", value=0, min=1, format="%.0f")

        def add_product() -> None:
            if not (p_name.value and p_cat.value):
                ui.notify("Заполните все поля", color="red")
                return
            if p_price.value is None or p_price.value <= 0:
                ui.notify("Введите цену", color="red")
                return
            with SessionLocal() as s:
                try:
                    cs.create_product(
                        s,
                        name=p_name.value,
                        category_id=p_cat.value,
                        kind=p_kind.value,
                        price_tiyn=round(p_price.value * 100),
                    )
                except (ValueError, IntegrityError) as e:
                    s.rollback()
                    ui.notify(str(e), color="red")
                    return
            p_name.value = ""
            refresh()

        ui.button("Добавить товар", on_click=add_product)

    refresh()
