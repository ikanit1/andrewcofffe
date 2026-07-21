from nicegui import ui

from app.db import SessionLocal
from app.services import shift_service as ss
from app.services import modifier_service as ms
from app.services import sales_service as sales
from app.services.catalog_service import list_menu
from app.services.pricing import PaymentInput
from app.services import pricing
from app.models import Modifier, Order, OrderItem
from app.ui.guard import current_user_id, require_user


@ui.page("/cashier")
def cashier_page() -> None:
    if not require_user():
        return
    uid = current_user_id()

    with SessionLocal() as session:
        shift = ss.current_open_shift(session)

    ui.label("Касса").classes("text-2xl font-bold")

    if shift is None:
        ui.label("Смена не открыта").classes("text-lg")
        cash = ui.number("Стартовая наличность, тг", value=0, min=0, format="%.0f")

        def do_open() -> None:
            try:
                with SessionLocal() as s:
                    ss.open_shift(s, cashier_id=uid, opening_cash_tiyn=round((cash.value or 0) * 100))
            except ValueError as e:
                ui.notify(str(e), color="red")
                return
            ui.navigate.to("/cashier")

        ui.button("Открыть смену", on_click=do_open)
        return

    ui.label(f"Смена открыта (№{shift.id})").classes("text-lg text-green-700")
    ui.button("Экран продажи", on_click=lambda: ui.navigate.to("/cashier/sale"))
    ui.button("Возвраты", on_click=lambda: ui.navigate.to("/cashier/refunds"))
    ui.button("Приход товара", on_click=lambda: ui.navigate.to("/stock/purchase"))

    with ui.expansion("Инкассация").classes("w-full max-w-md"):
        amt = ui.number("Сумма изъятия, тг", value=0, min=0, format="%.0f")
        note = ui.input("Примечание")

        def do_collect() -> None:
            try:
                with SessionLocal() as s:
                    ss.add_collection(s, shift_id=shift.id,
                                      amount_tiyn=round((amt.value or 0) * 100), note=note.value or None)
            except ValueError as e:
                ui.notify(str(e), color="red")
                return
            ui.notify("Инкассация записана")
            ui.navigate.to("/cashier")

        ui.button("Изъять", on_click=do_collect)

    with ui.expansion("Закрыть смену").classes("w-full max-w-md"):
        with SessionLocal() as s:
            expected = ss.expected_cash_tiyn(s, shift.id)
        ui.label(f"Ожидается в кассе: {expected / 100:.2f} тг")
        counted = ui.number("Фактически в кассе, тг", value=expected / 100, min=0, format="%.0f")

        def do_close() -> None:
            try:
                with SessionLocal() as s:
                    closed = ss.close_shift(s, shift_id=shift.id,
                                            counted_cash_tiyn=round((counted.value or 0) * 100))
            except ValueError as e:
                ui.notify(str(e), color="red")
                return
            diff = (closed.counted_cash_tiyn - closed.expected_cash_tiyn) / 100
            ui.notify(f"Смена закрыта. Расхождение: {diff:+.2f} тг")
            ui.navigate.to("/cashier")

        ui.button("Закрыть смену", on_click=do_close, color="red")


