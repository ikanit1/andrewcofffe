import asyncio

from nicegui import ui

from app.db import SessionLocal
from app.services import shift_service as ss
from app.services import modifier_service as ms
from app.services import sales_service as sales
from app.services import reporting_service
from app.services import dashboard_service
from app.timezone import to_almaty
from app.services.catalog_service import list_menu
from app.services.pricing import PaymentInput
from app.services import pricing
from app.services import user_service
from app.services import promo
from app.services.login_throttle import LockedOut
from app.models import Modifier, Order, OrderItem, Payment, User
from app.ui.design import (BANKNOTES, PAYMENT_ICONS, category_icon, empty_state,
                           numpad, product_media, reason_picker,
                           section_title, stat_tile)
from app.ui.guard import current_user_id, is_admin, require_user
from app.ui.layout import cashier_header, sale_success
from app.kaspi import service as kaspi_service
from app.kaspi.client import KaspiError

_METHOD_LABELS = {"cash": "Наличные", "card": "Карта",
                  "kaspi_qr": "Kaspi QR", "kaspi_terminal": "Kaspi (терминал)"}

# Способы оплаты на всю сумму. Карты нет: она принимается терминалом Kaspi,
# отдельная ручная отметка «Карта» только путала бы отчётность.
SINGLE_METHODS = ("cash", "kaspi_qr", "kaspi_terminal")


