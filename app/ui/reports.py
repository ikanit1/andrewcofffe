from datetime import date, timedelta

from nicegui import ui

from app.db import SessionLocal
from app.services import reporting_service as rs
from app.services.report_excel import build_reports_workbook
from app.ui.design import category_icon, empty_state
from app.ui.guard import require_admin
from app.ui.layout import admin_header

_PRESETS = (("today", "Сегодня"), ("yesterday", "Вчера"), ("week", "7 дней"),
            ("month", "Месяц"), ("custom", "Свой период"))
_METHOD_LABELS = {"cash": "Наличные", "card": "Карта",
                  "kaspi_qr": "Kaspi QR", "kaspi_terminal": "Kaspi (терминал)"}
_METHOD_ICONS = {"cash": "payments", "card": "credit_card",
                 "kaspi_qr": "qr_code_2", "kaspi_terminal": "contactless"}
_DAY_FILTERS = (("all", "Все чеки"), ("refunds", "С возвратом"), ("cash", "Наличные"),
                ("kaspi_qr", "Kaspi QR"), ("card", "Карта"),
                ("kaspi_terminal", "Терминал"))

_CARD = ("background: var(--surface-card); border:1px solid var(--border-subtle);"
         "border-radius:16px")
_CHART_HEIGHT = 130


def _tg(tiyn: int) -> str:
    return f"{tiyn / 100:,.0f} тг".replace(",", " ")


def _checks(n: int) -> str:
    """«1 чек» / «2 чека» / «5 чеков» — иначе подписи выглядят машинно."""
    if 11 <= n % 100 <= 14:
        return f"{n} чеков"
    return f"{n} чек" if n % 10 == 1 else (f"{n} чека" if 2 <= n % 10 <= 4 else f"{n} чеков")


def _days_word(n: int) -> str:
    """«1 день», «2 дня», «5 дней» — с исключением 11–14, где всегда «дней»
    (иначе 21 давало бы «21 дней», а 11 — «11 день»)."""
    if 11 <= n % 100 <= 14:
        return "дней"
    if n % 10 == 1:
        return "день"
    return "дня" if 2 <= n % 10 <= 4 else "дней"


def range_label(days: list[rs.DayRow]) -> str:
    """Подпись периода под заголовком: «22.07 — 28.07.2026 · 7 дней»."""
    if not days:
        return "—"
    n = len(days)
    if n == 1:
        return f"{days[0].day:%d.%m.%Y} · 1 день"
    return f"{days[0].day:%d.%m} — {days[-1].day:%d.%m.%Y} · {n} {_days_word(n)}"


def receipt_matches(receipt: rs.Receipt, *, hour: int | None, method_filter: str) -> bool:
    """Попадает ли чек под выбранные фильтры дня.

    Час берётся из клика по столбцу графика, фильтр — из пилюль под заголовком;
    работают вместе, а не вытесняют друг друга.
    """
    if hour is not None and receipt.at.hour != hour:
        return False
    if method_filter == "all":
        return True
    if method_filter == "refunds":
        return bool(receipt.refunded_tiyn)
    return method_filter in receipt.methods


def _pill(label: str, active: bool, on_click, *, dense: bool = False) -> None:
    cls = "cp-pill-active" if active else "cp-pill-idle"
    size = "h-10 px-4 text-sm" if dense else "h-11 px-4"
    ui.button(label, on_click=on_click).props("flat no-caps") \
        .classes(f"{size} rounded-full cp-hover {cls}")


def _bar_row(label: str, icon: str, amount: str, right: str, pct: int) -> None:
    """Строка с полосой заполнения — общая для способов оплаты и категорий."""
    with ui.column().classes("gap-1 w-full"):
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.icon(icon, size="20px").style("color: var(--brand-primary)")
            ui.label(label).classes("flex-1 text-base truncate")
            ui.label(amount).classes("text-base font-bold")
            ui.label(right).classes("text-xs text-right") \
                .style("color: var(--text-secondary); width:56px")
        with ui.element("div").classes("w-full rounded-full overflow-hidden") \
                .style("height:8px; background: var(--surface-sunken)"):
            ui.element("div").classes("h-full rounded-full") \
                .style(f"width:{pct}%; background: var(--brand-primary)")


