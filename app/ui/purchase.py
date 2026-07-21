from nicegui import ui
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Ingredient, StockMove
from app.services import inventory_service as inv
from app.timezone import to_almaty
from app.ui.guard import require_user
from app.ui.layout import cashier_header


@ui.page("/stock/purchase")
def purchase_page() -> None:
    if not require_user():
        return
    cashier_header()

    ui.label("Приход товара").classes("text-2xl font-bold")

    with SessionLocal() as session:
        ing_options = {
            i.id: f"{i.name} ({i.unit})"
            for i in session.scalars(select(Ingredient).where(Ingredient.is_active)).all()
        }

    if not ing_options:
        ui.label("Нет складских позиций. Добавьте их в /admin/stock").classes("text-red-600")
        return

    sel_ing = ui.select(ing_options, label="Позиция склада")
    qty = ui.number("Количество", value=0, min=1, format="%.0f")
    total = ui.number("Сумма закупки, тг", value=0, min=0, format="%.0f")

    history_box = ui.column().classes("w-full max-w-2xl gap-1 mt-4")

    def refresh_history() -> None:
        history_box.clear()
        with history_box, SessionLocal() as session:
            ui.label("Последние приходы").classes("text-xl")
            moves = session.scalars(
                select(StockMove).where(StockMove.kind == "purchase")
                .order_by(StockMove.created_at.desc()).limit(10)
            ).all()
            if not moves:
                ui.label("Приходов ещё не было").classes("text-gray-500")
            for m in moves:
                ing = session.get(Ingredient, m.ingredient_id)
                cost = (m.cost_tiyn or 0) / 100
                ui.label(
                    f"{to_almaty(m.created_at):%d.%m %H:%M} — {ing.name}: "
                    f"+{m.qty_delta} {ing.unit}, {cost:.2f} тг"
                )

    def do_receive() -> None:
        if not sel_ing.value:
            ui.notify("Выберите позицию склада", color="red")
            return
        if not qty.value or qty.value <= 0:
            ui.notify("Введите количество", color="red")
            return
        if total.value is None or total.value < 0:
            ui.notify("Введите сумму закупки", color="red")
            return
        try:
            with SessionLocal() as s:
                inv.receive_purchase(
                    s, sel_ing.value,
                    qty=round(qty.value),
                    total_cost_tiyn=round(total.value * 100),
                )
        except (ValueError, IntegrityError) as e:
            ui.notify(str(e), color="red")
            return
        ui.notify("Приход оформлен", color="green")
        qty.value = 0
        total.value = 0
        refresh_history()

    ui.button("Оформить приход", on_click=do_receive)
    refresh_history()
