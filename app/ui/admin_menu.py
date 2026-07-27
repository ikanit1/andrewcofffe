from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from nicegui import ui

from app.db import SessionLocal
from app.models import Category, Ingredient, RecipeItem
from app.services import catalog_service as cs
from app.services import images
from app.ui.design import category_icon
from app.ui.layout import admin_header

KIND_LABELS = {"prepared": "Приготовленный", "retail": "Штучный"}
KIND_FILTERS = (("all", "Все"), ("prepared", "Приготовленные"), ("retail", "Штучные"))

_ROW_STYLE = (
    "width:100%;border-radius:16px;padding:12px 14px;background:var(--surface-card);"
    "border:1px solid {border};opacity:{opacity}"
)


def _hint_for(session, p) -> tuple[str, str]:
    """Подсказка под названием: сигналит о пустой тех-карте или отсутствии склада —
    иначе владелец не узнает об этом, пока не откроет отдельный экран склада."""
    ok, warn = "var(--text-secondary)", "var(--status-warning)"
    if p.kind == "prepared":
        n = session.scalar(
            select(func.count()).select_from(RecipeItem).where(RecipeItem.product_id == p.id)
        )
        if n:
            return f"Тех-карта: {n} поз.", ok
        return "Тех-карта не заполнена — себестоимость 0", warn
    if p.ingredient_id is not None:
        ing = session.get(Ingredient, p.ingredient_id)
        return f"Складская позиция: {ing.name if ing else '?'}", ok
    return "Не привязан к складу — остаток не списывается", warn


