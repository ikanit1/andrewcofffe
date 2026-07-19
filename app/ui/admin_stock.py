from nicegui import ui
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Ingredient, Product, RecipeItem


@ui.page("/admin/stock")
def admin_stock_page() -> None:
    ui.label("Склад: позиции и тех-карты").classes("text-2xl font-bold")

    ing_container = ui.column().classes("w-full max-w-3xl gap-1")

    def refresh_ingredients() -> None:
        ing_container.clear()
        with ing_container, SessionLocal() as session:
            rows = session.scalars(
                select(Ingredient).where(Ingredient.is_active).order_by(Ingredient.name)
            ).all()
            columns = [
                {"name": "name", "label": "Название", "field": "name"},
                {"name": "stock", "label": "Остаток", "field": "stock"},
                {"name": "threshold", "label": "Порог", "field": "threshold"},
            ]
            data = [
                {
                    "name": f"{i.name} ({i.unit})",
                    "stock": i.stock_qty,
                    "threshold": i.low_stock_threshold,
                }
                for i in rows
            ]
            ui.table(columns=columns, rows=data).classes("w-full")

    with ui.expansion("Добавить позицию склада").classes("w-full max-w-3xl"):
        n = ui.input("Название (напр. Молоко)")
        u = ui.select({"г": "граммы", "мл": "миллилитры", "шт": "штуки"}, label="Единица", value="мл")
        t = ui.number(label="Порог низкого остатка", value=0, min=0, format="%.0f")

        def add_ing() -> None:
            if not n.value:
                return
            with SessionLocal() as s:
                s.add(Ingredient(name=n.value, unit=u.value, low_stock_threshold=int(t.value or 0)))
                s.commit()
            n.value = ""
            refresh_ingredients()

        ui.button("Добавить", on_click=add_ing)

    ui.separator()
    ui.label("Тех-карта товара").classes("text-xl")
    recipe_container = ui.column().classes("w-full max-w-3xl gap-1")

    with SessionLocal() as session:
        prod_options = {
            p.id: p.name
            for p in session.scalars(select(Product).where(Product.kind == "prepared")).all()
        }
        ing_options = {
            i.id: f"{i.name} ({i.unit})"
            for i in session.scalars(select(Ingredient).where(Ingredient.is_active)).all()
        }

    sel_product = ui.select(prod_options, label="Товар", on_change=lambda e: refresh_recipe())

    def refresh_recipe() -> None:
        recipe_container.clear()
        if not sel_product.value:
            return
        with recipe_container, SessionLocal() as session:
            items = session.scalars(
                select(RecipeItem).where(RecipeItem.product_id == sel_product.value)
            ).all()
            for it in items:
                ing = session.get(Ingredient, it.ingredient_id)
                with ui.row().classes("items-center gap-4"):
                    ui.label(f"{ing.name}: {it.qty} {ing.unit}")

                    def remove(item_id=it.id) -> None:
                        with SessionLocal() as s:
                            obj = s.get(RecipeItem, item_id)
                            if obj:
                                s.delete(obj)
                                s.commit()
                        refresh_recipe()

                    ui.button("Удалить", on_click=remove, color="red")

    with ui.row().classes("items-end gap-4"):
        sel_ing = ui.select(ing_options, label="Ингредиент")
        qty = ui.number(label="Кол-во на порцию", value=0, min=1, format="%.0f")

        def add_line() -> None:
            if not (sel_product.value and sel_ing.value and qty.value):
                ui.notify("Выберите товар, ингредиент и количество", color="red")
                return
            with SessionLocal() as s:
                s.add(
                    RecipeItem(
                        product_id=sel_product.value,
                        ingredient_id=sel_ing.value,
                        qty=int(qty.value),
                    )
                )
                s.commit()
            refresh_recipe()

        ui.button("Добавить в тех-карту", on_click=add_line)

    refresh_ingredients()
