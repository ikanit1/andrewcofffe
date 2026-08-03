from nicegui import ui

from app.db import SessionLocal
from app.services import inventory_service as inv
from app.timezone import to_almaty
from app.ui.design import empty_state, money_tg, numpad
from app.ui.guard import is_admin, require_user
from app.ui.layout import cashier_header

_CARD = ("background: var(--surface-card); border:1px solid var(--border-subtle);"
         "border-radius:16px")


@ui.page("/stock/purchase")
def purchase_page() -> None:
    if not require_user():
        return
    cashier_header()

    with SessionLocal() as session:
        options = {
            r.product_id: (f"{r.name} · {r.stock_qty} шт" if r.tracked else r.name)
            for r in inv.stock_rows(session)
        }

    with ui.column().classes("w-full gap-4 mx-auto").style("max-width:720px"):
        ui.label("Приход товара").classes("text-2xl font-black")

        if not options:
            # Кнопка — только админу: /admin/menu закрыт require_admin, и кассир
            # упёрся бы в «Доступ только для администратора».
            hint = ("Приход оформляется на товар из меню — круассаны, снеки, "
                    "бутылки. Заведите товары, и здесь появится форма прихода.")
            if is_admin():
                empty_state(icon="inventory_2", title="В меню ещё нет товаров", hint=hint,
                            action_label="Перейти в «Меню и цены»",
                            action_icon="arrow_forward",
                            on_action=lambda: ui.navigate.to("/admin/menu"))
            else:
                empty_state(icon="inventory_2", title="В меню ещё нет товаров",
                            hint="Товары заводит администратор в разделе «Меню и цены».")
            return

        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            product = ui.select(options, label="Товар", with_input=True) \
                .props("outlined").classes("w-full")
            qty = ui.number("Сколько штук пришло", value=0, min=1, format="%.0f") \
                .props("readonly outlined").classes("w-full")
            numpad(qty)
            total = ui.number("Сумма закупки, тг", value=0, min=0, format="%.0f") \
                .props("readonly outlined").classes("w-full")
            numpad(total)
            ui.label("Сумма нужна для расчёта закупочной цены и маржи. Можно "
                     "оставить 0 — тогда прежняя цена сохранится.").classes("text-xs") \
                .style("color: var(--text-secondary)")

            def do_receive() -> None:
                if not product.value:
                    ui.notify("Выберите товар", color="red")
                    return
                if not qty.value or qty.value <= 0:
                    ui.notify("Введите количество", color="red")
                    return
                try:
                    with SessionLocal() as s:
                        inv.receive_purchase(s, product.value, qty=round(qty.value),
                                             total_cost_tiyn=round((total.value or 0) * 100))
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                ui.notify("Приход оформлен", color="green")
                qty.value = 0
                total.value = 0
                refresh_history()

            ui.button("Оформить приход", icon="local_shipping", on_click=do_receive) \
                .props("no-caps").classes("w-full h-12")

        history_box = ui.column().classes("w-full gap-2 p-4").style(_CARD)

    def refresh_history() -> None:
        history_box.clear()
        with history_box, SessionLocal() as session:
            ui.label("Последние приходы").classes("text-lg font-bold")
            moves = inv.recent_moves(session, kind="purchase", limit=10)
            if not moves:
                ui.label("Приходов ещё не было").classes("text-sm") \
                    .style("color: var(--text-secondary)")
            for m in moves:
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    ui.label(f"{to_almaty(m.created_at):%d.%m %H:%M}").classes("text-sm") \
                        .style("color: var(--text-secondary); width:88px")
                    ui.label(m.product_name).classes("flex-1 min-w-0 text-base truncate")
                    ui.label(f"+{m.qty_delta} шт").classes("text-base font-bold")
                    ui.label(money_tg(m.cost_tiyn or 0)).classes("text-sm") \
                        .style("color: var(--text-secondary); width:96px").style("text-align:right")

    refresh_history()
