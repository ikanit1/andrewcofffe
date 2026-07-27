from nicegui import ui
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Ingredient, Product, RecipeItem, StockCategory
from app.services import inventory_service as inv
from app.ui.design import numpad
from app.ui.layout import admin_header


@ui.page("/admin/stock")
def admin_stock_page() -> None:
    from app.ui.guard import require_admin
    if not require_admin():
        return
    admin_header()

    ui.label("Склад: позиции и тех-карты").classes("text-2xl font-bold")

    with ui.row().classes("gap-2"):
        ui.button("Приход товара", icon="local_shipping",
                  on_click=lambda: ui.navigate.to("/stock/purchase"))
        ui.button("Разделы склада", icon="folder",
                  on_click=lambda: _categories_dialog()).props("outline")

    ing_container = ui.column().classes("w-full max-w-3xl gap-1")

    def _categories_dialog() -> None:
        """Разделы склада: добавить, переименовать, удалить."""
        with ui.dialog() as dlg, ui.card().classes("gap-3 w-full max-w-md"):
            ui.label("Разделы склада").classes("text-lg font-bold")
            body = ui.column().classes("w-full gap-1")

            def redraw() -> None:
                body.clear()
                with body, SessionLocal() as s:
                    cats = s.scalars(select(StockCategory)
                                     .order_by(StockCategory.sort_order,
                                               StockCategory.name)).all()
                    if not cats:
                        ui.label("Разделов пока нет — позиции лежат общим списком") \
                            .classes("text-sm").style("color: var(--text-secondary)")
                    for c in cats:
                        n = s.query(Ingredient).filter(
                            Ingredient.category_id == c.id).count()
                        with ui.row().classes("items-center gap-2 w-full no-wrap"):
                            ui.label(c.name).classes("flex-1 font-medium")
                            ui.label(f"{n}").classes("text-sm") \
                                .style("color: var(--text-secondary)")
                            ui.button(icon="edit",
                                      on_click=lambda c=c: _rename_cat(c.id, c.name)) \
                                .props("flat dense")
                            ui.button(icon="delete",
                                      on_click=lambda c=c, n=n: _delete_cat(c.id, c.name, n)) \
                                .props("flat dense color=negative")

            new_name = ui.input("Новый раздел").classes("w-full")

            def add() -> None:
                try:
                    with SessionLocal() as s:
                        inv.create_stock_category(s, new_name.value)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                new_name.value = ""
                redraw()
                refresh_ingredients()

            new_name.on("keydown.enter", lambda _: add())
            with ui.row().classes("gap-2"):
                ui.button("Добавить", icon="add", on_click=add)
                ui.button("Закрыть", on_click=dlg.close).props("flat")
            redraw()
        dlg.open()

    def _rename_cat(cat_id: int, name: str) -> None:
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Раздел «{name}»").classes("text-lg font-bold")
            field = ui.input("Название", value=name).classes("w-full")

            def confirm() -> None:
                try:
                    with SessionLocal() as s:
                        inv.rename_stock_category(s, cat_id, field.value)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                ui.notify("Переименовано", color="green")
                refresh_ingredients()

            with ui.row().classes("gap-2"):
                ui.button("Сохранить", on_click=confirm)
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    def _delete_cat(cat_id: int, name: str, count: int) -> None:
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Удалить раздел «{name}»?").classes("text-lg font-bold")
            if count:
                ui.label(f"{count} позиц. перейдут в «Без раздела». Сами позиции "
                         "и остатки не удаляются.").classes("text-sm") \
                    .style("color: var(--text-secondary)")
            else:
                ui.label("Раздел пустой.").classes("text-sm") \
                    .style("color: var(--text-secondary)")

            def confirm() -> None:
                try:
                    with SessionLocal() as s:
                        moved = inv.delete_stock_category(s, cat_id)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                ui.notify(f"Раздел удалён, позиций без раздела: {moved}", color="green")
                refresh_ingredients()

            with ui.row().classes("gap-2"):
                ui.button("Удалить", on_click=confirm, color="negative")
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    def _move_dialog(ing_id: int, name: str, current_id: int | None) -> None:
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Раздел для «{name}»").classes("text-lg font-bold")
            with SessionLocal() as s:
                opts = {c.id: c.name for c in s.scalars(
                    select(StockCategory).order_by(StockCategory.name)).all()}
            opts[0] = "— без раздела —"
            sel = ui.select(opts, value=current_id or 0, label="Раздел").classes("w-full")

            def confirm() -> None:
                try:
                    with SessionLocal() as s:
                        inv.set_ingredient_category(s, ing_id, sel.value or None)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                refresh_ingredients()

            with ui.row().classes("gap-2"):
                ui.button("Сохранить", on_click=confirm)
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    def refresh_ingredients() -> None:
        ing_container.clear()
        with ing_container, SessionLocal() as session:
            rows = session.scalars(
                select(Ingredient).where(Ingredient.is_active).order_by(Ingredient.name)
            ).all()
            if not rows:
                ui.label("Позиций склада пока нет").style("color: var(--text-secondary)")
                return
            cats = {c.id: c.name for c in session.scalars(
                select(StockCategory).order_by(StockCategory.sort_order,
                                               StockCategory.name)).all()}
            # Группируем по разделам; «Без раздела» показываем последним
            groups: dict = {cid: [] for cid in cats}
            groups[None] = []
            for i in rows:
                groups.setdefault(i.category_id if i.category_id in cats else None,
                                  []).append(i)
            order = [(cid, cats[cid]) for cid in cats] + [(None, "Без раздела")]

            for cid, cname in order:
                items = groups.get(cid) or []
                if not items:
                    continue
                if len(cats) or cid is not None:
                    with ui.row().classes("w-full items-baseline gap-2 mt-2"):
                        ui.label(cname).classes("text-xs uppercase tracking-wider") \
                            .style("color: var(--text-secondary)")
                        ui.label(f"{len(items)}").classes("text-xs") \
                            .style("color: var(--text-muted)")
                _render_items(items)

    def _render_items(rows) -> None:
            for i in rows:
                low = i.low_stock_threshold > 0 and i.stock_qty < i.low_stock_threshold
                with ui.card().classes("w-full p-3 gap-2"):
                    with ui.row().classes("items-center gap-3 w-full no-wrap"):
                        with ui.column().classes("gap-0 flex-1 min-w-0"):
                            ui.label(i.name).classes("text-base font-bold leading-tight")
                            ui.label(f"порог {i.low_stock_threshold} {i.unit}").classes("text-xs") \
                                .style("color: var(--text-secondary)")
                        with ui.column().classes("gap-0 items-end"):
                            ui.label(f"{i.stock_qty} {i.unit}").classes("text-lg font-black") \
                                .style("color: var(--status-danger)" if low else "")
                            if low:
                                ui.label("на исходе").classes("text-xs") \
                                    .style("color: var(--status-danger)")
                        ui.button("Остаток", icon="tune",
                                  on_click=lambda i=i: _adjust_dialog(i.id, i.name, i.unit,
                                                                      i.stock_qty)) \
                            .props("flat dense")
                        ui.button(icon="edit",
                                  on_click=lambda i=i: _edit_dialog(i.id, i.name, i.unit,
                                                                    i.low_stock_threshold)) \
                            .props("flat dense").tooltip("Название, единица, порог")
                        ui.button(icon="folder",
                                  on_click=lambda i=i: _move_dialog(i.id, i.name,
                                                                    i.category_id)) \
                            .props("flat dense").tooltip("Перенести в раздел")
                        ui.button(icon="visibility_off",
                                  on_click=lambda i=i: _hide(i.id, i.name)) \
                            .props("flat dense color=negative").tooltip("Убрать из списка")

    def _adjust_dialog(ing_id: int, name: str, unit: str, current: int) -> None:
        """Пересчёт остатка: вводим фактическое количество, разница уходит в журнал."""
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Остаток: {name}").classes("text-lg font-bold")
            ui.label(f"Сейчас в системе: {current} {unit}").classes("text-sm") \
                .style("color: var(--text-secondary)")
            qty = ui.number(f"Фактически на складе, {unit}", value=current, min=0,
                            format="%.0f").props("readonly").classes("w-full")
            diff_label = ui.label("").classes("text-sm font-bold")

            def show_diff() -> None:
                d = int(qty.value or 0) - current
                if d == 0:
                    diff_label.set_text("Без изменений")
                    diff_label.style("color: var(--text-secondary)")
                else:
                    diff_label.set_text(f"Изменение: {d:+d} {unit}")
                    diff_label.style("color: var(--status-warning)")

            numpad(qty, on_change=show_diff)
            show_diff()
            reason = ui.select(
                {"инвентаризация": "Инвентаризация (пересчёт)",
                 "списание": "Списание (порча, брак)",
                 "исправление ошибки": "Исправление ошибки ввода",
                 "прочее": "Прочее"},
                value="инвентаризация", label="Причина").classes("w-full")

            def confirm() -> None:
                try:
                    with SessionLocal() as s:
                        inv.adjust_stock(s, ing_id, new_qty=int(qty.value or 0),
                                         note=reason.value)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                ui.notify(f"Остаток «{name}» обновлён", color="green")
                refresh_ingredients()

            with ui.row().classes("gap-2"):
                ui.button("Сохранить", on_click=confirm)
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    def _edit_dialog(ing_id: int, name: str, unit: str, threshold: int) -> None:
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Позиция: {name}").classes("text-lg font-bold")
            name_in = ui.input("Название", value=name).classes("w-full")
            unit_in = ui.select({"г": "граммы", "мл": "миллилитры", "шт": "штуки"},
                                value=unit, label="Единица").classes("w-full")
            thr_in = ui.number("Порог «на исходе»", value=threshold, min=0,
                               format="%.0f").props("readonly").classes("w-full")
            numpad(thr_in)
            ui.label("Порог 0 — уведомления по этой позиции отключены").classes("text-xs") \
                .style("color: var(--text-secondary)")

            def confirm() -> None:
                try:
                    with SessionLocal() as s:
                        inv.update_ingredient(s, ing_id, name=name_in.value,
                                              unit=unit_in.value,
                                              low_stock_threshold=int(thr_in.value or 0))
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                ui.notify("Сохранено", color="green")
                refresh_ingredients()
                reload_ing_options()

            with ui.row().classes("gap-2"):
                ui.button("Сохранить", on_click=confirm)
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    def _hide(ing_id: int, name: str) -> None:
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Убрать «{name}» из списка?").classes("text-lg font-bold")
            ui.label("Позиция скрывается, но не удаляется: на неё ссылаются прошлые "
                     "движения склада и тех-карты.").classes("text-sm") \
                .style("color: var(--text-secondary)")

            def confirm() -> None:
                with SessionLocal() as s:
                    inv.set_ingredient_active(s, ing_id, False)
                dlg.close()
                ui.notify(f"«{name}» убрана из списка", color="green")
                refresh_ingredients()
                reload_ing_options()

            with ui.row().classes("gap-2"):
                ui.button("Убрать", on_click=confirm, color="negative")
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    def reload_ing_options() -> None:
        with SessionLocal() as session:
            sel_ing.set_options(
                {
                    i.id: f"{i.name} ({i.unit})"
                    for i in session.scalars(select(Ingredient).where(Ingredient.is_active)).all()
                }
            )

    with ui.expansion("Добавить позицию склада").classes("w-full max-w-3xl"):
        n = ui.input("Название (напр. Молоко)").classes("w-full")
        u = ui.select({"г": "граммы", "мл": "миллилитры", "шт": "штуки"},
                      label="Единица", value="мл").classes("w-full")
        t = ui.number(label="Порог низкого остатка", value=0, min=0,
                      format="%.0f").props("readonly").classes("w-full")
        numpad(t)

        def add_ing() -> None:
            if not n.value:
                return
            with SessionLocal() as s:
                try:
                    s.add(
                        Ingredient(name=n.value, unit=u.value, low_stock_threshold=int(t.value or 0))
                    )
                    s.commit()
                except IntegrityError as e:
                    s.rollback()
                    ui.notify(str(e), color="red")
                    return
            n.value = ""
            refresh_ingredients()
            reload_ing_options()

        ui.button("Добавить", on_click=add_ing)

    ui.separator()
    ui.label("Тех-карта товара").classes("text-xl")
    recipe_container = ui.column().classes("w-full max-w-3xl gap-1")

    with SessionLocal() as session:
        prod_options = {
            p.id: p.name
            for p in session.scalars(
                select(Product).where(Product.kind == "prepared", Product.is_active)
            ).all()
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
        qty = ui.number(label="Кол-во на порцию", value=1, min=1, format="%.0f")

        def add_line() -> None:
            if not (sel_product.value and sel_ing.value):
                ui.notify("Выберите товар и ингредиент", color="red")
                return
            if qty.value is None or qty.value <= 0:
                ui.notify("Введите количество", color="red")
                return
            with SessionLocal() as s:
                try:
                    s.add(
                        RecipeItem(
                            product_id=sel_product.value,
                            ingredient_id=sel_ing.value,
                            qty=round(qty.value),
                        )
                    )
                    s.commit()
                except IntegrityError as e:
                    s.rollback()
                    ui.notify(str(e), color="red")
                    return
            refresh_recipe()

        ui.button("Добавить в тех-карту", on_click=add_line)

    refresh_ingredients()
