import asyncio

from nicegui import ui

from app.db import SessionLocal
from app.services import shift_service as ss
from app.services import modifier_service as ms
from app.services import sales_service as sales
from app.services.catalog_service import list_menu
from app.services.pricing import PaymentInput
from app.services import pricing
from app.models import Modifier, Order, OrderItem, Payment
from app.ui.guard import current_user_id, require_user
from app.ui.layout import cashier_header, sale_success
from app.kaspi import service as kaspi_service
from app.kaspi.client import KaspiError


@ui.page("/cashier")
def cashier_page() -> None:
    if not require_user():
        return
    uid = current_user_id()
    cashier_header()

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
    cashier_header()

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
        if not menu:
            ui.label("Меню пустое").classes("text-gray-500")
        else:
            with ui.tabs().classes("w-full") as cat_tabs:
                for cat, _ in menu:
                    ui.tab(name=str(cat.id), label=cat.name)
            with ui.tab_panels(cat_tabs, value=str(menu[0][0].id)).classes("w-full"):
                for cat, products in menu:
                    with ui.tab_panel(str(cat.id)):
                        with ui.grid(columns=3).classes("w-full gap-3"):
                            for p in products:
                                card = ui.card().classes(
                                    "w-full h-28 items-center justify-center cursor-pointer "
                                    "p-2 hover:bg-blue-50 transition"
                                )
                                card.on("click", lambda p=p: add_to_cart(p))
                                with card:
                                    ui.label(p.name).classes("text-lg font-bold text-center leading-tight")
                                    ui.label(f"{p.price_tiyn/100:.0f} тг").classes("text-base text-gray-600")

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

    def clear_cart() -> None:
        cart.clear()
        render_cart()

    def render_cart() -> None:
        cart_col.clear()
        with cart_col:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Чек").classes("text-2xl font-bold")
                if cart:
                    ui.button("Очистить чек", icon="delete",
                              on_click=clear_cart).props("flat color=red")
            if not cart:
                ui.label("Пусто").classes("text-gray-500 text-lg")
            for idx, c in enumerate(cart):
                label = c["name"] + (f" [{', '.join(c['mod_labels'])}]" if c["mod_labels"] else "")
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.label(label).classes("flex-1 text-lg")

                    def dec(i=idx) -> None:
                        cart[i]["qty"] -= 1
                        if cart[i]["qty"] <= 0:
                            cart.pop(i)
                        render_cart()

                    def inc(i=idx) -> None:
                        cart[i]["qty"] += 1
                        render_cart()

                    ui.button("−", on_click=dec).props("round").classes("text-xl")
                    ui.label(f"{c['qty']}").classes("text-xl font-bold w-8 text-center")
                    ui.button("+", on_click=inc).props("round").classes("text-xl")
            ui.separator()
            ui.label(f"Итого: {cart_total_tiyn()/100:.0f} тг").classes("text-2xl font-bold")
            if cart:
                ui.button("Оплата", on_click=open_payment).classes("w-full h-16 text-xl")

    def open_payment() -> None:
        total = cart_total_tiyn()
        with ui.dialog() as dialog, ui.card():
            ui.label(f"К оплате: {total/100:.2f} тг").classes("text-xl")
            split = ui.checkbox("Разделить оплату")

            single_col = ui.column()
            with single_col:
                method = ui.select({"cash": "Наличные", "card": "Карта",
                                    "kaspi_qr": "Kaspi QR (вручную)",
                                    "kaspi_terminal": "Kaspi (терминал)"},
                                   label="Способ", value="cash")
                tendered = ui.number("Получено (наличные), тг", value=total / 100, format="%.0f")

            split_col = ui.column()
            with split_col:
                method_a = ui.select({"cash": "Наличные", "card": "Карта", "kaspi_qr": "Kaspi QR"},
                                     label="Способ 1", value="cash")
                amount_a = ui.number("Сумма способа 1, тг", value=0, min=0, format="%.0f")
                tendered_a = ui.number("Получено (наличные) способ 1, тг", value=0, format="%.0f")
                method_b = ui.select({"cash": "Наличные", "card": "Карта", "kaspi_qr": "Kaspi QR"},
                                     label="Способ 2", value="card")
                amount_b_label = ui.label("")
                tendered_b = ui.number("Получено (наличные) способ 2, тг", value=0, format="%.0f")

            def refresh_split() -> None:
                remainder = max(total - round((amount_a.value or 0) * 100), 0)
                amount_b_label.set_text(f"Сумма способа 2: {remainder / 100:.2f} тг")
                tendered_a.set_visibility(method_a.value == "cash")
                tendered_b.set_visibility(method_b.value == "cash")
                if method_a.value == "cash" and not tendered_a.value:
                    tendered_a.value = amount_a.value or 0
                if method_b.value == "cash" and not tendered_b.value:
                    tendered_b.value = remainder / 100

            def toggle_mode() -> None:
                single_col.set_visibility(not split.value)
                split_col.set_visibility(split.value)
                if split.value:
                    refresh_split()

            split.on_value_change(lambda e: toggle_mode())
            amount_a.on_value_change(lambda e: refresh_split())
            method_a.on_value_change(lambda e: refresh_split())
            method_b.on_value_change(lambda e: refresh_split())
            toggle_mode()

            def _cash_payment(method_name: str, amount_tiyn: int, tendered_field, label: str) -> PaymentInput | None:
                if method_name != "cash":
                    return PaymentInput(method_name, amount_tiyn, None)
                tnd = round((tendered_field.value or 0) * 100)
                if tnd < amount_tiyn:
                    ui.notify(f"Получено меньше суммы по {label} (наличные)", color="red")
                    return None
                return PaymentInput("cash", amount_tiyn, tnd)

            async def confirm_payment() -> None:
                # Терминальная Kaspi-оплата: только как единственный способ (не в split)
                if not split.value and method.value == "kaspi_terminal":
                    if total % 100 != 0:
                        ui.notify("Kaspi принимает только целые тенге", color="red")
                        return
                    submit_btn.disable()  # защита от повторного нажатия во время оплаты
                    pay_task: asyncio.Task | None = None
                    with ui.dialog().props("persistent") as wait_dialog, \
                            ui.card().classes("items-center p-8 gap-4"):
                        ui.spinner(size="4rem")
                        ui.label("Ожидание оплаты на терминале…").classes("text-xl font-bold")
                        ui.label(f"К оплате: {total/100:.0f} тг").classes("text-2xl")
                        ui.label("Клиент сканирует QR или прикладывает карту").classes("text-gray-600")
                        ui.button("Отменить", color="red",
                                  on_click=lambda: pay_task.cancel() if pay_task else None)
                    wait_dialog.open()
                    try:
                        async def _run_pay():
                            with SessionLocal() as s:
                                return await kaspi_service.pay(s, total)

                        pay_task = asyncio.create_task(_run_pay())
                        try:
                            result = await pay_task
                        except asyncio.CancelledError:
                            wait_dialog.close()
                            ui.notify("Оплата отменена. Если клиент уже оплатил — проверьте статус на терминале.",
                                      color="orange")
                            return
                        except (ValueError, KaspiError) as e:
                            wait_dialog.close()
                            ui.notify(str(e), color="red")
                            return
                        except Exception:
                            wait_dialog.close()
                            ui.notify("Ошибка связи с терминалом. Чек не проведён.", color="red")
                            return
                        wait_dialog.close()
                        if result.status != "success":
                            ui.notify(result.message or "Оплата не подтверждена терминалом. Чек не проведён.",
                                      color="red")
                            return
                        try:
                            with SessionLocal() as s:
                                lines = [sales.SaleLineInput(product_id=c["product_id"], qty=c["qty"],
                                                             modifier_ids=c["modifier_ids"]) for c in cart]
                                order = sales.create_sale(
                                    s, cashier_id=uid, lines=lines,
                                    payments=[PaymentInput("kaspi_terminal", total, None,
                                                           provider="terminal",
                                                           terminal_method=result.terminal_method,
                                                           transaction_id=result.transaction_id)],
                                )
                                num = order.number
                        except Exception as e:
                            # деньги уже ушли: закрываем диалог и чистим корзину, чтобы кассир не пробил повторно
                            dialog.close()
                            cart.clear()
                            render_cart()
                            ui.notify(f"Оплата прошла, но чек не сохранён ({e}). Запишите заказ вручную.",
                                      color="red")
                            return
                        dialog.close()
                        cart.clear()
                        render_cart()
                        sale_success(num, f"Kaspi ({result.terminal_method})")
                        return
                    finally:
                        submit_btn.enable()
                # --- дальше прежняя (синхронная) логика для остальных способов ---
                if split.value:
                    amt_a = round((amount_a.value or 0) * 100)
                    if amt_a <= 0 or amt_a >= total:
                        ui.notify("Сумма способа 1 должна быть больше 0 и меньше итога", color="red")
                        return
                    amt_b = total - amt_a
                    pay_a = _cash_payment(method_a.value, amt_a, tendered_a, "способу 1")
                    if pay_a is None:
                        return
                    pay_b = _cash_payment(method_b.value, amt_b, tendered_b, "способу 2")
                    if pay_b is None:
                        return
                    payments = [pay_a, pay_b]
                    change = sum(
                        (p.tendered_tiyn - p.amount_tiyn) for p in payments
                        if p.method == "cash" and p.tendered_tiyn is not None
                    )
                else:
                    pay_method = method.value
                    if pay_method == "cash":
                        tnd = round((tendered.value or 0) * 100)
                        if tnd < total:
                            ui.notify("Получено меньше суммы чека", color="red")
                            return
                        payments = [PaymentInput("cash", total, tnd)]
                        change = tnd - total
                    else:
                        payments = [PaymentInput(pay_method, total, None)]
                        change = 0
                try:
                    with SessionLocal() as s:
                        lines = [sales.SaleLineInput(product_id=c["product_id"], qty=c["qty"],
                                                     modifier_ids=c["modifier_ids"]) for c in cart]
                        order = sales.create_sale(s, cashier_id=uid, lines=lines, payments=payments)
                        num = order.number
                except (ValueError, PermissionError) as e:
                    ui.notify(str(e), color="red")
                    return
                except Exception:
                    ui.notify("Не удалось провести чек. Ничего не списано, попробуйте ещё раз.", color="red")
                    return
                dialog.close()
                cart.clear()
                render_cart()
                extra = f"Сдача: {change/100:.0f} тг" if change else ""
                sale_success(num, extra)

            submit_btn = ui.button("Провести", on_click=confirm_payment)
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    ui.button("← К смене", on_click=lambda: ui.navigate.to("/cashier"))
    render_cart()


