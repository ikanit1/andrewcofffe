from datetime import date

from nicegui import ui

from app.db import SessionLocal
from app.services import reporting_service as rs
from app.services.report_excel import build_reports_workbook
from app.ui.guard import require_admin
from app.ui.layout import admin_header

_PRESETS = {"today": "Сегодня", "yesterday": "Вчера", "week": "7 дней",
            "month": "Месяц", "custom": "Свой"}
_METHOD_LABELS = {"cash": "Наличные", "card": "Карта",
                  "kaspi_qr": "Kaspi QR", "kaspi_terminal": "Kaspi (терминал)"}


def _tg(tiyn: int) -> str:
    return f"{tiyn / 100:,.0f} тг".replace(",", " ")


@ui.page("/admin/reports")
def reports_page() -> None:
    if not require_admin():
        return
    admin_header()

    ui.label("Отчёты").classes("text-2xl font-bold")

    preset = ui.toggle(_PRESETS, value="today")
    with ui.row().classes("items-center gap-2") as custom_row:
        d_from = ui.date(value=date.today().isoformat())
        d_to = ui.date(value=date.today().isoformat())
    custom_row.bind_visibility_from(preset, "value", value="custom")

    body = ui.column().classes("w-full max-w-4xl gap-4")

    def current_period() -> rs.Period | None:
        if preset.value == "custom":
            try:
                s = date.fromisoformat(d_from.value)
                e = date.fromisoformat(d_to.value)
            except (TypeError, ValueError):
                ui.notify("Укажите даты", color="red")
                return None
            if e < s:
                ui.notify("Конец периода раньше начала", color="red")
                return None
            return rs.period_from_dates(s, e)
        return rs.period_from_preset(preset.value)

    def build_reports():
        period = current_period()
        if period is None:
            return None
        with SessionLocal() as session:
            return (
                period,
                rs.revenue_by_method(session, period),
                rs.top_products(session, period),
                rs.revenue_by_category(session, period),
                rs.cost_and_margin(session, period),
                rs.shifts_and_cashiers(session, period),
            )

    def show() -> None:
        data = build_reports()
        body.clear()
        if data is None:
            return
        _, rev, top, cats, margin, shifts = data
        with body:
            with ui.card().classes("w-full"):
                ui.label("Сводка").classes("text-xl font-bold")
                ui.label(f"Продажи: {_tg(rev.gross_tiyn)}   Возвраты: {_tg(rev.refunds_tiyn)}"
                         f"   Чистая: {_tg(rev.net_tiyn)}")
                ui.label(f"Маржа: {_tg(margin.margin_tiyn)} ({margin.margin_pct}%)   "
                         f"Чеков: {rev.orders_count}")

            with ui.card().classes("w-full"):
                ui.label("Выручка по способам").classes("text-xl font-bold")
                if not rev.by_method:
                    ui.label("Нет данных за период").classes("text-gray-500")
                for method, amount in rev.by_method.items():
                    ui.label(f"{_METHOD_LABELS.get(method, method)}: {_tg(amount)}")

            with ui.card().classes("w-full"):
                ui.label("Топ товаров").classes("text-xl font-bold")
                if not top:
                    ui.label("Нет данных за период").classes("text-gray-500")
                for r in top:
                    ui.label(f"{r.name}: {r.qty_net} шт, {_tg(r.revenue_tiyn)}")

            with ui.card().classes("w-full"):
                ui.label("По категориям").classes("text-xl font-bold")
                if not cats:
                    ui.label("Нет данных за период").classes("text-gray-500")
                for c in cats:
                    ui.label(f"{c.category}: {_tg(c.revenue_tiyn)}")

            with ui.card().classes("w-full"):
                ui.label("Смены и кассиры").classes("text-xl font-bold")
                if not shifts.by_cashier:
                    ui.label("Нет данных за период").classes("text-gray-500")
                for c in shifts.by_cashier:
                    ui.label(f"{c.cashier_name}: смен {c.shifts_count}, чеков {c.orders_count}, "
                             f"{_tg(c.revenue_tiyn)}, маржа {_tg(c.margin_tiyn)}")

    def download() -> None:
        data = build_reports()
        if data is None:
            return
        period = data[0]
        content = build_reports_workbook(*data)
        ui.download(content, f"Отчёт_{period.start:%Y%m%d}-{period.end:%Y%m%d}.xlsx")

    with ui.row().classes("gap-2 mt-2"):
        ui.button("Показать", on_click=show)
        ui.button("Скачать Excel", icon="download", on_click=download)

    show()