@ui.page("/cashier/sale")
def sale_page() -> None:
    if not require_user():
        return
    uid = current_user_id()

    with SessionLocal() as session:
        if ss.current_open_shift(session) is None:
            ui.label("Смена не открыта").classes("text-red-600 text-xl")
            ui.button("К смене", on_click=lambda: ui.navigate.to("/cashier"))
            return
        menu = list_menu(session)

    cart: list[dict] = []

    ui.label("Экран продажи").classes("text-2xl font-bold")
    with ui.row().classes("w-full gap-4"):
        products_col = ui.column().classes("flex-1")
        cart_col = ui.column().classes("w-96")

    def add_to_cart(product) -> None:
        with SessionLocal() as session:
            groups = ms.groups_for_product(session, product.id)
        if not groups:
            cart.append({"product_id": product.id, "name": product.name,
                         "base_price_tiyn": product.price_tiyn, "qty": 1,
                         "modifier_ids": [], "mod_labels": []})
            render_cart()
            return
        _open_modifier_dialog(product, groups)

    def _open_modifier_dialog(product, groups) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(product.name).classes("text-xl")
            selectors = []
            for g, mods in groups:
                opts = {m.id: f"{m.name} (+{m.price_delta_tiyn/100:.2f})" for m in mods}
                sel = ui.select(opts, label=g.name)
                selectors.append((g, sel, {m.id: m for m in mods}))

            def confirm() -> None:
                chosen_ids, labels = [], []
                for g, sel, by_id in selectors:
                    if sel.value:
                        chosen_ids.append(sel.value)
                        labels.append(by_id[sel.value].name)
                    elif g.is_required:
                        ui.notify(f"Выберите: {g.name}", color="red")
                        return
                cart.append({"product_id": product.id, "name": product.name,
                             "base_price_tiyn": product.price_tiyn, "qty": 1,
                             "modifier_ids": chosen_ids, "mod_labels": labels})
                dialog.close()
                render_cart()

            ui.button("Добавить", on_click=confirm)
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    with products_col:
        for cat, products in menu:
            ui.label(cat.name).classes("text-xl mt-2")
            with ui.row().classes("flex-wrap gap-2"):
                for p in products:
                    ui.button(f"{p.name}\n{p.price_tiyn/100:.2f} тг",
                              on_click=lambda p=p: add_to_cart(p)).classes("w-40 h-20")

    def cart_total_tiyn() -> int:
        all_mod_ids = {mid for c in cart for mid in c["modifier_ids"]}
        mods_by_id = {}
        if all_mod_ids:
            with SessionLocal() as s:
                mods_by_id = {m.id: m for m in s.query(Modifier).filter(Modifier.id.in_(all_mod_ids)).all()}
        total = 0
        for c in cart:
            line = pricing.CartLine(
                base_price_tiyn=c["base_price_tiyn"],
                qty=c["qty"],
                unit_cost_tiyn=0,
                modifier_price_deltas=[mods_by_id[mid].price_delta_tiyn for mid in c["modifier_ids"] if mid in mods_by_id],
            )
            total += pricing.line_total_tiyn(line)
        return total

    def render_cart() -> None:
        cart_col.clear()
        with cart_col:
            ui.label("Чек").classes("text-xl")
            if not cart:
                ui.label("Пусто").classes("text-gray-500")
            for idx, c in enumerate(cart):
                label = c["name"] + (f" [{', '.join(c['mod_labels'])}]" if c["mod_labels"] else "")
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{label} ×{c['qty']}").classes("flex-1")

                    def inc(i=idx) -> None:
                        cart[i]["qty"] += 1
                        render_cart()

                    def dec(i=idx) -> None:
                        cart[i]["qty"] -= 1
                        if cart[i]["qty"] <= 0:
                            cart.pop(i)
                        render_cart()

                    ui.button("−", on_click=dec)
                    ui.button("+", on_click=inc)
            ui.separator()
            ui.label(f"Итого: {cart_total_tiyn()/100:.2f} тг").classes("text-lg font-bold")
            if cart:
                ui.button("Оплата", on_click=open_payment).classes("w-full")

    def open_payment() -> None:
        total = cart_total_tiyn()
        with ui.dialog() as dialog, ui.card():
            ui.label(f"К оплате: {total/100:.2f} тг").classes("text-xl")
            method = ui.select({"cash": "Наличные", "card": "Карта", "kaspi_qr": "Kaspi QR"},
                               label="Способ", value="cash")
            tendered = ui.number("Получено (наличные), тг", value=total / 100, format="%.0f")

            def confirm_payment() -> None:
                pay_method = method.value
                if pay_method == "cash":
                    tnd = round((tendered.value or 0) * 100)
                    if tnd < total:
                        ui.notify("Получено меньше суммы чека", color="red")
                        return
                    payments = [PaymentInput("cash", total, tnd)]
                else:
                    payments = [PaymentInput(pay_method, total, None)]
                try:
                    with SessionLocal() as s:
                        lines = [sales.SaleLineInput(product_id=c["product_id"], qty=c["qty"],
                                                     modifier_ids=c["modifier_ids"]) for c in cart]
                        order = sales.create_sale(s, cashier_id=uid, lines=lines, payments=payments)
                        num = order.number
                        change = payments[0].tendered_tiyn - total if pay_method == "cash" else 0
                except (ValueError, PermissionError) as e:
                    ui.notify(str(e), color="red")
                    return
                except Exception:
                    ui.notify("Не удалось провести чек. Ничего не списано, попробуйте ещё раз.", color="red")
                    return
                dialog.close()
                cart.clear()
                render_cart()
                msg = f"Заказ №{num} проведён."
                if change:
                    msg += f" Сдача: {change/100:.2f} тг"
                ui.notify(msg, color="green")

            ui.button("Провести", on_click=confirm_payment)
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    ui.button("← К смене", on_click=lambda: ui.navigate.to("/cashier"))
    render_cart()


