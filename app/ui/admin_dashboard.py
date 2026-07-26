from nicegui import ui

from app.db import SessionLocal
from app.models import User
from app.services import dashboard_service as ds
from app.services import shift_service as ss
from app.timezone import to_almaty
from app.ui.design import stat_tile
from app.ui.guard import require_admin
from app.ui.layout import admin_header


@ui.page("/admin/dashboard")
def admin_dashboard_page() -> None:
    if not require_admin():
        return
    admin_header()

    ui.label("Дашборд").classes("text-2xl font-black")

    async def do_backup() -> None:
        from app.services.backup_service import run_backup_once
        ui.notify("Делаю бэкап…")
        result = await run_backup_once()
        if result.error:
            ui.notify(f"Бэкап {result.path.name} сделан, но: {result.error}", color="orange")
        else:
            ui.notify(
                f"Бэкап готов: {result.path.name} "
                f"({result.size_bytes / 1024 / 1024:.1f} МБ), "
                f"в Telegram доставлено: {result.delivered_count}",
                color="green",
            )

    ui.button("Сделать бэкап сейчас", icon="backup", on_click=do_backup)
    box = ui.column().classes("w-full max-w-3xl gap-3")

    def refresh() -> None:
        box.clear()
        with box, SessionLocal() as session:
            summary = ds.today_summary(session)
            shift = ss.current_open_shift(session)
            low_stock = ds.low_stock_ingredients(session)

            with ui.row().classes("w-full gap-3 no-wrap"):
                stat_tile("Выручка сегодня", f"{summary.revenue_tiyn / 100:.0f} тг")
                stat_tile("Чеков", str(summary.orders_count))
                stat_tile("Позиций продано", str(summary.items_count))

            if shift is None:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("lock", size="20px").style("color: var(--text-muted)")
                    ui.label("Смена закрыта").style("color: var(--text-secondary)")
            else:
                cashier = session.get(User, shift.cashier_id)
                cashier_name = cashier.name if cashier is not None else "неизвестен"
                with ui.row().classes("items-center gap-2"):
                    ui.icon("check_circle", size="20px").style("color: var(--status-success)")
                    ui.label(
                        f"Смена открыта: {cashier_name}, "
                        f"с {to_almaty(shift.opened_at):%d.%m.%Y %H:%M}"
                    ).style("color: var(--status-success)")

            with ui.card().classes("w-full p-4 gap-2"):
                ui.label("На исходе").classes("text-lg font-bold")
                if not low_stock:
                    ui.label("Все позиции в норме").style("color: var(--text-secondary)")
                for ing in low_stock:
                    ui.label(
                        f"{ing.name}: {ing.stock_qty} {ing.unit} "
                        f"(порог {ing.low_stock_threshold})"
                    ).style("color: var(--status-danger)")

    ui.timer(3.0, refresh)
