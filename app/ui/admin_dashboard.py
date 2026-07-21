from nicegui import ui

from app.db import SessionLocal
from app.models import User
from app.services import dashboard_service as ds
from app.services import shift_service as ss
from app.timezone import to_almaty
from app.ui.guard import require_admin


@ui.page("/admin/dashboard")
def admin_dashboard_page() -> None:
    if not require_admin():
        return

    ui.label("Дашборд").classes("text-2xl font-bold")
    box = ui.column().classes("w-full max-w-3xl gap-3")

    def refresh() -> None:
        box.clear()
        with box, SessionLocal() as session:
            summary = ds.today_summary(session)
            shift = ss.current_open_shift(session)
            low_stock = ds.low_stock_ingredients(session)

            with ui.row().classes("gap-6"):
                ui.label(f"Выручка сегодня: {summary.revenue_tiyn / 100:.2f} тг").classes("text-lg")
                ui.label(f"Чеков: {summary.orders_count}").classes("text-lg")
                ui.label(f"Позиций продано: {summary.items_count}").classes("text-lg")

            if shift is None:
                ui.label("Смена закрыта").classes("text-gray-500")
            else:
                cashier = session.get(User, shift.cashier_id)
                cashier_name = cashier.name if cashier is not None else "неизвестен"
                ui.label(
                    f"Смена открыта: {cashier_name}, с {to_almaty(shift.opened_at):%d.%m.%Y %H:%M}"
                ).classes("text-green-700")

            ui.label("На исходе").classes("text-xl mt-4")
            if not low_stock:
                ui.label("Все позиции в норме").classes("text-gray-500")
            for ing in low_stock:
                ui.label(
                    f"{ing.name}: {ing.stock_qty} {ing.unit} (порог {ing.low_stock_threshold})"
                ).classes("text-red-600")

    ui.timer(3.0, refresh)