@ui.page("/cashier/refunds")
def refunds_page() -> None:
    if not require_user():
        return
    uid = current_user_id()

    ui.label("Возвраты").classes("text-2xl font-bold")
    box = ui.column().classes("w-full max-w-2xl gap-2")

    def refresh() -> None:
        box.clear()
        with box, SessionLocal() as session:
            shift = ss.current_open_shift(session)
            if shift is None:
                ui.label("Смена не открыта").classes("text-red-600")
                return
            orders = session.query(Order).filter(
                Order.shift_id == shift.id,
                Order.status.in_(["paid", "partially_refunded"]),
            ).order_by(Order.number.desc()).all()
            if not orders:
                ui.label("Нет заказов для возврата").classes("text-gray-500")
            for o in orders:
                items = session.query(OrderItem).filter_by(order_id=o.id).all()
                names = ", ".join(f"{it.name}×{it.qty - it.refunded_qty}"
                                  for it in items if it.qty - it.refunded_qty > 0)
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"№{o.number}: {names} — {o.total_tiyn/100:.2f} тг").classes("flex-1")
                    ui.button("Вернуть полностью",
                              on_click=lambda oid=o.id: _do_full_refund(oid))
                    ui.button("Частичный возврат",
                              on_click=lambda oid=o.id: _do_partial_refund(oid))

    def _do_full_refund(order_id: int) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label("Причина возврата").classes("text-lg")
            reason = ui.input("Причина")

            def confirm() -> None:
                if not reason.value or not reason.value.strip():
                    ui.notify("Укажите причину", color="red")
                    return
                try:
                    with SessionLocal() as s:
                        sales.refund_sale(s, order_id=order_id, cashier_id=uid,
                                          reason=reason.value, item_qty=None)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dialog.close()
                ui.notify("Возврат оформлен", color="green")
                refresh()

            ui.button("Подтвердить возврат", on_click=confirm, color="red")
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    def _do_partial_refund(order_id: int) -> None:
        with SessionLocal() as session:
            items = session.query(OrderItem).filter_by(order_id=order_id).all()
        remaining = [(it, it.qty - it.refunded_qty) for it in items if it.qty - it.refunded_qty > 0]

        with ui.dialog() as dialog, ui.card():
            ui.label("Частичный возврат").classes("text-lg")
            if not remaining:
                ui.label("Нечего возвращать").classes("text-gray-500")
                ui.button("Закрыть", on_click=dialog.close)
                dialog.open()
                return

            qty_inputs: dict[int, object] = {}
            for it, rem in remaining:
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"{it.name} (куплено {it.qty}, доступно к возврату {rem})").classes("flex-1")
                    q = ui.number("Вернуть", value=0, min=0, max=rem, format="%.0f")
                    qty_inputs[it.id] = q

            reason = ui.input("Причина")

            def confirm() -> None:
                if not reason.value or not reason.value.strip():
                    ui.notify("Укажите причину", color="red")
                    return
                item_qty = {
                    item_id: round(q.value)
                    for item_id, q in qty_inputs.items()
                    if q.value and q.value > 0
                }
                if not item_qty:
                    ui.notify("Выберите хотя бы одну позицию", color="red")
                    return
                try:
                    with SessionLocal() as s:
                        sales.refund_sale(s, order_id=order_id, cashier_id=uid,
                                          reason=reason.value, item_qty=item_qty)
                except ValueError as e:
                    dialog.close()
                    ui.notify(f"{e}. Данные обновлены, откройте возврат заново.", color="red")
                    refresh()
                    return
                dialog.close()
                ui.notify("Возврат оформлен", color="green")
                refresh()

            ui.button("Оформить возврат", on_click=confirm, color="red")
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    refresh()