@ui.page("/cashier/refunds")
def refunds_page() -> None:
    if not require_user():
        return
    uid = current_user_id()
    cashier_header()

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
                terminal_paid = session.query(Payment).filter_by(
                    order_id=o.id, provider="terminal").first() is not None
                with ui.column().classes("gap-0"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label(f"№{o.number}: {names} — {o.total_tiyn/100:.2f} тг").classes("flex-1")
                        ui.button("Вернуть полностью",
                                  on_click=lambda oid=o.id: _do_full_refund(oid))
                        ui.button("Частичный возврат",
                                  on_click=lambda oid=o.id: _do_partial_refund(oid))
                    if terminal_paid:
                        ui.label("⚠ Оплачено через терминал Kaspi — деньги верните покупателю вручную на терминале").classes("text-orange-700 text-sm")

    def _do_full_refund(order_id: int) -> None:
        with SessionLocal() as session:
            terminal_paid = session.query(Payment).filter_by(
                order_id=order_id, provider="terminal").first() is not None
        with ui.dialog() as dialog, ui.card():
            if terminal_paid:
                ui.label("⚠ Оплата была через терминал Kaspi. Возврат денег сделайте вручную на терминале — система деньги не вернёт.").classes("text-orange-700")
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
            terminal_paid = session.query(Payment).filter_by(
                order_id=order_id, provider="terminal").first() is not None
        remaining = [(it, it.qty - it.refunded_qty) for it in items if it.qty - it.refunded_qty > 0]

        with ui.dialog() as dialog, ui.card():
            if terminal_paid:
                ui.label("⚠ Оплата была через терминал Kaspi. Возврат денег сделайте вручную на терминале — система деньги не вернёт.").classes("text-orange-700")
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