@ui.page("/cashier")
def cashier_page() -> None:
    if not require_user():
        return
    uid = current_user_id()
    cashier_header()
    if is_admin():
        ui.button("← Админ-панель", icon="grid_view",
                  on_click=lambda: ui.navigate.to("/admin")).props("flat color=primary")

    with SessionLocal() as session:
        shift = ss.current_open_shift(session)

    ui.label("Касса").classes("text-2xl font-bold")

    if shift is None:
        with ui.card().classes("w-full max-w-xl p-6 gap-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("lock", size="22px").style("color: var(--status-danger)")
                ui.label("Смена закрыта").classes("text-lg font-bold") \
                    .style("color: var(--status-danger)")
            ui.label("Пересчитайте наличность в кассе и откройте смену — "
                     "после этого станет доступна продажа.") \
                .classes("text-sm").style("color: var(--text-secondary)")
            cash = ui.number("Стартовая наличность, тг", value=0, min=0,
                             format="%.0f").props("readonly").classes("w-full")
            numpad(cash, quick=BANKNOTES)

            def do_open() -> None:
                try:
                    with SessionLocal() as s:
                        ss.open_shift(s, cashier_id=uid,
                                      opening_cash_tiyn=round((cash.value or 0) * 100))
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                ui.navigate.to("/cashier")

            ui.button("Открыть смену", icon="lock_open", on_click=do_open) \
                .classes("w-full h-16 text-xl")
        return

    with SessionLocal() as s:
        today = dashboard_service.today_summary(s)
        expected_now = ss.expected_cash_tiyn(s, shift.id)

    with ui.card().classes("w-full max-w-3xl p-5 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("check_circle", size="22px").style("color: var(--status-success)")
            ui.label(f"Смена №{shift.id} открыта с {to_almaty(shift.opened_at):%H:%M}") \
                .classes("text-lg font-bold").style("color: var(--status-success)")
        with ui.row().classes("w-full gap-3 no-wrap"):
            stat_tile("Выручка сегодня", f"{today.revenue_tiyn / 100:.0f} тг")
            stat_tile("Чеков", str(today.orders_count))
            stat_tile("Ожидается в кассе", f"{expected_now / 100:.0f} тг")

    with ui.row().classes("w-full max-w-3xl gap-4 no-wrap"):
        ui.button("Продажа", icon="point_of_sale",
                  on_click=lambda: ui.navigate.to("/cashier/sale")) \
            .classes("flex-1 h-24 text-xl")
        ui.button("Возвраты", icon="undo",
                  on_click=lambda: ui.navigate.to("/cashier/refunds")) \
            .props("outline").classes("flex-1 h-24 text-xl")

    def show_xreport() -> None:
        with SessionLocal() as s:
            rep = reporting_service.x_report(s)
        with ui.dialog() as dlg, ui.card().classes("gap-2 min-w-72"):
            ui.label("X-отчёт (текущая смена)").classes("text-xl font-bold")
            if rep is None:
                ui.label("Смена не открыта")
            else:
                ui.label(f"Смена №{rep.shift_id} · {rep.cashier_name}")
                ui.label(f"Открыта: {to_almaty(rep.opened_at):%d.%m %H:%M}")
                ui.label(f"Чеков: {rep.orders_count}")
                ui.label(f"Выручка: {rep.revenue_tiyn/100:.0f} тг").classes("font-bold")
                for m, amt in rep.by_method.items():
                    ui.label(f"  {_METHOD_LABELS.get(m, m)}: {amt/100:.0f} тг")
                if rep.refunds_tiyn:
                    ui.label(f"Возвраты: −{rep.refunds_tiyn/100:.0f} тг").classes("text-orange-700")
                ui.label(f"Ожидается в кассе: {rep.expected_cash_tiyn/100:.0f} тг").classes("font-bold")
            ui.button("Закрыть", on_click=dlg.close)
        dlg.open()

    def open_collection_dialog() -> None:
        with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
            ui.label("Инкассация").classes("text-xl font-bold")
            amt = ui.number("Сумма изъятия, тг", value=0, min=0,
                            format="%.0f").props("readonly").classes("w-full")
            numpad(amt, quick=BANKNOTES)
            note = ui.input("Примечание").classes("w-full")

            def do_collect() -> None:
                try:
                    with SessionLocal() as s:
                        ss.add_collection(s, shift_id=shift.id,
                                          amount_tiyn=round((amt.value or 0) * 100),
                                          note=note.value or None)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dlg.close()
                ui.notify("Инкассация записана")
                ui.navigate.to("/cashier")

            with ui.row().classes("gap-2"):
                ui.button("Изъять", on_click=do_collect)
                ui.button("Отмена", on_click=dlg.close).props("flat")
        dlg.open()

    with ui.column().classes("w-full max-w-3xl gap-2"):
        section_title("Во время смены")
        with ui.row().classes("gap-2 flex-wrap"):
            ui.button("X-отчёт", icon="assessment", on_click=show_xreport) \
                .props("outline").classes("h-12")
            ui.button("Приход товара", icon="local_shipping",
                      on_click=lambda: ui.navigate.to("/stock/purchase")) \
                .props("outline").classes("h-12")
            ui.button("Инкассация", icon="savings", on_click=open_collection_dialog) \
                .props("outline").classes("h-12")

    with SessionLocal() as s:
        low = dashboard_service.low_stock_ingredients(s)
    if low:
        with ui.card().classes("w-full max-w-3xl p-4 gap-2") \
                .style("background: var(--status-warning-bg); "
                       "border-color: var(--status-warning)"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("warning", size="20px").style("color: var(--status-warning)")
                ui.label(f"На исходе ({len(low)})").classes("font-bold") \
                    .style("color: var(--status-warning)")
            for ing in low:
                ui.label(
                    f"{ing.name}: {ing.stock_qty} {ing.unit} (порог {ing.low_stock_threshold})"
                ).classes("text-sm").style("color: var(--text-secondary)")

    with ui.card().classes("w-full max-w-3xl p-4 gap-3") \
            .style("background: var(--status-danger-bg); border-color: var(--status-danger-border)"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("lock", size="20px").style("color: var(--status-danger)")
            ui.label("Закрыть смену").classes("text-lg font-bold")
        expected = expected_now
        ui.label(f"Ожидается в кассе {expected / 100:.0f} тг — сверьте с фактом") \
            .classes("text-sm").style("color: var(--text-secondary)")
        counted = ui.number("Фактически в кассе, тг", value=expected / 100, min=0,
                            format="%.0f").props("readonly").classes("w-full max-w-xs")
        numpad(counted, quick=BANKNOTES, exact=int(expected / 100))

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

        ui.button("Закрыть смену", icon="lock", on_click=do_close, color="negative") \
            .classes("h-12")


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
        cashier_user = session.get(User, uid)
        cashier_limit = cashier_user.discount_limit_percent if cashier_user else 0

    cart: list[dict] = []
    order_discount = {"kind": None, "value": 0}  # kind: None|"percent"|"amount"
    discount_approved = {"ok": False}
    # Раскладка экрана продажи из макета: сетка / рельс категорий слева / телефон.
    view = {"layout": "grid", "cat_id": menu[0][0].id if menu else None}

    with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
        with ui.row().classes("items-baseline gap-3"):
            ui.label("Продажа").classes("text-2xl font-black")
            cart_count_label = ui.label("Чек пуст").classes("text-sm") \
                .style("color: var(--text-secondary)")
        layout_row = ui.row().classes("items-center gap-1 rounded-full p-1") \
            .style("background: var(--surface-card); border: 1px solid var(--border-subtle)")

    # Плашка акции: цены на витрине уже акционные, и без подписи кассир решит,
    # что цены сбились. Строится один раз при открытии экрана — акция за смену
    # закончится, но цену всё равно считает сервер при проведении чека.
    for pr in promo.active_promos():
        with ui.row().classes("w-full max-w-3xl items-center gap-2 rounded-xl p-3") \
                .style("background: var(--status-warning-bg); "
                       "border: 1px solid var(--status-warning)"):
            ui.icon("local_offer", size="20px").style("color: var(--status-warning)")
            ui.label(f"{pr.name} до {pr.end:%H:%M}").classes("font-bold") \
                .style("color: var(--status-warning)")
            ui.label(f"капучино, латте, флэт-уайт — {pr.price_tiyn / 100:.0f} тг "
                     f"за 0.3 л").classes("text-sm") \
                .style("color: var(--text-secondary)")

    sale_row = ui.row().classes("w-full gap-4 items-start no-wrap")
    with sale_row:
        products_col = ui.column().classes("flex-1 min-w-0 gap-3")
        cart_col = ui.column().classes("w-96 shrink-0")
    # Стабильный контейнер для плашки успеха: cart_col пересоздаётся в render_cart(),
    # поэтому диалог успеха нельзя создавать в его (удаляемом) контексте — держим здесь.
    success_host = ui.column()

    def qty_in_cart(product_id: int) -> int:
        return sum(c["qty"] for c in cart if c["product_id"] == product_id)

    def render_layout_switch() -> None:
        layout_row.clear()
        with layout_row:
            for lid, label in (("grid", "Сетка"), ("rail", "Рельс"), ("phone", "Телефон")):
                state = "cp-pill-active" if view["layout"] == lid else "cp-pill-flat"
                ui.button(label, on_click=lambda l=lid: set_layout(l)) \
                    .props("flat dense no-caps") \
                    .classes(f"rounded-full px-4 h-9 text-sm font-bold {state}")

    def set_layout(layout_id: str) -> None:
        view["layout"] = layout_id
        render_layout_switch()
        render_products()
        render_cart()

    def add_to_cart(product) -> None:
        with SessionLocal() as session:
            groups = ms.groups_for_product(session, product.id)
        if not groups:
            cart.append({"product_id": product.id, "name": product.name,
                         "base_price_tiyn": promo.effective_price_tiyn(product), "qty": 1,
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
                             "base_price_tiyn": promo.effective_price_tiyn(product), "qty": 1,
                             "modifier_ids": chosen_ids, "mod_labels": labels})
                dialog.close()
                render_cart()

            ui.button("Добавить", on_click=confirm)
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    def _category_pill(cat, *, vertical: bool) -> None:
        state = "cp-pill-active" if view["cat_id"] == cat.id else "cp-pill-idle"
        shape = ("flex-col items-center justify-center gap-1 w-full h-24 rounded-2xl"
                 if vertical else "items-center gap-2 h-14 px-5 rounded-full")
        btn = ui.button(on_click=lambda c=cat: set_category(c.id)) \
            .props("flat no-caps").classes(f"flex {shape} font-bold cp-hover {state}")
        with btn:
            ui.icon(category_icon(cat.name), size="26px" if vertical else "22px")
            ui.label(cat.name).classes("text-sm" if vertical else "text-base")

    def _product_card(p, *, big: bool, cat_name: str, with_media: bool) -> None:
        """Плитка товара: название, цена и счётчик в углу, если товар уже в чеке.

        with_media — показывать ли полосу с фото. Если в категории нет ни одного
        фото, полоса не рисуется вовсе: ряд серых заглушек хуже, чем компактная
        плитка с иконкой, как в макете.
        """
        qty = qty_in_cart(p.id)
        # Категорию берём из цикла: объекты меню отсоединены от сессии,
        # и обращение к p.category подняло бы ленивую загрузку на закрытой сессии.
        icon = category_icon(cat_name)
        pad = "p-0 gap-0" if with_media else "p-4 gap-1 justify-end"
        card = ui.card().classes(f"w-full cursor-pointer {pad} cp-hover relative overflow-hidden") \
            .style(f"min-height: {186 if big else 150}px")
        card.on("click", lambda p=p: add_to_cart(p))
        with card:
            if with_media:
                product_media(product_id=p.id, has_image=getattr(p, "has_image", False),
                              fallback_icon=icon, height=104 if big else 84)
            elif big:
                ui.icon(icon, size="30px").style("color: var(--brand-primary); opacity:.55")
            text_box = ui.column().classes("gap-1 w-full flex-1 justify-end") \
                .classes("p-4" if with_media else "")
            with text_box:
                ui.label(p.name).classes(
                    f"{'text-2xl' if big else 'text-xl'} font-bold leading-tight")
                ui.label(f"{promo.effective_price_tiyn(p) / 100:.0f} тг") \
                    .classes("text-lg").style("color: var(--text-secondary)")
            if qty:
                ui.label(str(qty)).classes(
                    "absolute rounded-full flex items-center justify-center "
                    "text-lg font-black"
                ).style("top:12px;right:12px;min-width:32px;height:32px;padding:0 8px;"
                        "background: var(--brand-primary); color: var(--text-on-brand);"
                        "box-shadow: var(--shadow-sm)")

    def _product_row(p, *, cat_name: str, with_media: bool) -> None:
        """Строка товара для раскладки «Телефон»: крупная зона нажатия."""
        qty = qty_in_cart(p.id)
        card = ui.card().classes("w-full cursor-pointer p-4 cp-hover")
        card.on("click", lambda p=p: add_to_cart(p))
        with card, ui.row().classes("items-center gap-3 w-full no-wrap"):
            if with_media:
                # В списке фото уместно квадратом слева: строка низкая,
                # полоса во всю ширину съела бы всю высоту экрана телефона.
                thumb = ui.element("div").classes(
                    "flex items-center justify-center shrink-0 rounded-xl overflow-hidden"
                ).style("width:56px;height:56px;background:var(--surface-sunken)")
                with thumb:
                    if getattr(p, "has_image", False):
                        ui.image(f"/product-image/{p.id}").props("fit=cover no-spinner") \
                            .classes("w-full h-full")
                    else:
                        ui.icon(category_icon(cat_name), size="24px") \
                            .style("color: var(--brand-primary); opacity:.35")
            with ui.column().classes("gap-0 flex-1 min-w-0"):
                ui.label(p.name).classes("text-xl font-bold leading-tight")
                ui.label(f"{promo.effective_price_tiyn(p) / 100:.0f} тг").classes("text-lg") \
                    .style("color: var(--text-secondary)")
            if qty:
                ui.label(str(qty)).classes(
                    "rounded-full flex items-center justify-center text-lg font-black"
                ).style("min-width:32px;height:32px;padding:0 8px;flex:none;"
                        "background: var(--brand-primary); color: var(--text-on-brand)")
            ui.icon("add", size="28px").classes("rounded-full flex items-center justify-center") \
                .style("width:52px;height:52px;flex:none;color: var(--brand-primary);"
                       "background: var(--surface-sunken)")

    def set_category(cat_id: int) -> None:
        view["cat_id"] = cat_id
        render_products()

    def render_products() -> None:
        products_col.clear()
        if not menu:
            with products_col:
                if is_admin():
                    empty_state(
                        icon="restaurant_menu",
                        title="В меню пока нет товаров",
                        hint="Добавьте категории и товары — они появятся здесь "
                             "плитками для продажи.",
                        action_label="Перейти в «Меню и цены»",
                        action_icon="arrow_forward",
                        on_action=lambda: ui.navigate.to("/admin/menu"),
                    )
                else:
                    empty_state(
                        icon="restaurant_menu",
                        title="В меню пока нет товаров",
                        hint="Меню заполняет администратор. Попросите владельца "
                             "добавить товары — тогда можно будет пробивать чеки.",
                    )
            return
        cat_sel = next((c for c, _ in menu if c.id == view["cat_id"]), menu[0][0])
        products = next((ps for c, ps in menu if c.id == cat_sel.id), menu[0][1])
        cat_name = cat_sel.name
        layout = view["layout"]
        # Полосу с фото показываем, только если в категории есть хоть одно фото:
        # иначе экран превратился бы в ряд одинаковых серых заглушек.
        with_media = any(getattr(p, "has_image", False) for p in products)
        with products_col:
            if layout == "rail":
                # Категории узкой колонкой слева, товары — крупной сеткой справа
                with ui.row().classes("w-full gap-4 items-start no-wrap"):
                    with ui.column().classes("w-32 shrink-0 gap-2"):
                        for cat, _ in menu:
                            _category_pill(cat, vertical=True)
                    with ui.grid().classes("flex-1 min-w-0 gap-4") \
                            .style("grid-template-columns: repeat(auto-fill, minmax(210px, 1fr))"):
                        for p in products:
                            _product_card(p, big=True, cat_name=cat_name, with_media=with_media)
                return

            with ui.row().classes("w-full gap-2 flex-wrap"):
                for cat, _ in menu:
                    _category_pill(cat, vertical=False)
            if layout == "phone":
                with ui.column().classes("w-full gap-2 max-w-lg"):
                    for p in products:
                        _product_row(p, cat_name=cat_name, with_media=with_media)
            else:
                with ui.grid().classes("w-full gap-3") \
                        .style("grid-template-columns: repeat(auto-fill, minmax(180px, 1fr))"):
                    for p in products:
                        _product_card(p, big=False, cat_name=cat_name, with_media=with_media)

    def cart_subtotal_tiyn() -> int:
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

    def line_sum_tiyn(c: dict) -> int:
        """Сумма одной строки чека с модификаторами — для подписи под названием."""
        deltas = []
        if c["modifier_ids"]:
            with SessionLocal() as s:
                deltas = [m.price_delta_tiyn for m in
                          s.query(Modifier).filter(Modifier.id.in_(c["modifier_ids"])).all()]
        return pricing.line_total_tiyn(pricing.CartLine(
            base_price_tiyn=c["base_price_tiyn"], qty=c["qty"],
            unit_cost_tiyn=0, modifier_price_deltas=deltas,
        ))

    def order_discount_tiyn() -> int:
        if not order_discount["kind"]:
            return 0
        try:
            return pricing.order_discount_tiyn(
                cart_subtotal_tiyn(), order_discount["kind"], order_discount["value"])
        except ValueError:
            return 0

    def cart_total_tiyn() -> int:
        return cart_subtotal_tiyn() - order_discount_tiyn()

    def clear_cart() -> None:
        cart.clear()
        order_discount["kind"] = None
        order_discount["value"] = 0
        discount_approved["ok"] = False
        render_cart()

    def _reset_after_sale() -> None:
        cart.clear()
        order_discount["kind"] = None
        order_discount["value"] = 0
        discount_approved["ok"] = False
        render_cart()

    def open_discount_dialog() -> None:
        with ui.dialog() as dialog, ui.card().classes("gap-3"):
            ui.label("Скидка на чек").classes("text-lg font-bold")
            kind = ui.toggle({"none": "Нет", "percent": "%", "amount": "Сумма, тг"},
                             value=order_discount["kind"] or "none")
            init_val = (order_discount["value"] / 100 if order_discount["kind"] == "amount"
                        else order_discount["value"])
            val = ui.number("Значение", value=init_val, min=0,
                            format="%.0f").props("readonly").classes("w-full")
            numpad(val)

            def apply() -> None:
                if kind.value == "none":
                    order_discount["kind"] = None
                    order_discount["value"] = 0
                elif kind.value == "percent":
                    v = int(val.value or 0)
                    if not 0 <= v <= 100:
                        ui.notify("Процент 0..100", color="red")
                        return
                    order_discount["kind"] = "percent"
                    order_discount["value"] = v
                else:
                    order_discount["kind"] = "amount"
                    order_discount["value"] = round((val.value or 0) * 100)
                discount_approved["ok"] = False  # новая скидка — снова требует проверки
                dialog.close()
                render_cart()

            with ui.row().classes("gap-2"):
                ui.button("Применить", on_click=apply)
                ui.button("Отмена", on_click=dialog.close).props("flat")
        dialog.open()

    def render_cart() -> None:
        count = sum(c["qty"] for c in cart)
        cart_count_label.set_text(f"{count} поз. в чеке" if count else "Чек пуст")
        # Счётчики на плитках товаров живут в products_col — перерисовываем и его
        render_products()

        # В раскладке «Телефон» чек уходит под товары узкой колонкой, как на экране телефона
        phone = view["layout"] == "phone"
        cart_col.classes(replace="w-full max-w-lg shrink-0" if phone else "w-96 shrink-0")
        sale_row.classes(replace="w-full gap-4 items-start "
                                 + ("flex-col" if phone else "no-wrap"))

        cart_col.clear()
        with cart_col, ui.card().classes("w-full p-4 gap-2 sticky top-20"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Чек").classes("text-xl font-black")
                if cart:
                    ui.button("Очистить", icon="delete",
                              on_click=clear_cart).props("flat dense color=negative")
            if not cart:
                ui.label("Пусто. Нажмите товар слева.").classes("py-6 text-center text-base") \
                    .style("color: var(--text-muted)")
            for idx, c in enumerate(cart):
                label = c["name"] + (f" [{', '.join(c['mod_labels'])}]" if c["mod_labels"] else "")
                with ui.row().classes("items-center gap-2 w-full py-1 no-wrap") \
                        .style("border-bottom: 1px solid var(--border-subtle)"):
                    with ui.column().classes("gap-0 flex-1 min-w-0"):
                        ui.label(label).classes("text-base font-medium leading-tight")
                        ui.label(f"{line_sum_tiyn(c) / 100:.0f} тг").classes("text-sm") \
                            .style("color: var(--text-secondary)")

                    def dec(i=idx) -> None:
                        cart[i]["qty"] -= 1
                        if cart[i]["qty"] <= 0:
                            cart.pop(i)
                        render_cart()

                    def inc(i=idx) -> None:
                        cart[i]["qty"] += 1
                        render_cart()

                    ui.button("−", on_click=dec).props("round dense flat").classes("text-xl")
                    ui.label(f"{c['qty']}").classes("text-lg font-bold text-center").style("width:28px")
                    ui.button("+", on_click=inc).props("round dense flat").classes("text-xl")
            if cart:
                disc = order_discount_tiyn()
                with ui.row().classes("w-full items-center justify-between pt-1"):
                    ui.label(f"Подытог: {cart_subtotal_tiyn() / 100:.0f} тг").classes("text-sm") \
                        .style("color: var(--text-secondary)")
                    ui.button("Скидка", icon="percent",
                              on_click=open_discount_dialog).props("flat dense")
                if disc:
                    ui.label(f"Скидка: −{disc / 100:.0f} тг") \
                        .style("color: var(--status-warning)")
            with ui.row().classes("w-full items-baseline justify-between pt-1"):
                ui.label("Итого").classes("text-base").style("color: var(--text-secondary)")
                ui.label(f"{cart_total_tiyn() / 100:.0f} тг").classes("text-3xl font-black")
            if cart:
                ui.button("Оплата", on_click=open_payment).classes("w-full h-16 text-xl")

    def open_payment() -> None:
        total = cart_total_tiyn()
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-md p-5 gap-4"):
            with ui.column().classes("gap-0"):
                ui.label("К оплате").classes("text-sm").style("color: var(--text-secondary)")
                ui.label(f"{total / 100:.0f} тг").classes("text-4xl font-black leading-tight")
            split = ui.checkbox("Разделить оплату")

            single_col = ui.column().classes("w-full gap-3")
            with single_col:
                # Способ выбирается карточками с иконками, как в макете; select оставлен
                # скрытым — на нём завязаны валидация и проведение чека ниже.
                method = ui.select({m: _METHOD_LABELS[m] for m in SINGLE_METHODS},
                                   label="Способ", value="cash")
                method.set_visibility(False)
                methods_grid = ui.grid(columns=2).classes("w-full gap-2")

                def render_methods() -> None:
                    methods_grid.clear()
                    with methods_grid:
                        for mid in SINGLE_METHODS:
                            active = method.value == mid
                            btn = ui.button(on_click=lambda m=mid: pick_method(m)) \
                                .props("flat no-caps").classes(
                                    "flex flex-col items-start justify-center gap-1 "
                                    "h-20 p-3 rounded-xl w-full cp-method")
                            btn.style(
                                "background: var(--coffee-50); border: 2px solid var(--brand-primary)"
                                if active else
                                "background: var(--surface-card); border: 2px solid var(--border-subtle)"
                            )
                            with btn:
                                ui.icon(PAYMENT_ICONS[mid], size="24px")
                                ui.label(_METHOD_LABELS[mid]) \
                                    .classes("text-base font-bold cp-method-label")

                def pick_method(mid: str) -> None:
                    method.value = mid
                    render_methods()
                    refresh_single()

                render_methods()
                cash_col = ui.column().classes("w-full gap-2")
                with cash_col:
                    tendered = ui.number("Получено (наличные), тг", value=total / 100,
                                         format="%.0f").props("readonly").classes("w-full")
                    change_label = ui.label("").classes("text-base font-bold")

                    def refresh_change() -> None:
                        diff = round((tendered.value or 0) * 100) - total
                        if diff < 0:
                            change_label.set_text(f"Не хватает {-diff / 100:.0f} тг")
                            change_label.style("color: var(--status-danger)")
                        else:
                            change_label.set_text(
                                f"Сдача: {diff / 100:.0f} тг" if diff else "Сдачи нет")
                            change_label.style("color: var(--text-secondary)")

                    # Моноблок без клавиатуры: сумма набирается мышью, купюрами
                    # или кнопкой «Без сдачи» под сумму чека.
                    numpad(tendered, quick=BANKNOTES, exact=int(total / 100),
                           on_change=refresh_change)
                    refresh_change()

                terminal_hint = ui.label(
                    "Терминал сам покажет QR или примет карту. "
                    "Чек проведётся после подтверждения оплаты."
                ).classes("text-sm rounded-xl p-3") \
                    .style("color: var(--text-secondary); background: var(--surface-sunken)")
                qr_hint = ui.label(
                    "Оплату отмечает кассир вручную — система её не проверяет. "
                    "Убедитесь, что деньги пришли, и только потом проводите чек. "
                    "В отчётах помечается как ручная."
                ).classes("text-sm rounded-xl p-3") \
                    .style("color: var(--status-warning); background: var(--status-warning-bg)")

                def refresh_single() -> None:
                    cash_col.set_visibility(method.value == "cash")
                    terminal_hint.set_visibility(method.value == "kaspi_terminal")
                    qr_hint.set_visibility(method.value == "kaspi_qr")

                refresh_single()

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

            def _open_admin_approval() -> None:
                with ui.dialog() as adlg, ui.card().classes("gap-3"):
                    ui.label("Скидка выше лимита кассира").classes("text-lg font-bold")
                    ui.label("Одобрение администратора: введите PIN").classes("text-sm text-gray-500")
                    apin = ui.input("PIN администратора", password=True) \
                        .props("inputmode=numeric readonly").classes("w-full")
                    numpad(apin, money=False, max_len=6)

                    async def approve() -> None:
                        try:
                            with SessionLocal() as s:
                                admin = user_service.admin_by_pin(s, (apin.value or "").strip())
                        except LockedOut as e:
                            apin.value = ""
                            ui.notify(f"Слишком много попыток. Подождите {e.retry_after_seconds} с.",
                                      color="red")
                            return
                        if admin is None:
                            ui.notify("Неверный PIN администратора", color="red")
                            return
                        discount_approved["ok"] = True
                        adlg.close()
                        await confirm_payment()

                    with ui.row().classes("gap-2"):
                        ui.button("Одобрить", on_click=approve)
                        ui.button("Отмена", on_click=adlg.close).props("flat")
                adlg.open()

            async def confirm_payment() -> None:
                # Одобрение скидки над лимитом кассира — ДО любой оплаты (в т.ч. терминала)
                if order_discount["kind"] and not discount_approved["ok"]:
                    if not pricing.discount_within_limit_tiyn(
                            cart_subtotal_tiyn(), order_discount_tiyn(), cashier_limit):
                        _open_admin_approval()
                        return
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
                            ui.notify(
                                "Касса перестала ждать оплату. Терминал API отмены не поддерживает — "
                                "нажмите «Отмена» на самом терминале, иначе он будет ждать QR ещё "
                                "до 3 минут. Если клиент уже оплатил — проверьте статус на терминале.",
                                color="orange", multi_line=True, timeout=10000,
                            )
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
                                    order_discount_kind=order_discount["kind"],
                                    order_discount_value=order_discount["value"],
                                    discount_approved=discount_approved["ok"],
                                )
                                num = order.number
                        except Exception as e:
                            # деньги уже ушли: закрываем диалог и чистим корзину, чтобы кассир не пробил повторно
                            dialog.close()
                            _reset_after_sale()
                            ui.notify(f"Оплата прошла, но чек не сохранён ({e}). Запишите заказ вручную.",
                                      color="red")
                            return
                        dialog.close()
                        _reset_after_sale()
                        with success_host:
                            success_host.clear()
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
                        order = sales.create_sale(
                            s, cashier_id=uid, lines=lines, payments=payments,
                            order_discount_kind=order_discount["kind"],
                            order_discount_value=order_discount["value"],
                            discount_approved=discount_approved["ok"],
                        )
                        num = order.number
                except (ValueError, PermissionError) as e:
                    ui.notify(str(e), color="red")
                    return
                except Exception:
                    ui.notify("Не удалось провести чек. Ничего не списано, попробуйте ещё раз.", color="red")
                    return
                dialog.close()
                extra = f"Сдача: {change/100:.0f} тг" if change else ""
                _reset_after_sale()
                with success_host:
                    success_host.clear()
                    sale_success(num, extra)

            submit_btn = ui.button("Провести", on_click=confirm_payment) \
                .classes("w-full h-16 text-xl")
            ui.button("Отмена", on_click=dialog.close).props("outline").classes("w-full h-12")
        dialog.open()

    ui.button("К смене", icon="arrow_back",
              on_click=lambda: ui.navigate.to("/cashier")).props("flat")
    render_layout_switch()
    render_cart()  # рисует и товары: счётчики на плитках зависят от чека


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
            reason = ui.input("Причина").props("readonly").classes("w-full")
            reason_picker(reason)

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
                    # Количество — стрелками, чтобы обойтись без клавиатуры
                    q = ui.number("Вернуть", value=0, min=0, max=rem,
                                  format="%.0f").props("readonly")
                    qty_inputs[it.id] = q

                    def bump(delta: int, q=q, rem=rem) -> None:
                        q.value = max(0, min(rem, int(q.value or 0) + delta))

                    ui.button("−", on_click=lambda q=q, rem=rem: bump(-1, q, rem)) \
                        .props("round dense outline")
                    ui.button("+", on_click=lambda q=q, rem=rem: bump(1, q, rem)) \
                        .props("round dense outline")

            reason = ui.input("Причина").props("readonly").classes("w-full")
            reason_picker(reason)

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