@ui.page("/admin/reports")
def reports_page() -> None:
    if not require_admin():
        return
    admin_header()

    today = date.today()
    state = {
        "preset": "today",
        "from": today.isoformat(),
        "to": today.isoformat(),
        "sort": "rev",          # топ товаров: по выручке или по количеству
        "day": None,            # открытый день (date) — режим детализации
        "day_hour": None,       # фильтр чеков по часу
        "day_filter": "all",
        "open_receipt": None,   # раскрытый чек
    }

    root = ui.column().classes("w-full gap-4 mx-auto").style("max-width:1180px")

    # ---------- расчёт периода ----------

    def period_or_error() -> tuple[rs.Period | None, str]:
        if state["preset"] != "custom":
            return rs.period_from_preset(state["preset"]), ""
        try:
            a = date.fromisoformat(state["from"])
            b = date.fromisoformat(state["to"])
        except (TypeError, ValueError):
            return None, "Укажите обе даты периода"
        if b < a:
            return None, "Конец периода раньше начала"
        return rs.period_from_dates(a, b), ""

    def go_day(day: date) -> None:
        state.update(day=day, day_hour=None, day_filter="all", open_receipt=None)
        render()

    def back_to_list() -> None:
        state["day"] = None
        render()

    # ---------- шапка и выбор периода ----------

    def render_header(days: list[rs.DayRow], error: str) -> None:
        with ui.row().classes("w-full items-end justify-between gap-4 flex-wrap"):
            with ui.column().classes("gap-0"):
                ui.label("Отчёты").classes("text-2xl font-black leading-tight")
                ui.label(range_label(days) if not error else "Период указан неверно") \
                    .classes("text-sm").style("color: var(--text-secondary)")
            with ui.row().classes("gap-2 flex-wrap"):
                if len(days) == 1:
                    ui.button("Подробно за день", icon="receipt_long",
                              on_click=lambda d=days[0].day: go_day(d)) \
                        .props("outline no-caps")
                ui.button("X-отчёт", icon="assessment", on_click=_show_x_report) \
                    .props("outline no-caps")
                ui.button("Скачать Excel", icon="download", on_click=_download) \
                    .props("no-caps")

        with ui.row().classes("w-full items-center gap-3 flex-wrap p-3").style(_CARD):
            with ui.row().classes("gap-2 flex-wrap"):
                for key, label in _PRESETS:
                    _pill(label, state["preset"] == key,
                          lambda k=key: (state.update(preset=k), render()))
            if state["preset"] == "custom":
                with ui.row().classes("items-center gap-2 ml-auto flex-wrap"):
                    _date_field("from")
                    ui.label("—").style("color: var(--text-secondary)")
                    _date_field("to")

    def _date_field(key: str) -> None:
        field = ui.input(value=state[key]).props("type=date outlined dense") \
            .style("min-width:150px")
        field.on_value_change(lambda e, k=key: (state.update({k: e.value}), render()))

    # ---------- сводка ----------

    def render_kpis(sm: rs.Summary, prev: rs.Summary) -> None:
        with ui.grid().classes("w-full gap-3") \
                .style("grid-template-columns: repeat(auto-fit, minmax(190px, 1fr))"):
            with ui.column().classes("gap-1 p-4").style(
                    "background: var(--surface-card); border:1px solid var(--brand-primary);"
                    "border-radius:16px"):
                ui.label("Чистая выручка").classes("text-xs") \
                    .style("color: var(--text-secondary)")
                ui.label(_tg(sm.net_tiyn)).classes("text-3xl font-black leading-tight")
                _delta(sm.net_tiyn, prev.net_tiyn)
            _kpi("Продажи", _tg(sm.gross_tiyn), f"Чеков: {sm.orders_count}")
            _kpi("Возвраты", _tg(sm.refunds_tiyn),
                 f"{sm.refunds_tiyn / sm.gross_tiyn * 100:.1f}% от продаж"
                 if sm.gross_tiyn else "нет возвратов",
                 value_color="var(--status-danger)" if sm.refunds_tiyn else None)
            _kpi("Маржа", _tg(sm.margin_tiyn),
                 f"{sm.margin_pct}% · себестоимость {_tg(sm.cogs_tiyn)}")
            _kpi("Средний чек", _tg(sm.avg_check_tiyn), f"Позиций: {sm.items_count}")

    def _kpi(title: str, value: str, hint: str, *, value_color: str | None = None) -> None:
        with ui.column().classes("gap-1 p-4").style(_CARD):
            ui.label(title).classes("text-xs").style("color: var(--text-secondary)")
            label = ui.label(value).classes("text-2xl font-black leading-tight")
            if value_color:
                label.style(f"color: {value_color}")
            ui.label(hint).classes("text-xs").style("color: var(--text-secondary)")

    def _delta(now: int, before: int) -> None:
        """Сравнение с предыдущим отрезком той же длины."""
        if not before:
            ui.label("нет данных за прошлый период").classes("text-xs") \
                .style("color: var(--text-secondary)")
            return
        pct = round((now - before) / before * 100, 1)
        up = pct >= 0
        with ui.row().classes("items-center gap-1"):
            ui.icon("trending_up" if up else "trending_down", size="16px") \
                .style(f"color: var(--status-{'success' if up else 'danger'})")
            ui.label(f"{'+' if up else ''}{pct}% к прошлому периоду").classes("text-xs") \
                .style(f"color: var(--status-{'success' if up else 'danger'})")

    # ---------- график ----------

    def render_chart(title: str, bars: list[tuple[str, int, str, object]], hint: str) -> None:
        """bars: (подпись, значение, всплывающая подсказка, обработчик клика или None)."""
        peak = max((v for _, v, _, _ in bars), default=0)
        peak_label = next((lb for lb, v, _, _ in bars if v == peak and peak), "—")
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            with ui.row().classes("w-full items-baseline justify-between gap-3 flex-wrap"):
                ui.label(title).classes("text-lg font-bold")
                ui.label(f"Пик: {peak_label} · {_tg(peak)}{hint}").classes("text-xs") \
                    .style("color: var(--text-secondary)")
            with ui.row().classes("w-full items-end gap-1 no-wrap") \
                    .style(f"height:{_CHART_HEIGHT + 30}px"):
                for label, value, tip, handler in bars:
                    _bar(label, value, peak, tip, handler)

    def _bar(label: str, value: int, peak: int, tip: str, handler) -> None:
        height = max(4, round(value / peak * _CHART_HEIGHT)) if peak else 4
        col = ui.column().classes("flex-1 min-w-0 items-center justify-end gap-1 h-full") \
            .style(f"cursor: {'pointer' if handler else 'default'}")
        if handler:
            col.on("click", handler)
        with col:
            bar = ui.element("div").classes("w-full") \
                .style(f"height:{height}px; border-radius:8px 8px 4px 4px;"
                       f"background: var(--brand-primary)"
                       f"{'' if value == peak and peak else '; opacity:.55'}")
            bar.tooltip(tip)
            ui.label(label).classes("text-xs truncate max-w-full") \
                .style("color: var(--text-secondary)")

    # ---------- разбивки ----------

    def render_breakdowns(session, period: rs.Period, sm: rs.Summary) -> None:
        methods = rs.revenue_by_method(session, period).by_method
        cats = rs.revenue_by_category(session, period)
        with ui.grid().classes("w-full gap-4") \
                .style("grid-template-columns: repeat(auto-fit, minmax(320px, 1fr))"):
            with ui.column().classes("gap-3 p-4").style(_CARD):
                ui.label("Выручка по способам").classes("text-lg font-bold")
                top = max(methods.values(), default=0)
                for method, amount in sorted(methods.items(), key=lambda kv: -kv[1]):
                    _bar_row(_METHOD_LABELS.get(method, method),
                             _METHOD_ICONS.get(method, "payments"), _tg(amount),
                             f"{amount / sm.gross_tiyn * 100:.0f}%" if sm.gross_tiyn else "0%",
                             round(amount / top * 100) if top else 0)
                if not methods:
                    ui.label("Нет продаж за период").classes("text-sm") \
                        .style("color: var(--text-secondary)")
            with ui.column().classes("gap-3 p-4").style(_CARD):
                ui.label("По категориям").classes("text-lg font-bold")
                top = cats[0].revenue_tiyn if cats else 0
                for c in cats:
                    _bar_row(c.category, category_icon(c.category), _tg(c.revenue_tiyn),
                             f"{c.qty_net} шт",
                             round(c.revenue_tiyn / top * 100) if top else 0)
                if not cats:
                    ui.label("Нет продаж за период").classes("text-sm") \
                        .style("color: var(--text-secondary)")

    def render_top(session, period: rs.Period) -> None:
        rows = rs.top_products(session, period, limit=10)
        by_qty = state["sort"] == "qty"
        rows = sorted(rows, key=lambda r: r.qty_net if by_qty else r.revenue_tiyn, reverse=True)
        top = max((r.qty_net if by_qty else r.revenue_tiyn for r in rows), default=0)
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
                ui.label("Топ товаров").classes("text-lg font-bold")
                with ui.row().classes("gap-2"):
                    for key, label in (("rev", "По выручке"), ("qty", "По количеству")):
                        _pill(label, state["sort"] == key,
                              lambda k=key: (state.update(sort=k), render()), dense=True)
            _top_head()
            if not rows:
                ui.label("Нет продаж за период").classes("text-sm") \
                    .style("color: var(--text-secondary)")
            for i, r in enumerate(rows, start=1):
                value = r.qty_net if by_qty else r.revenue_tiyn
                _top_row(i, r, round(value / top * 100) if top else 0,
                         striped=i % 2 == 0)

    _TOP_COLUMNS = "grid-template-columns: 28px minmax(0,1fr) 90px 90px 130px"

    def _top_head() -> None:
        with ui.element("div").classes("w-full gap-3 items-center px-1") \
                .style(f"display:grid; {_TOP_COLUMNS}"):
            for text, align in (("#", "left"), ("Товар", "left"), ("Продано", "right"),
                                ("Возвраты", "right"), ("Выручка", "right")):
                ui.label(text).classes("text-xs uppercase") \
                    .style(f"color: var(--text-secondary); letter-spacing:.06em; text-align:{align}")

    def _top_row(rank: int, r: rs.ProductRow, pct: int, *, striped: bool) -> None:
        with ui.element("div").classes("w-full gap-3 items-center px-1 rounded-lg") \
                .style(f"display:grid; {_TOP_COLUMNS}; min-height:52px;"
                       f"background: {'var(--surface-sunken)' if striped else 'transparent'}"):
            ui.label(str(rank)).classes("text-sm font-bold") \
                .style("color: var(--text-secondary)")
            with ui.column().classes("gap-1 min-w-0"):
                ui.label(r.name).classes("text-base font-semibold truncate")
                with ui.element("div").classes("w-full rounded-full overflow-hidden") \
                        .style("height:5px; background: var(--surface-sunken)"):
                    ui.element("div").classes("h-full") \
                        .style(f"width:{pct}%; background: var(--brand-primary)")
            ui.label(str(r.qty_net)).classes("text-base").style("text-align:right")
            ui.label(str(r.qty_refunded)).classes("text-base") \
                .style("text-align:right; color: "
                       + ("var(--status-danger)" if r.qty_refunded else "var(--text-primary)"))
            ui.label(_tg(r.revenue_tiyn)).classes("text-base font-bold").style("text-align:right")

    def render_shifts(session, period: rs.Period) -> None:
        report = rs.shifts_and_cashiers(session, period)
        with ui.grid().classes("w-full gap-4") \
                .style("grid-template-columns: repeat(auto-fit, minmax(320px, 1fr))"):
            with ui.column().classes("gap-3 p-4").style(_CARD):
                ui.label("Кассиры").classes("text-lg font-bold")
                for c in report.by_cashier:
                    _cashier_row(c)
                if not report.by_cashier:
                    ui.label("Нет смен за период").classes("text-sm") \
                        .style("color: var(--text-secondary)")
            with ui.column().classes("gap-2 p-4").style(_CARD):
                with ui.row().classes("w-full items-baseline justify-between gap-2"):
                    ui.label("Смены").classes("text-lg font-bold")
                    ui.label(f"{len(report.shifts)} за период").classes("text-xs") \
                        .style("color: var(--text-secondary)")
                for sh in reversed(report.shifts[-7:]):
                    _shift_row(sh)
                if not report.shifts:
                    ui.label("Нет смен за период").classes("text-sm") \
                        .style("color: var(--text-secondary)")

    def _cashier_row(c: rs.CashierRow) -> None:
        with ui.row().classes("items-center gap-3 p-3 rounded-2xl w-full no-wrap") \
                .style("background: var(--surface-sunken)"):
            with ui.row().classes("items-center justify-center rounded-full flex-none") \
                    .style("width:44px;height:44px;background: var(--coffee-50);"
                           "color: var(--brand-primary)"):
                ui.label((c.cashier_name or "?")[:1].upper()).classes("text-lg font-black")
            with ui.column().classes("gap-0 flex-1 min-w-0"):
                ui.label(c.cashier_name).classes("text-base font-bold truncate")
                ui.label(f"Смен: {c.shifts_count} · Чеков: {c.orders_count}").classes("text-xs") \
                    .style("color: var(--text-secondary)")
            with ui.column().classes("gap-0 items-end flex-none"):
                ui.label(_tg(c.revenue_tiyn)).classes("text-base font-bold")
                ui.label(f"маржа {_tg(c.margin_tiyn)}").classes("text-xs") \
                    .style("color: var(--text-secondary)")

    def _shift_row(sh: rs.ShiftRow) -> None:
        from app.timezone import to_almaty
        opened = to_almaty(sh.opened_at)
        closed = to_almaty(sh.closed_at) if sh.closed_at else None
        row = ui.row().classes("items-center gap-3 p-2 rounded-xl w-full no-wrap cp-hover") \
            .style("background: var(--surface-sunken); cursor:pointer; min-height:48px")
        row.on("click", lambda d=opened.date(): go_day(d))
        with row:
            ui.label(f"№{sh.shift_id}").classes("text-xs flex-none") \
                .style("color: var(--text-secondary); width:44px")
            with ui.column().classes("gap-0 flex-1 min-w-0"):
                span = f"{opened:%H:%M} — {closed:%H:%M}" if closed else f"{opened:%H:%M} — сейчас"
                ui.label(f"{opened:%d.%m} · {span}").classes("text-sm font-semibold truncate")
                ui.label(f"{sh.cashier_name} · {_checks(sh.orders_count)}").classes("text-xs") \
                    .style("color: var(--text-secondary)")
            with ui.row().classes("items-center gap-2 flex-none"):
                ui.label(_tg(sh.revenue_tiyn)).classes("text-sm font-bold")
                is_open = closed is None
                ui.label("открыта" if is_open else "закрыта").classes("text-xs font-bold") \
                    .style("padding:3px 8px;border-radius:999px;background: "
                           + ("var(--status-success-bg); color: var(--status-success)"
                              if is_open else "var(--surface-card); color: var(--text-secondary)"))

    # ---------- детализация дня ----------

    def render_day(session, day: date) -> None:
        sm = rs.summary(session, rs.period_from_dates(day, day))
        receipts = rs.day_receipts(session, day)
        hours = rs.revenue_by_hour(session, day)

        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            ui.button("Все отчёты", icon="arrow_back", on_click=back_to_list) \
                .props("outline no-caps").classes("rounded-full")
            with ui.column().classes("gap-0 flex-1").style("min-width:200px"):
                ui.label(f"{day:%d %B %Y}").classes("text-2xl font-black leading-tight")
                ui.label(f"{_checks(sm.orders_count)} · {_tg(sm.net_tiyn)} чистыми") \
                    .classes("text-sm").style("color: var(--text-secondary)")
            with ui.row().classes("gap-2"):
                ui.button(icon="chevron_left",
                          on_click=lambda: go_day(day - timedelta(days=1))) \
                    .props("outline").tooltip("Предыдущий день")
                nxt = ui.button(icon="chevron_right",
                                on_click=lambda: go_day(day + timedelta(days=1))) \
                    .props("outline").tooltip("Следующий день")
                if day >= date.today():
                    nxt.disable()
                ui.button("Excel за день", icon="download",
                          on_click=lambda d=day: _download_day(d)).props("outline no-caps")

        if sm.orders_count == 0:
            empty_state(icon="insights", title="В этот день продаж не было",
                        hint="Выберите другой день стрелками или вернитесь к списку отчётов.")
            return

        with ui.grid().classes("w-full gap-3") \
                .style("grid-template-columns: repeat(auto-fit, minmax(170px, 1fr))"):
            with ui.column().classes("gap-1 p-4").style(
                    "background: var(--surface-card); border:1px solid var(--brand-primary);"
                    "border-radius:16px"):
                ui.label("Чистая выручка").classes("text-xs") \
                    .style("color: var(--text-secondary)")
                ui.label(_tg(sm.net_tiyn)).classes("text-2xl font-black leading-tight")
                ui.label(f"продажи {_tg(sm.gross_tiyn)}").classes("text-xs") \
                    .style("color: var(--text-secondary)")
            _kpi("Чеков", str(sm.orders_count), f"средний {_tg(sm.avg_check_tiyn)}")
            peak = max(hours, key=lambda h: h.revenue_tiyn)
            _kpi("Позиций продано", str(sm.items_count),
                 f"пик в {peak.hour:02d}:00" if peak.revenue_tiyn else "—")
            _kpi("Маржа", _tg(sm.margin_tiyn),
                 f"{sm.margin_pct}% · с/с {_tg(sm.cogs_tiyn)}")
            _kpi("Возвраты", _tg(sm.refunds_tiyn),
                 f"{sum(1 for r in receipts if r.refunded_tiyn)} с возвратом"
                 if sm.refunds_tiyn else "без возвратов",
                 value_color="var(--status-danger)" if sm.refunds_tiyn else None)

        def pick_hour(h: int) -> None:
            state["day_hour"] = None if state["day_hour"] == h else h
            state["open_receipt"] = None
            render()

        hint = ("Нажмите на час, чтобы отфильтровать чеки"
                if state["day_hour"] is None
                else f"Фильтр: {state['day_hour']:02d}:00 — нажмите ещё раз, чтобы снять")
        render_chart("Выручка по часам",
                     [(f"{h.hour:02d}", h.revenue_tiyn,
                       f"{h.hour:02d}:00 — {_tg(h.revenue_tiyn)} · {_checks(h.orders_count)}",
                       (lambda h=h: pick_hour(h.hour)))
                      for h in hours],
                     f" · {hint}")

        _render_day_methods(receipts, sm)
        _render_day_receipts(receipts)

    def _render_day_methods(receipts: list[rs.Receipt], sm: rs.Summary) -> None:
        totals: dict[str, int] = {}
        counts: dict[str, int] = {}
        for r in receipts:
            totals[r.method] = totals.get(r.method, 0) + r.total_tiyn
            counts[r.method] = counts.get(r.method, 0) + 1
        top = max(totals.values(), default=0)
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            ui.label("Способы оплаты").classes("text-lg font-bold")
            for method, amount in sorted(totals.items(), key=lambda kv: -kv[1]):
                _bar_row(f"{_METHOD_LABELS.get(method, method)} · {_checks(counts[method])}",
                         _METHOD_ICONS.get(method, "payments"), _tg(amount),
                         f"{amount / sm.gross_tiyn * 100:.0f}%" if sm.gross_tiyn else "0%",
                         round(amount / top * 100) if top else 0)

    def _render_day_receipts(receipts: list[rs.Receipt]) -> None:
        shown = [r for r in receipts
                 if receipt_matches(r, hour=state["day_hour"],
                                    method_filter=state["day_filter"])]
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
                ui.label("Чеки за день").classes("text-lg font-bold")
                ui.label(f"{len(shown)} из {_checks(len(receipts))} · "
                         f"{_tg(sum(r.total_tiyn for r in shown))}").classes("text-xs") \
                    .style("color: var(--text-secondary)")
            with ui.row().classes("gap-2 flex-wrap"):
                for key, label in _DAY_FILTERS:
                    _pill(label, state["day_filter"] == key,
                          lambda k=key: (state.update(day_filter=k, open_receipt=None), render()),
                          dense=True)
            if not shown:
                ui.label("Под фильтр не попал ни один чек").classes("text-sm py-6 text-center") \
                    .style("color: var(--text-secondary)")
            for r in shown:
                _receipt_card(r)

    def _receipt_card(r: rs.Receipt) -> None:
        opened = state["open_receipt"] == r.number
        border = "var(--status-danger-border)" if r.refunded_tiyn else "var(--border-subtle)"
        with ui.column().classes("w-full gap-0 overflow-hidden") \
                .style(f"border:1px solid {border}; border-radius:14px"):
            head = ui.row().classes("items-center gap-3 w-full no-wrap px-3 py-2 cp-hover") \
                .style("cursor:pointer; min-height:56px")
            head.on("click", lambda n=r.number: _toggle_receipt(n))
            with head:
                ui.label(f"{r.at:%H:%M}").classes("text-sm font-bold flex-none") \
                    .style("width:52px")
                ui.label(f"№{r.number}").classes("text-xs flex-none") \
                    .style("color: var(--text-secondary); width:56px")
                with ui.column().classes("gap-0 flex-1 min-w-0"):
                    ui.label(", ".join(f"{l.name} ×{l.qty}" for l in r.lines)) \
                        .classes("text-sm truncate")
                    if r.refunded_tiyn:
                        full = r.refunded_tiyn >= r.total_tiyn
                        ui.label(f"{'Возврат полностью' if full else 'Частичный возврат'} · "
                                 f"−{_tg(r.refunded_tiyn)}"
                                 + (f" · {r.refund_reason}" if r.refund_reason else "")) \
                            .classes("text-xs").style("color: var(--status-danger)")
                with ui.row().classes("items-center gap-1 flex-none"):
                    ui.icon(_METHOD_ICONS.get(r.method, "payments"), size="18px") \
                        .style("color: var(--text-secondary)")
                    ui.label(_METHOD_LABELS.get(r.method, r.method)).classes("text-xs") \
                        .style("color: var(--text-secondary)")
                ui.label(_tg(r.total_tiyn)).classes("text-base font-bold flex-none") \
                    .style("min-width:100px; text-align:right")
                ui.icon("expand_less" if opened else "expand_more", size="22px") \
                    .style("color: var(--text-secondary)")
            if opened:
                with ui.column().classes("w-full gap-1 px-3 py-2") \
                        .style("background: var(--surface-sunken);"
                               "border-top:1px solid var(--border-subtle)"):
                    for l in r.lines:
                        with ui.row().classes("items-center gap-3 w-full no-wrap"):
                            ui.label(l.name).classes("flex-1 text-sm truncate")
                            ui.label(f"{_tg(l.unit_price_tiyn)} × {l.qty}").classes("text-sm") \
                                .style("color: var(--text-secondary)")
                            ui.label(_tg(l.line_total_tiyn)).classes("text-sm font-bold") \
                                .style("min-width:100px; text-align:right")

    def _toggle_receipt(number: int) -> None:
        state["open_receipt"] = None if state["open_receipt"] == number else number
        render()

    # ---------- X-отчёт и выгрузка ----------

    def _show_x_report() -> None:
        with SessionLocal() as session:
            rep = rs.x_report(session)
        with ui.dialog() as dlg, ui.card().classes("gap-3").style("min-width:420px"):
            ui.label("X-отчёт").classes("text-xl font-black")
            if rep is None:
                ui.label("Смена не открыта — X-отчёт недоступен.").classes("text-base p-3") \
                    .style("color: var(--status-warning);"
                           "background: var(--status-warning-bg); border-radius:12px")
            else:
                from app.timezone import to_almaty
                ui.label(f"Смена №{rep.shift_id} · {rep.cashier_name} · "
                         f"с {to_almaty(rep.opened_at):%d.%m %H:%M}").classes("text-sm") \
                    .style("color: var(--text-secondary)")
                rows = [("Чеков", str(rep.orders_count), False),
                        ("Выручка", _tg(rep.revenue_tiyn), True)]
                rows += [(f"  {_METHOD_LABELS.get(m, m)}", _tg(a), False)
                         for m, a in rep.by_method.items()]
                if rep.refunds_tiyn:
                    rows.append(("Возвраты", f"−{_tg(rep.refunds_tiyn)}", False))
                rows.append(("Ожидается в кассе", _tg(rep.expected_cash_tiyn), True))
                for label, value, strong in rows:
                    with ui.row().classes("items-center gap-3 w-full px-3 rounded-xl") \
                            .style("min-height:44px; background: "
                                   + ("var(--coffee-50)" if strong else "var(--surface-sunken)")):
                        ui.label(label).classes("flex-1 text-sm") \
                            .style("color: var(--text-secondary)")
                        ui.label(value).classes(
                            "text-base " + ("font-black" if strong else "font-medium"))
                ui.label("Смена не закрывается — это промежуточная сводка.").classes("text-xs") \
                    .style("color: var(--text-secondary)")
            ui.button("Закрыть", on_click=dlg.close).props("outline no-caps").classes("w-full")
        dlg.open()

    def _download() -> None:
        period, error = period_or_error()
        if period is None:
            ui.notify(error, color="red")
            return
        with SessionLocal() as session:
            content = build_reports_workbook(
                period,
                rs.revenue_by_method(session, period),
                rs.top_products(session, period),
                rs.revenue_by_category(session, period),
                rs.cost_and_margin(session, period),
                rs.shifts_and_cashiers(session, period),
            )
        ui.download(content, f"Отчёт_{period.start:%Y%m%d}-{period.end:%Y%m%d}.xlsx")

    def _download_day(day: date) -> None:
        period = rs.period_from_dates(day, day)
        with SessionLocal() as session:
            content = build_reports_workbook(
                period,
                rs.revenue_by_method(session, period),
                rs.top_products(session, period),
                rs.revenue_by_category(session, period),
                rs.cost_and_margin(session, period),
                rs.shifts_and_cashiers(session, period),
            )
        ui.download(content, f"Отчёт_{day:%Y%m%d}.xlsx")

    # ---------- сборка экрана ----------

    def render() -> None:
        root.clear()
        period, error = period_or_error()
        with root:
            if state["day"] is not None:
                with SessionLocal() as session:
                    render_day(session, state["day"])
                return

            days: list[rs.DayRow] = []
            if period is not None:
                with SessionLocal() as session:
                    days = rs.revenue_by_day(session, period)
            render_header(days, error)

            if error:
                with ui.row().classes("items-center gap-2 w-full p-4 rounded-2xl") \
                        .style("background: var(--status-danger-bg); color: var(--status-danger)"):
                    ui.icon("error_outline", size="20px")
                    ui.label(error).classes("text-base")
                return

            with SessionLocal() as session:
                sm = rs.summary(session, period)
                if sm.orders_count == 0:
                    empty_state(icon="insights", title="Нет данных за период",
                                hint="За выбранные даты не было ни одного чека. "
                                     "Попробуйте другой период.")
                    return
                prev = rs.summary(session, rs.previous_period(period))
                render_kpis(sm, prev)
                if len(days) == 1:
                    hours = rs.revenue_by_hour(session, days[0].day)
                    render_chart("Выручка по часам",
                                 [(f"{h.hour:02d}", h.revenue_tiyn,
                                   f"{h.hour:02d}:00 — {_tg(h.revenue_tiyn)}", None)
                                  for h in hours], "")
                else:
                    render_chart("Выручка по дням",
                                 [(f"{d.day:%d.%m}", d.revenue_tiyn,
                                   f"{d.day:%d.%m} — {_tg(d.revenue_tiyn)} · открыть день",
                                   (lambda d=d: go_day(d.day)))
                                  for d in days],
                                 " · нажмите на столбец, чтобы открыть день")
                render_breakdowns(session, period, sm)
                render_top(session, period)
                render_shifts(session, period)

    render()
