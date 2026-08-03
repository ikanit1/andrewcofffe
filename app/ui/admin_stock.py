"""Склад: сколько штук каждого товара лежит на точке.

Никаких ингредиентов и тех-карт — считается сам товар из меню. Остаток можно
не вести вовсе: у кофе, который варят из общих запасов, количества не
существует, и такой товар помечается «не считается».

Правится здесь всё: остаток, порог предупреждения, закупочная цена, журнал
движений. Продажу склад никогда не блокирует — остаток просто уходит в минус.
"""
from nicegui import ui

from app.db import SessionLocal
from app.services import inventory_service as inv
from app.timezone import to_almaty
from app.ui.design import confirm_with_pin, empty_state, money_tg, numpad
from app.ui.layout import admin_header

_CARD = ("background: var(--surface-card); border:1px solid var(--border-subtle);"
         "border-radius:16px")
_ADJUST_REASONS = {
    "инвентаризация": "Инвентаризация (пересчёт)",
    "списание": "Списание (порча, брак)",
    "исправление ошибки": "Исправление ошибки ввода",
    "прочее": "Прочее",
}


@ui.page("/admin/stock")
def admin_stock_page() -> None:
    from app.ui.guard import require_admin
    if not require_admin():
        return
    admin_header()

    state = {"query": "", "hidden": False, "only_tracked": False}

    root = ui.column().classes("w-full gap-4 mx-auto").style("max-width:1000px")

    # ------------------------------------------------------------------
    # действия
    # ------------------------------------------------------------------

    def _stock_dialog(row: inv.StockRow) -> None:
        """Остаток товара: ввести фактическое количество или перестать считать."""
        current = row.stock_qty or 0
        with ui.dialog() as dlg, ui.card().classes("gap-3 w-full max-w-md"):
            ui.label(f"Остаток: {row.name}").classes("text-lg font-bold")
            if row.tracked:
                ui.label(f"Сейчас в системе: {row.stock_qty} шт").classes("text-sm") \
                    .style("color: var(--text-secondary)")
            else:
                ui.label("Сейчас товар не считается — введите количество, чтобы "
                         "начать вести остаток.").classes("text-sm") \
                    .style("color: var(--text-secondary)")
            qty = ui.number("Фактически на складе, шт", value=current, min=0,
                            format="%.0f").props("readonly outlined").classes("w-full")
            diff = ui.label("").classes("text-sm font-bold")

            def show_diff() -> None:
                if not row.tracked:
                    diff.set_text(f"Начнём считать с {int(qty.value or 0)} шт")
                    diff.style("color: var(--text-secondary)")
                    return
                d = int(qty.value or 0) - current
                diff.set_text("Без изменений" if d == 0 else f"Изменение: {d:+d} шт")
                diff.style("color: var(--text-secondary)" if d == 0
                           else "color: var(--status-warning)")

            numpad(qty, on_change=show_diff)
            show_diff()
            reason = ui.select(_ADJUST_REASONS, value="инвентаризация",
                               label="Причина").classes("w-full")

            def save() -> None:
                try:
                    with SessionLocal() as s:
                        inv.set_stock(s, row.product_id, new_qty=int(qty.value or 0),
                                      note=reason.value)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                ui.notify(f"Остаток «{row.name}» обновлён", color="green")
                refresh()

            def stop_tracking() -> None:
                with SessionLocal() as s:
                    inv.set_stock(s, row.product_id, new_qty=None)
                dlg.close()
                ui.notify(f"«{row.name}» больше не считается", color="green")
                refresh()

            with ui.row().classes("gap-2 flex-wrap"):
                ui.button("Сохранить", on_click=save).props("no-caps")
                if row.tracked:
                    ui.button("Не считать этот товар", on_click=stop_tracking) \
                        .props("flat no-caps color=negative")
                ui.button("Отмена", on_click=dlg.close).props("flat no-caps")
        dlg.open()

    def _settings_dialog(row: inv.StockRow) -> None:
        """Порог предупреждения и закупочная цена."""
        with ui.dialog() as dlg, ui.card().classes("gap-3 w-full max-w-md"):
            ui.label(f"Настройки: {row.name}").classes("text-lg font-bold")
            thr = ui.number("Предупреждать, когда остаток ниже", value=row.low_stock_threshold,
                            min=0, format="%.0f").props("readonly outlined").classes("w-full")
            numpad(thr)
            ui.label("0 — не предупреждать по этому товару").classes("text-xs") \
                .style("color: var(--text-secondary)")
            cost = ui.number("Закупочная цена за штуку, тг", value=row.cost_tiyn / 100,
                             min=0, format="%.0f").props("readonly outlined").classes("w-full")
            numpad(cost)
            margin = ui.label("").classes("text-sm")

            def show_margin() -> None:
                buy = round((cost.value or 0) * 100)
                if not buy:
                    margin.set_text("Без закупочной цены маржа в отчётах считается "
                                    "равной всей выручке")
                    margin.style("color: var(--status-warning)")
                    return
                profit = row.price_tiyn - buy
                margin.set_text(f"Продаём за {money_tg(row.price_tiyn)} — "
                                f"прибыль {money_tg(profit)} со штуки")
                margin.style("color: var(--status-success)" if profit > 0
                             else "color: var(--status-danger)")

            cost.on_value_change(lambda _: show_margin())
            show_margin()

            def save() -> None:
                try:
                    with SessionLocal() as s:
                        inv.update_product_stock_settings(
                            s, row.product_id,
                            low_stock_threshold=int(thr.value or 0),
                            cost_tiyn=round((cost.value or 0) * 100),
                        )
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                ui.notify("Сохранено", color="green")
                refresh()

            with ui.row().classes("gap-2"):
                ui.button("Сохранить", on_click=save).props("no-caps")
                ui.button("Отмена", on_click=dlg.close).props("flat no-caps")
        dlg.open()

    def _history_dialog(row: inv.StockRow) -> None:
        """Журнал движений по товару: приходы, продажи, ручные правки."""
        with SessionLocal() as s:
            moves = inv.recent_moves(s, product_id=row.product_id, limit=50)

        def clear() -> None:
            def do_clear() -> None:
                with SessionLocal() as s:
                    n = inv.clear_moves(s, row.product_id)
                ui.notify(f"Удалено записей: {n}", color="green")
                dlg.close()

            confirm_with_pin(
                title=f"Очистить журнал «{row.name}»",
                question="Остаток останется прежним, пропадёт только история движений.",
                action_label="Очистить журнал", on_confirm=do_clear,
            )

        with ui.dialog() as dlg, ui.card().classes("gap-3 w-full max-w-lg"):
            with ui.row().classes("w-full items-baseline justify-between gap-2"):
                ui.label(f"Движения: {row.name}").classes("text-lg font-bold")
                if moves:
                    ui.button("Очистить", on_click=clear) \
                        .props("flat dense no-caps color=negative")
            if not moves:
                ui.label("Движений по этому товару ещё не было").classes("text-sm") \
                    .style("color: var(--text-secondary)")
            with ui.column().classes("w-full gap-1").style("max-height:420px;overflow:auto"):
                for m in moves:
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        ui.label(f"{to_almaty(m.created_at):%d.%m %H:%M}").classes("text-xs") \
                            .style("color: var(--text-secondary); width:84px")
                        ui.label(m.kind_label).classes("text-sm").style("width:110px")
                        ui.label(f"{m.qty_delta:+d} шт").classes("text-sm font-bold") \
                            .style("color: var(--status-success)" if m.qty_delta > 0
                                   else "color: var(--status-danger)")
                        ui.label(m.note or "").classes("flex-1 min-w-0 text-xs truncate") \
                            .style("color: var(--text-secondary)")
            ui.button("Закрыть", on_click=dlg.close).props("flat no-caps")
        dlg.open()

    # ------------------------------------------------------------------
    # отрисовка
    # ------------------------------------------------------------------

    def _row_card(row: inv.StockRow) -> None:
        opacity = "1" if row.is_active else ".55"
        with ui.row().classes("w-full items-center gap-3 no-wrap p-3") \
                .style(f"{_CARD}; opacity:{opacity}"):
            with ui.column().classes("gap-0 flex-1 min-w-0"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label(row.name).classes("text-base font-bold leading-tight")
                    if not row.is_active:
                        ui.badge("убран из меню").props("rounded") \
                            .style("background: var(--surface-sunken); "
                                   "color: var(--text-secondary)")
                threshold = (f"порог {row.low_stock_threshold} шт"
                             if row.low_stock_threshold else "без порога")
                cost = (f"закупка {money_tg(row.cost_tiyn)}" if row.cost_tiyn
                        else "закупочная цена не задана")
                ui.label(f"{threshold} · {cost}").classes("text-xs") \
                    .style("color: var(--text-secondary)")
            with ui.column().classes("gap-0 items-end").style("width:104px"):
                if not row.tracked:
                    ui.label("—").classes("text-lg font-black") \
                        .style("color: var(--text-muted)")
                    ui.label("не считается").classes("text-xs") \
                        .style("color: var(--text-muted)")
                else:
                    ui.label(f"{row.stock_qty} шт").classes("text-lg font-black") \
                        .style("color: var(--status-danger)" if row.is_low else "")
                    if row.is_low:
                        ui.label("на исходе").classes("text-xs") \
                            .style("color: var(--status-danger)")
            ui.button("Остаток", icon="tune", on_click=lambda r=row: _stock_dialog(r)) \
                .props("flat dense no-caps")
            ui.button(icon="notifications", on_click=lambda r=row: _settings_dialog(r)) \
                .props("flat dense").tooltip("Порог предупреждения и закупочная цена")
            ui.button(icon="history", on_click=lambda r=row: _history_dialog(r)) \
                .props("flat dense").tooltip("Движения по товару")

    def refresh() -> None:
        box.clear()
        with box, SessionLocal() as session:
            rows = inv.stock_rows(session, include_hidden=state["hidden"],
                                  query=state["query"],
                                  only_tracked=state["only_tracked"])
            total = inv.stock_value_tiyn(session)
            if not rows:
                if state["query"] or state["only_tracked"]:
                    empty_state(icon="search_off", title="Ничего не найдено",
                                hint="Снимите поиск или фильтр «только учитываемые».")
                else:
                    empty_state(
                        icon="inventory_2", title="В меню ещё нет товаров",
                        hint="Склад считается по товарам меню — заведите их, "
                             "и здесь появятся остатки.",
                        action_label="Перейти в «Меню и цены»", action_icon="arrow_forward",
                        on_action=lambda: ui.navigate.to("/admin/menu"))
                return

            tracked = [r for r in rows if r.tracked]
            low = [r for r in tracked if r.is_low]
            with ui.row().classes("w-full items-center gap-4 flex-wrap p-3") \
                    .style(_CARD):
                _summary("Считаем товаров", str(len(tracked)))
                _summary("На исходе", str(len(low)),
                         danger=bool(low))
                _summary("Склад на сумму", money_tg(total))

            groups: dict[str, list] = {}
            for row in rows:
                groups.setdefault(row.category, []).append(row)
            for name, items in groups.items():
                with ui.row().classes("w-full items-baseline gap-2 mt-2"):
                    ui.label(name).classes("text-xs uppercase tracking-wider") \
                        .style("color: var(--text-secondary)")
                    ui.label(f"{len(items)}").classes("text-xs") \
                        .style("color: var(--text-muted)")
                for row in items:
                    _row_card(row)

    def _summary(label: str, value: str, *, danger: bool = False) -> None:
        with ui.column().classes("gap-0"):
            ui.label(label).classes("text-xs").style("color: var(--text-secondary)")
            ui.label(value).classes("text-lg font-black") \
                .style("color: var(--status-danger)" if danger else "")

    # ------------------------------------------------------------------
    # разметка
    # ------------------------------------------------------------------

    with root:
        with ui.row().classes("w-full items-end justify-between gap-4 flex-wrap"):
            with ui.column().classes("gap-0"):
                ui.label("Склад").classes("text-2xl font-black leading-tight")
                ui.label("Сколько штук товара лежит на точке. Продажи списывают "
                         "остаток сами.").classes("text-sm") \
                    .style("color: var(--text-secondary)")
            with ui.row().classes("gap-2 flex-wrap"):
                ui.button("Приход товара", icon="local_shipping",
                          on_click=lambda: ui.navigate.to("/stock/purchase")) \
                    .props("outline no-caps").classes("h-12")
                ui.button("Меню и цены", icon="restaurant_menu",
                          on_click=lambda: ui.navigate.to("/admin/menu")) \
                    .props("outline no-caps").classes("h-12")

        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            with ui.row().classes("items-center gap-2 px-3 rounded-xl flex-1") \
                    .style(f"{_CARD}; min-height:48px; min-width:240px"):
                ui.icon("search", size="20px").style("color: var(--text-secondary)")
                search = ui.input(placeholder="Поиск по названию товара") \
                    .props("borderless dense clearable").classes("flex-1")
            tracked_switch = ui.switch("Только учитываемые")
            hidden_switch = ui.switch("Показывать убранные из меню")

        def _on_search(_) -> None:
            state["query"] = (search.value or "").strip()
            refresh()

        def _on_tracked(_) -> None:
            state["only_tracked"] = bool(tracked_switch.value)
            refresh()

        def _on_hidden(_) -> None:
            state["hidden"] = bool(hidden_switch.value)
            refresh()

        search.on_value_change(_on_search)
        tracked_switch.on_value_change(_on_tracked)
        hidden_switch.on_value_change(_on_hidden)

        box = ui.column().classes("w-full gap-2")

    refresh()