@ui.page("/admin/menu")
def admin_menu_page() -> None:
    from app.ui.guard import require_admin
    if not require_admin():
        return
    admin_header()

    state = {"cat": "all", "kind": "all"}
    pending: dict[int, int] = {}  # product_id -> новая цена в тиынах (несохранённая)

    with ui.column().classes("w-full max-w-5xl gap-4 mx-auto"):
        with ui.row().classes("w-full items-end justify-between gap-4 flex-wrap"):
            with ui.column().classes("gap-0"):
                ui.label("Меню и цены").classes("text-2xl font-black leading-tight")
                summary_label = ui.label("").classes("text-sm") \
                    .style("color: var(--text-secondary)")
            with ui.row().classes("gap-2"):
                ui.button("Категория", icon="playlist_add", on_click=lambda: _open_add(False)) \
                    .props("outline no-caps")
                ui.button("Добавить товар", icon="add", on_click=lambda: _open_add(True)) \
                    .props("no-caps")

        with ui.row().classes("w-full gap-4 items-start no-wrap"):
            sidebar = ui.column().classes("gap-1 p-2 rounded-2xl") \
                .style("width:236px;flex:none;position:sticky;top:88px;"
                       "background:var(--surface-card);border:1px solid var(--border-subtle)")
            with ui.column().classes("gap-3 flex-1 min-w-0"):
                with ui.row().classes("items-center gap-2 flex-wrap w-full"):
                    search = ui.input(placeholder="Поиск по названию") \
                        .props("outlined dense clearable") \
                        .classes("flex-1").style("min-width:220px")
                    kind_row = ui.row().classes("gap-2")
                content = ui.column().classes("gap-4 w-full")

    dirty_host = ui.row()

    def _load():
        with SessionLocal() as session:
            return cs.list_menu_admin(session)

    def _matches(p) -> bool:
        if state["kind"] != "all" and p.kind != state["kind"]:
            return False
        query = (search.value or "").strip().lower()
        return not query or query in p.name.lower()

    def _pick_cat(key: str) -> None:
        state["cat"] = key
        refresh()

    def _pick_kind(key: str) -> None:
        state["kind"] = key
        refresh()

    def _on_search_change() -> None:
        refresh()

    search.on_value_change(_on_search_change)

    def _render_sidebar(menu) -> None:
        sidebar.clear()
        with sidebar:
            _sidebar_item("all", "Все", "apps", sum(len(prods) for _, prods in menu))
            for cat, prods in menu:
                _sidebar_item(str(cat.id), cat.name, category_icon(cat.name), len(prods))
                if state["cat"] == str(cat.id):
                    # Действия показываем только у выбранной категории: иначе
                    # в списке из десяти разделов рябит от кнопок.
                    with ui.row().classes("gap-1 pl-2 pb-1"):
                        ui.button("Имя", icon="edit",
                                  on_click=lambda c=cat: _rename_category(c.id, c.name)) \
                            .props("flat dense no-caps").classes("text-xs")
                        ui.button("Удалить", icon="delete",
                                  on_click=lambda c=cat, n=len(prods):
                                      _delete_category(c.id, c.name, n)) \
                            .props("flat dense no-caps color=negative").classes("text-xs")

    def _rename_category(cat_id: int, name: str) -> None:
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Категория «{name}»").classes("text-lg font-bold")
            field = ui.input("Название", value=name).classes("w-full")

            def confirm() -> None:
                try:
                    with SessionLocal() as s:
                        cs.rename_category(s, cat_id, field.value)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                ui.notify("Переименовано", color="green")
                refresh()

            field.on("keydown.enter", lambda _: confirm())
            with ui.row().classes("gap-2"):
                ui.button("Сохранить", on_click=confirm)
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    def _delete_category(cat_id: int, name: str, count: int) -> None:
        """Товар обязан лежать в категории, поэтому непустую удаляем только
        вместе с переносом товаров — иначе они остались бы без раздела."""
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Удалить категорию «{name}»?").classes("text-lg font-bold")
            target = None
            if count:
                ui.label(f"В категории {count} товаров. Товар не может остаться "
                         "без категории — выберите, куда их перенести.") \
                    .classes("text-sm").style("color: var(--text-secondary)")
                with SessionLocal() as s:
                    opts = {c.id: c.name for c in s.scalars(
                        select(Category).where(Category.id != cat_id)
                        .order_by(Category.sort_order, Category.name)).all()}
                if not opts:
                    ui.label("Других категорий нет — сначала создайте ещё одну.") \
                        .style("color: var(--status-danger)")
                else:
                    target = ui.select(opts, value=next(iter(opts)),
                                       label="Перенести в").classes("w-full")
            else:
                ui.label("Категория пустая.").classes("text-sm") \
                    .style("color: var(--text-secondary)")

            def confirm() -> None:
                try:
                    with SessionLocal() as s:
                        moved = cs.delete_category(
                            s, cat_id,
                            move_to_id=target.value if target is not None else None)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                state["cat"] = "all"
                ui.notify(f"Категория удалена, перенесено товаров: {moved}",
                          color="green")
                refresh()

            with ui.row().classes("gap-2"):
                if not count or target is not None:
                    ui.button("Удалить", on_click=confirm, color="negative")
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    def _sidebar_item(key: str, name: str, icon: str, count: int) -> None:
        cls = "cp-pill-active" if state["cat"] == key else "cp-pill-idle"
        btn = ui.button(on_click=lambda key=key: _pick_cat(key)) \
            .props("flat no-caps align=left").classes(f"w-full h-12 rounded-xl cp-hover {cls}")
        with btn, ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.icon(icon, size="20px")
            ui.label(name).classes("flex-1 text-left truncate text-sm")
            ui.label(str(count)).classes("text-xs")

    def _render_kind_filters() -> None:
        kind_row.clear()
        with kind_row:
            for key, label in KIND_FILTERS:
                cls = "cp-pill-active" if state["kind"] == key else "cp-pill-idle"
                ui.button(label, on_click=lambda key=key: _pick_kind(key)) \
                    .props("flat no-caps").classes(f"h-12 px-4 rounded-full cp-hover {cls}")

    def _on_price_change(pid: int, orig_tiyn: int, tenge, row) -> None:
        new_tiyn = round((tenge or 0) * 100)
        if new_tiyn == orig_tiyn or new_tiyn <= 0:
            pending.pop(pid, None)
            row.style(replace=_ROW_STYLE.format(border="var(--border-subtle)", opacity=1))
        else:
            pending[pid] = new_tiyn
            row.style(replace=_ROW_STYLE.format(border="var(--brand-primary)", opacity=1))
        _render_dirty_bar()

    def _item_row(session, cat, p) -> None:
        border = "var(--brand-primary)" if p.id in pending else "var(--border-subtle)"
        opacity = 1 if p.is_active else 0.55
        with ui.row().classes("items-center gap-3 no-wrap") \
                .style(_ROW_STYLE.format(border=border, opacity=opacity)) as row:
            with ui.row().classes("items-center justify-center overflow-hidden") \
                    .style("width:56px;height:56px;border-radius:12px;"
                           "background:var(--surface-sunken);flex:none"):
                if p.has_image:
                    # fit=cover — свойство QImg; CSS-класс object-cover на обёртке
                    # не доходит до самого <img> внутри компонента Quasar.
                    ui.image(f"/product-image/{p.id}").props("fit=cover no-spinner") \
                        .classes("w-full h-full")
                else:
                    ui.icon(category_icon(cat.name), size="26px").style("color:var(--brand-primary)")

            with ui.column().classes("gap-0 flex-1 min-w-0"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label(p.name).classes("text-base font-bold")
                    ui.badge(KIND_LABELS[p.kind]).props("rounded") \
                        .style("background:var(--surface-sunken);color:var(--text-secondary)")
                    if not p.is_active:
                        ui.badge("Убран из меню").props("rounded") \
                            .style("background:var(--status-danger-bg);color:var(--status-danger)")
                hint, hint_color = _hint_for(session, p)
                ui.label(hint).classes("text-xs").style(f"color:{hint_color}")

            with ui.row().classes("items-center gap-2 flex-none"):
                price_in = ui.number(value=p.price_tiyn / 100, min=1, format="%.0f") \
                    .props("dense outlined suffix=тг inputmode=numeric") \
                    .classes("text-right font-bold").style("width:130px")
                price_in.on_value_change(
                    lambda e, pid=p.id, orig=p.price_tiyn, row=row: _on_price_change(pid, orig, e.value, row)
                )
                ui.button(icon="photo_camera",
                          on_click=lambda pid=p.id, name=p.name, has=p.has_image: _photo_dialog(pid, name, has)) \
                    .props("flat dense round").tooltip("Фото товара")
                if p.is_active:
                    ui.button(icon="visibility_off",
                              on_click=lambda pid=p.id, name=p.name: _remove(pid, name)) \
                        .props("flat dense round").tooltip("Убрать из меню")
                else:
                    ui.button(icon="undo", color="positive",
                              on_click=lambda pid=p.id, name=p.name: _restore(pid, name)) \
                        .props("flat dense round").tooltip("Вернуть в меню")

    def _render_content(menu) -> None:
        content.clear()
        shown_total = 0
        hidden_total = 0
        with content:
            any_rendered = False
            with SessionLocal() as session:
                for cat, prods in menu:
                    if state["cat"] not in ("all", str(cat.id)):
                        continue
                    rows = [p for p in prods if _matches(p)]
                    for p in prods:
                        if p.is_active:
                            shown_total += 1
                        else:
                            hidden_total += 1
                    if not rows:
                        continue
                    any_rendered = True
                    with ui.column().classes("gap-2 w-full"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(cat.name.upper()).classes("text-xs font-bold") \
                                .style("color:var(--text-secondary);letter-spacing:.07em")
                            ui.element("div").classes("flex-1 h-px") \
                                .style("background:var(--border-subtle)")
                        for p in rows:
                            _item_row(session, cat, p)
            if not any_rendered:
                with ui.column().classes("items-center gap-2 w-full py-12") \
                        .style("color:var(--text-secondary);background:var(--surface-card);"
                               "border:1px dashed var(--border-default);border-radius:16px"):
                    ui.icon("search_off", size="32px")
                    ui.label("Ничего не найдено")
        summary = f"{shown_total} товаров"
        if hidden_total:
            summary += f", {hidden_total} скрыто"
        summary_label.set_text(summary)

    def _render_dirty_bar() -> None:
        dirty_host.clear()
        if not pending:
            return
        with dirty_host:
            with ui.row().classes(
                "fixed bottom-6 left-1/2 -translate-x-1/2 z-50 items-center gap-3 "
                "rounded-2xl px-4 py-2 shadow-lg"
            ).style("background:var(--surface-card);border:1px solid var(--border-default)"):
                ui.label(f"Изменено цен: {len(pending)}").classes("text-sm") \
                    .style("color:var(--text-secondary)")
                ui.button("Отменить", on_click=_cancel_changes).props("flat no-caps")
                ui.button("Сохранить", on_click=_save_changes).props("no-caps")

    def _cancel_changes() -> None:
        pending.clear()
        refresh()

    def _save_changes() -> None:
        n = len(pending)
        with SessionLocal() as s:
            for pid, new_price in pending.items():
                try:
                    cs.update_product(s, pid, price_tiyn=new_price)
                except (ValueError, IntegrityError) as e:
                    s.rollback()
                    ui.notify(str(e), color="red")
                    return
        pending.clear()
        ui.notify(f"Цены сохранены: {n}", color="green")
        refresh()

    def _photo_dialog(pid: int, name: str, has_image: bool) -> None:
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Фото: {name}").classes("text-lg font-bold")
            if has_image:
                ui.image(f"/product-image/{pid}").classes("w-full rounded-xl") \
                    .style("max-height:200px;object-fit:cover")

            async def upload(e) -> None:
                data = await e.file.read()
                try:
                    with SessionLocal() as s:
                        cs.set_product_image(s, pid, data, e.file.content_type)
                except ValueError as err:
                    ui.notify(str(err), color="red")
                    return
                dlg.close()
                ui.notify("Фото загружено", color="green")
                refresh()

            # max_file_size режет великанов до чтения в память; сервер всё равно
            # перепроверяет размер и формат — на клиентскую проверку полагаться нельзя.
            ui.upload(auto_upload=True, max_files=1, on_upload=upload,
                      max_file_size=images.MAX_IMAGE_BYTES,
                      on_rejected=lambda: ui.notify(
                          f"Файл больше {images.MAX_IMAGE_BYTES // (1024 * 1024)} МБ", color="red")) \
                .props("accept=image/jpeg,image/png,image/gif,image/webp flat dense") \
                .classes("w-full")

            if has_image:
                def remove_photo() -> None:
                    with SessionLocal() as s:
                        cs.clear_product_image(s, pid)
                    dlg.close()
                    ui.notify("Фото удалено", color="orange")
                    refresh()

                ui.button("Убрать фото", on_click=remove_photo) \
                    .props("outline no-caps color=negative").classes("w-full")

            ui.button("Закрыть", on_click=dlg.close).props("flat no-caps").classes("w-full")
        dlg.open()

    def _remove(pid: int, name: str) -> None:
        with SessionLocal() as s:
            cs.update_product(s, pid, is_active=False)
        pending.pop(pid, None)
        ui.notify(f"«{name}» убран из меню", color="orange")
        refresh()

    def _restore(pid: int, name: str) -> None:
        with SessionLocal() as s:
            cs.update_product(s, pid, is_active=True)
        ui.notify(f"«{name}» возвращён в меню", color="green")
        refresh()

    def refresh() -> None:
        menu = _load()
        _render_sidebar(menu)
        _render_kind_filters()
        _render_content(menu)
        _render_dirty_bar()

    def _open_add(is_product: bool) -> None:
        with SessionLocal() as session:
            cats = cs.list_menu_admin(session)
        if is_product and not cats:
            ui.notify("Сначала добавьте категорию", color="red")
            return

        picked = {"cat": cats[0][0].id if cats else None, "kind": "prepared"}

        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-96"):
            ui.label("Добавить товар" if is_product else "Новая категория") \
                .classes("text-xl font-black")
            name_in = ui.input("Название").classes("w-full")
            error_label = ui.label("").style("color:var(--status-danger)")
            price_in = None
            cat_row = None
            kind_row_dlg = None

            def render_cat_pills() -> None:
                cat_row.clear()
                with cat_row:
                    for cat, _ in cats:
                        cls = "cp-pill-active" if picked["cat"] == cat.id else "cp-pill-idle"

                        def pick(cat_id=cat.id) -> None:
                            picked["cat"] = cat_id
                            render_cat_pills()

                        ui.button(cat.name, on_click=pick).props("flat no-caps dense") \
                            .classes(f"h-10 px-3 rounded-full cp-hover {cls}")

            def render_kind_pills() -> None:
                kind_row_dlg.clear()
                with kind_row_dlg:
                    for key, label in (("prepared", KIND_LABELS["prepared"]),
                                       ("retail", KIND_LABELS["retail"])):
                        cls = "cp-pill-active" if picked["kind"] == key else "cp-pill-idle"

                        def pick(key=key) -> None:
                            picked["kind"] = key
                            render_kind_pills()

                        ui.button(label, on_click=pick).props("flat no-caps dense") \
                            .classes(f"h-10 px-3 rounded-full cp-hover {cls}")

            if is_product:
                ui.label("Категория").classes("text-xs").style("color:var(--text-secondary)")
                cat_row = ui.row().classes("gap-2 flex-wrap")
                ui.label("Тип").classes("text-xs mt-1").style("color:var(--text-secondary)")
                kind_row_dlg = ui.row().classes("gap-2 flex-wrap")
                render_cat_pills()
                render_kind_pills()
                price_in = ui.number(label="Цена, тг", value=0, min=1, format="%.0f") \
                    .classes("w-full")

            def submit() -> None:
                name = (name_in.value or "").strip()
                if not name:
                    error_label.set_text("Введите название")
                    return
                if not is_product:
                    with SessionLocal() as s:
                        try:
                            cs.create_category(s, name)
                        except IntegrityError as e:
                            s.rollback()
                            error_label.set_text(str(e))
                            return
                    dlg.close()
                    ui.notify(f"Категория «{name}» добавлена", color="green")
                    refresh()
                    return
                price = price_in.value
                if price is None or price <= 0:
                    error_label.set_text("Введите цену")
                    return
                with SessionLocal() as s:
                    try:
                        # Штучному товару сразу заводится позиция склада: без неё
                        # он продаётся, а остаток молча не уменьшается.
                        cs.create_product_with_stock(
                            s, name=name, category_id=picked["cat"],
                            kind=picked["kind"], price_tiyn=round(price * 100))
                    except (ValueError, IntegrityError) as e:
                        s.rollback()
                        error_label.set_text(str(e))
                        return
                dlg.close()
                if picked["kind"] == "retail":
                    ui.notify(f"«{name}» добавлен, позиция склада заведена "
                              "(остаток 0 — сделайте приход)", color="green")
                else:
                    ui.notify(f"«{name}» добавлен. Заполните тех-карту в разделе "
                              "«Склад», иначе списания не будет", color="orange")
                state["cat"] = str(picked["cat"])
                refresh()

            ui.button("Добавить товар" if is_product else "Добавить категорию",
                      on_click=submit).props("no-caps").classes("w-full")
            ui.button("Отмена", on_click=dlg.close).props("outline no-caps").classes("w-full")
        dlg.open()

    refresh()
