from nicegui import ui

from app.db import SessionLocal
from app.services import shift_service as ss
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
        ui.label(f"Ожидается в кассе: {expected / 100:.0f} тг")
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
            ui.notify(f"Смена закрыта. Расхождение: {diff:+.0f} тг")
            ui.navigate.to("/cashier")

        ui.button("Закрыть смену", on_click=do_close, color="red")
