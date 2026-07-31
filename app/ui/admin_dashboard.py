"""Дашборд владельца: что происходит на точке прямо сейчас.

Раскладка и состав блоков — из макета «Coffee POS» (claude.ai/design): шапка
с состоянием смены, строка предупреждений, шесть показателей, слева динамика
и чеки, справа деньги и остатки.

Всё считается за календарные сутки Алматы, а не за смену. Смена бывает открыта
со вчерашнего вечера, и «выручка смены» тогда не сошлась бы ни с одним отчётом
за день; сама смена показана отдельной строкой, и по ней же считается ящик —
наличные лежат именно в открытой смене.
"""
from datetime import date, timedelta

from nicegui import ui

from app.db import SessionLocal
from app.services import dashboard_service as ds
from app.services import reporting_service as rs
from app.ui.design import (PAYMENT_ICONS, PAYMENT_LABELS, category_icon, checks_word,
                           money_tg)
from app.ui.guard import require_admin
from app.ui.layout import admin_header

_CARD = ("background: var(--surface-card); border:1px solid var(--border-subtle);"
         "border-radius:16px")
_HOURS_HEIGHT = 150
_WEEK_HEIGHT = 110
# Пересобирается целиком, поэтому редко: снимок дашборда — это полтора десятка
# запросов, и на секундном таймере они заняли бы кассу больше, чем продажи.
_REFRESH_SECONDS = 15.0
_WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
# Родительный падеж множественного числа: «средняя выручка прошлых пятниц».
# Форма одна на любое количество дней, поэтому подпись не приходится согласовывать
# с числом — «за 3 прошлых пятница» иначе неизбежно.
_WEEKDAYS_GENITIVE = ("понедельников", "вторников", "сред", "четвергов", "пятниц",
                      "суббот", "воскресений")


def _short_tg(tiyn: int) -> str:
    """Сумма для подписи столбца: «96к», «1.2 млн» — целиком туда не влезает."""
    tenge = tiyn / 100
    if tenge >= 1_000_000:
        return f"{tenge / 1_000_000:.1f} млн"
    if tenge >= 1000:
        return f"{round(tenge / 1000)}к"
    return str(round(tenge))


def _elapsed(delta: timedelta) -> str:
    total_minutes = max(0, int(delta.total_seconds()) // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"


def _delta_parts(current: float, previous: float) -> tuple[str, str, str]:
    """Подпись «ко вчера»: текст, цвет, иконка.

    Порог в 2% — чтобы дрожание на пару процентов не красило плитку в красный
    и зелёный поочерёдно при каждом обновлении.
    """
    if not previous:
        return "нет данных за вчера", "var(--text-secondary)", "trending_flat"
    pct = round((current - previous) / previous * 100)
    if pct > 2:
        return f"+{pct}% ко вчера", "var(--status-success)", "trending_up"
    if pct < -2:
        return f"{pct}% ко вчера", "var(--status-danger)", "trending_down"
    if pct == 0:
        return "как вчера", "var(--text-secondary)", "trending_flat"
    return f"{pct:+d}% ко вчера", "var(--text-secondary)", "trending_flat"


def _card(gap: str = "gap-3"):
    return ui.column().classes(f"w-full {gap} p-4").style(_CARD)


def _card_title(text: str, right: str = "") -> None:
    with ui.row().classes("w-full items-baseline justify-between gap-3 flex-wrap"):
        ui.label(text).classes("text-lg font-bold")
        if right:
            ui.label(right).classes("text-sm").style("color: var(--text-secondary)")


def _muted(text: str) -> None:
    ui.label(text).classes("text-sm").style("color: var(--text-secondary)")


def _progress(pct: int, color: str, *, height: int = 8) -> None:
    with ui.element("div").classes("w-full rounded-full overflow-hidden") \
            .style(f"height:{height}px; background: var(--surface-sunken)"):
        ui.element("div").classes("h-full rounded-full") \
            .style(f"width:{max(0, min(100, pct))}%; background: {color}")


@ui.page("/admin/dashboard")
def admin_dashboard_page() -> None:
    if not require_admin():
        return
    admin_header()

    root = ui.column().classes("w-full gap-4 mx-auto").style("max-width:1180px")

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

    def open_day(day: date) -> None:
        ui.navigate.to(f"/admin/reports?day={day.isoformat()}")

    # ---------- шапка ----------

    def render_header(dash: ds.Dashboard) -> None:
        with ui.row().classes("w-full items-end justify-between gap-4 flex-wrap"):
            with ui.column().classes("gap-1"):
                ui.label("Дашборд").classes("text-2xl font-black leading-tight")
                with ui.row().classes("items-center gap-2 flex-wrap text-sm") \
                        .style("color: var(--text-secondary)"):
                    if dash.shift is not None:
                        ui.label("●").style("color: var(--status-success)")
                        ui.label(
                            f"Смена №{dash.shift.shift_id} открыта · "
                            f"{dash.shift.cashier_name} · "
                            f"с {dash.shift.opened_at:%H:%M} ({_elapsed(dash.shift.elapsed)})"
                        )
                    else:
                        ui.label("●").style("color: var(--text-muted)")
                        ui.label("Смена закрыта")
                    ui.label("·")
                    ui.label(f"{dash.day:%d.%m}, {_WEEKDAYS[dash.day.weekday()]}, "
                             f"данные на {dash.now:%H:%M}")
            with ui.row().classes("gap-2 flex-wrap"):
                ui.button("Отчёт за день", icon="receipt_long",
                          on_click=lambda d=dash.day: open_day(d)) \
                    .props("outline no-caps").classes("h-12")
                ui.button("Сделать бэкап", icon="backup", on_click=do_backup) \
                    .props("outline no-caps").classes("h-12")

    # ---------- предупреждения ----------

    def render_alerts(dash: ds.Dashboard) -> None:
        alerts: list[tuple[str, str, str]] = []  # (иконка, текст, статус)
        for s in [s for s in dash.stock if s.is_low][:4]:
            alerts.append(("inventory_2",
                           f"{s.name} — {s.stock_qty} из {s.threshold} {s.unit}", "warning"))
        if dash.refunded_orders_count:
            alerts.append(("undo",
                           f"{checks_word(dash.refunded_orders_count)} с возвратом "
                           f"на {money_tg(dash.today.refunds_tiyn)}", "danger"))
        if dash.plan is not None and not dash.plan.ahead:
            alerts.append(("trending_down",
                           f"План {dash.plan.done_pct}% — норма к этому часу "
                           f"{dash.plan.norm_pct}%", "warning"))
        if not alerts:
            return
        with ui.row().classes("w-full gap-2 flex-wrap"):
            for icon, text, kind in alerts:
                with ui.row().classes("items-center gap-2 rounded-full px-3") \
                        .style(f"min-height:40px; background: var(--status-{kind}-bg); "
                               f"color: var(--status-{kind})"):
                    ui.icon(icon, size="18px")
                    ui.label(text).classes("text-sm font-medium")

    # ---------- показатели ----------

    def render_kpis(dash: ds.Dashboard) -> None:
        today, yesterday = dash.today, dash.yesterday
        worked_hours = max(1, len([h for h in dash.hours if not h.is_future]))
        per_hour = (f"{today.orders_count / worked_hours:.1f} чек/час"
                    if today.orders_count else "продаж пока нет")
        in_check = (f"в среднем {today.items_count / today.orders_count:.1f} в чеке"
                    if today.orders_count else "—")
        margin_share = (f"{today.margin_pct:.1f}% от выручки"
                        if today.gross_tiyn else "—")

        tiles = [
            ("Выручка за день", money_tg(today.gross_tiyn),
             f"вчера к {dash.now:%H:%M} — {money_tg(yesterday.gross_tiyn)}",
             _delta_parts(today.gross_tiyn, yesterday.gross_tiyn)),
            ("Чеков", str(today.orders_count), per_hour,
             _delta_parts(today.orders_count, yesterday.orders_count)),
            ("Средний чек", money_tg(today.avg_check_tiyn),
             f"вчера — {money_tg(yesterday.avg_check_tiyn)}",
             _delta_parts(today.avg_check_tiyn, yesterday.avg_check_tiyn)),
            ("Позиций продано", str(today.items_count), in_check,
             _delta_parts(today.items_count, yesterday.items_count)),
            ("Маржа", money_tg(today.margin_tiyn),
             f"себестоимость {money_tg(today.cogs_tiyn)}",
             (margin_share, "var(--text-secondary)", "percent")),
            ("Возвраты", money_tg(today.refunds_tiyn),
             (f"{checks_word(dash.refunded_orders_count)} с возвратом"
              if dash.refunded_orders_count else "без возвратов"),
             (f"вчера — {money_tg(yesterday.refunds_tiyn)}",
              "var(--text-secondary)", "history")),
        ]
        with ui.grid().classes("w-full gap-3") \
                .style("grid-template-columns: repeat(auto-fit, minmax(210px, 1fr))"):
            for label, value, sub, (delta_text, delta_color, delta_icon) in tiles:
                with ui.column().classes("gap-1 p-4").style(_CARD):
                    _muted(label)
                    ui.label(value).classes("text-2xl font-black leading-tight")
                    with ui.row().classes("items-center gap-1 no-wrap") \
                            .style(f"color: {delta_color}"):
                        ui.icon(delta_icon, size="17px")
                        ui.label(delta_text).classes("text-xs font-bold truncate")
                    ui.label(sub).classes("text-xs truncate") \
                        .style("color: var(--text-muted)")

    # ---------- план на день ----------

    def render_plan(plan: ds.DayPlan, day: date, now_hour: int) -> None:
        color = "var(--status-success)" if plan.ahead else "var(--status-warning)"
        with _card("gap-2"):
            _card_title("План на день",
                        f"{money_tg(plan.revenue_tiyn)} из {money_tg(plan.target_tiyn)}")
            _progress(plan.done_pct, color, height=14)
            with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
                ui.label(
                    f"{'Идём с опережением' if plan.ahead else 'Отстаём'}: "
                    f"{plan.done_pct}% плана при норме {plan.norm_pct}% к {now_hour:02d}:00"
                ).classes("text-sm font-bold").style(f"color: {color}")
                _muted(f"Осталось {money_tg(plan.left_tiyn)}")
            ui.label(
                f"Ориентир — средняя выручка прошлых {_WEEKDAYS_GENITIVE[day.weekday()]} "
                f"(учтено дней: {plan.basis_days})"
            ).classes("text-xs").style("color: var(--text-muted)")

    # ---------- выручка по часам ----------

    def render_hours(dash: ds.Dashboard) -> None:
        peak_value = dash.peak.today_tiyn if dash.peak else 0
        scale = max([h.today_tiyn for h in dash.hours]
                    + [h.yesterday_tiyn for h in dash.hours] + [1])
        with _card():
            with ui.row().classes("w-full items-baseline justify-between gap-3 flex-wrap"):
                ui.label("Выручка по часам").classes("text-lg font-bold")
                with ui.row().classes("items-center gap-3 text-xs") \
                        .style("color: var(--text-secondary)"):
                    for label, color in (("сегодня", "var(--coffee-500)"),
                                         ("вчера", "var(--coffee-200)")):
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.element("div").style(
                                f"width:10px;height:10px;border-radius:3px;background:{color}")
                            ui.label(label)
            with ui.row().classes("w-full items-end gap-1 no-wrap") \
                    .style(f"height:{_HOURS_HEIGHT + 20}px"):
                for h in dash.hours:
                    _hour_bar(h, scale, is_peak=peak_value > 0 and h.today_tiyn == peak_value)
            with ui.row().classes("w-full gap-5 flex-wrap text-sm pt-2") \
                    .style("border-top:1px solid var(--border-subtle);"
                           "color: var(--text-secondary)"):
                peak_text = (f"{dash.peak.hour:02d}:00 · {money_tg(dash.peak.today_tiyn)}"
                             if dash.peak else "—")
                ui.label(f"Пик: {peak_text}")
                last = f"{dash.last_receipt_at:%H:%M}" if dash.last_receipt_at else "—"
                ui.label(f"Последний чек: {last}")

    def _hour_bar(h: ds.HourBar, scale: int, *, is_peak: bool) -> None:
        if h.is_future:
            today_color = "var(--border-subtle)"
        elif is_peak:
            today_color = "var(--brand-primary)"
        else:
            today_color = "var(--coffee-500)"
        with ui.column().classes("flex-1 min-w-0 items-center justify-end gap-1 h-full"):
            with ui.row().classes("w-full items-end justify-center gap-1 flex-1 no-wrap"):
                for value, color, width in ((h.today_tiyn, today_color, "44%"),
                                            (h.yesterday_tiyn, "var(--coffee-200)", "30%")):
                    bar = ui.element("div").style(
                        f"width:{width};background:{color};border-radius:5px 5px 0 0;"
                        f"height:{max(2, round(value / scale * _HOURS_HEIGHT))}px")
                    bar.tooltip(f"{h.hour:02d}:00 — {money_tg(h.today_tiyn)} "
                                f"(вчера {money_tg(h.yesterday_tiyn)})")
            ui.label(f"{h.hour:02d}").classes("text-xs") \
                .style("color: var(--text-" + ("muted" if h.is_future else "secondary") + ")")

    # ---------- топ товаров ----------

    def render_top(dash: ds.Dashboard) -> None:
        with _card():
            _card_title("Топ товаров за день")
            if not dash.top:
                _muted("Продаж пока нет")
                return
            best = dash.top[0].revenue_tiyn or 1
            for i, p in enumerate(dash.top, start=1):
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    ui.label(str(i)).classes("text-sm font-bold") \
                        .style("color: var(--text-muted); width:20px")
                    with ui.column().classes("flex-1 min-w-0 gap-1"):
                        with ui.row().classes("items-baseline gap-2 no-wrap"):
                            ui.label(p.name).classes("text-base font-bold truncate")
                            ui.label(f"{p.category} · {p.qty} шт").classes("text-xs truncate") \
                                .style("color: var(--text-secondary)")
                        _progress(round(p.revenue_tiyn / best * 100),
                                  "var(--brand-accent)", height=7)
                    ui.label(money_tg(p.revenue_tiyn)).classes("text-base font-bold text-right") \
                        .style("width:92px")

    # ---------- последние чеки ----------

    def render_recent(dash: ds.Dashboard) -> None:
        with _card("gap-2"):
            with ui.row().classes("w-full items-baseline justify-between gap-3 flex-wrap"):
                ui.label("Последние чеки").classes("text-lg font-bold")
                ui.button("Все чеки за день", on_click=lambda d=dash.day: open_day(d)) \
                    .props("flat no-caps").classes("h-10 px-3 rounded-full cp-pill-idle")
            if not dash.recent:
                _muted("Сегодня чеков ещё не было")
                return
            for r in dash.recent:
                _receipt_row(r, dash.day)

    def _receipt_row(r: rs.Receipt, day: date) -> None:
        row = ui.row().classes("w-full items-center gap-3 no-wrap rounded-xl px-2 cp-hover") \
            .style("min-height:52px; cursor:pointer")
        row.on("click", lambda d=day: open_day(d))
        with row:
            ui.label(f"{r.at:%H:%M}").classes("text-sm") \
                .style("color: var(--text-secondary); width:48px")
            ui.icon(PAYMENT_ICONS.get(r.method, "payments"), size="19px") \
                .style("color: var(--text-secondary)")
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.label(f"№{r.number}").classes("text-base font-bold")
                    if r.refunded_tiyn:
                        ui.badge("возврат").props("rounded") \
                            .style("background: var(--status-danger-bg); "
                                   "color: var(--status-danger)")
                ui.label(", ".join(f"{line.name} ×{line.qty}" for line in r.lines)) \
                    .classes("text-xs truncate").style("color: var(--text-secondary)")
            ui.label(money_tg(r.total_tiyn)).classes("text-base font-bold text-right")

    # ---------- касса ----------

    def render_cash(dash: ds.Dashboard) -> None:
        with _card("gap-2"):
            ui.label("Касса").classes("text-lg font-bold")
            if dash.cash is None:
                _muted("Смена закрыта — ящик не считается")
                return
            _muted("Ожидается в ящике")
            ui.label(money_tg(dash.cash.expected_tiyn)).classes("text-2xl font-black leading-tight")
            with ui.column().classes("w-full gap-2 pt-2") \
                    .style("border-top:1px solid var(--border-subtle)"):
                rows = [("Разменные на открытии", dash.cash.opening_tiyn),
                        ("Принято наличными", dash.cash.cash_sales_tiyn),
                        ("Возвраты наличными", dash.cash.cash_refunds_tiyn)]
                if dash.cash.collections_tiyn:
                    rows.insert(2, ("Инкассации", dash.cash.collections_tiyn))
                for label, amount in rows:
                    with ui.row().classes("w-full items-center justify-between gap-3 no-wrap"):
                        ui.label(label).classes("text-sm truncate") \
                            .style("color: var(--text-secondary)")
                        ui.label(money_tg(amount)).classes("text-sm font-bold")
            _muted(f"{dash.cash_share_pct}% выручки наличными"
                   if dash.today.gross_tiyn else "Продаж пока нет")

    # ---------- способы оплаты ----------

    def render_methods(dash: ds.Dashboard) -> None:
        with _card():
            _card_title("Способы оплаты")
            if not dash.methods:
                _muted("Оплат сегодня ещё не было")
                return
            best = dash.methods[0].amount_tiyn or 1
            total = sum(m.amount_tiyn for m in dash.methods) or 1
            for m in dash.methods:
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.icon(PAYMENT_ICONS.get(m.method, "payments"), size="19px") \
                            .style("color: var(--brand-primary)")
                        ui.label(PAYMENT_LABELS.get(m.method, m.method)) \
                            .classes("flex-1 min-w-0 text-base truncate")
                        ui.label(money_tg(m.amount_tiyn)).classes("text-base font-bold")
                    _progress(round(m.amount_tiyn / best * 100), "var(--brand-primary)", height=7)
                    ui.label(f"{round(m.amount_tiyn / total * 100)}% · "
                             f"{checks_word(m.orders_count)}").classes("text-xs") \
                        .style("color: var(--text-secondary)")

    # ---------- остатки ----------

    def render_stock(dash: ds.Dashboard) -> None:
        with _card():
            with ui.row().classes("w-full items-baseline justify-between gap-3"):
                ui.label("Остатки").classes("text-lg font-bold")
                ui.button("Приход", on_click=lambda: ui.navigate.to("/stock/purchase")) \
                    .props("flat no-caps").classes("h-10 px-3 rounded-full cp-pill-idle")
            if not dash.stock:
                _muted("Пороги остатков не заданы — следить не за чем")
                return
            for s in dash.stock:
                if not s.is_low:
                    color, note, note_color = ("var(--status-success)", "в норме",
                                               "var(--text-secondary)")
                elif s.pct < 50:
                    color = note_color = "var(--status-danger)"
                    note = "ниже порога"
                else:
                    color = note_color = "var(--status-warning)"
                    note = "ниже порога"
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("w-full items-baseline gap-2 no-wrap"):
                        ui.label(s.name).classes("flex-1 min-w-0 text-base truncate")
                        ui.label(f"{s.stock_qty} / {s.threshold} {s.unit}") \
                            .classes("text-sm font-bold")
                    _progress(s.pct, color, height=7)
                    ui.label(note).classes("text-xs").style(f"color: {note_color}")

    # ---------- последние 7 дней ----------

    def render_week(dash: ds.Dashboard) -> None:
        scale = max([d.revenue_tiyn for d in dash.week] + [1])
        with _card():
            _card_title("Последние 7 дней")
            with ui.row().classes("w-full items-end gap-1 no-wrap") \
                    .style(f"height:{_WEEK_HEIGHT + 34}px"):
                for d in dash.week:
                    _week_bar(d, scale, is_today=d.day == dash.day)
            ui.label("Нажмите на столбец, чтобы открыть отчёт за день").classes("text-xs") \
                .style("color: var(--text-muted)")

    def _week_bar(d: rs.DayRow, scale: int, *, is_today: bool) -> None:
        col = ui.column().classes("flex-1 min-w-0 items-center justify-end gap-1 h-full") \
            .style("cursor:pointer")
        col.on("click", lambda day=d.day: open_day(day))
        weight = "font-bold" if is_today else ""
        with col:
            ui.label(_short_tg(d.revenue_tiyn)).classes(f"text-xs {weight}") \
                .style("color: var(--text-secondary)")
            bar = ui.element("div").classes("w-full").style(
                f"height:{max(3, round(d.revenue_tiyn / scale * _WEEK_HEIGHT))}px;"
                f"border-radius:6px 6px 0 0;"
                f"background: var(--{'brand-primary' if is_today else 'coffee-400'})")
            bar.tooltip(f"{d.day:%d.%m} — {money_tg(d.revenue_tiyn)} · "
                        f"{checks_word(d.orders_count)}")
            ui.label(_WEEKDAYS_SHORT[d.day.weekday()]).classes(f"text-xs {weight}") \
                .style("color: var(--text-secondary)")

    # ---------- сборка ----------

    def refresh() -> None:
        with SessionLocal() as session:
            dash = ds.dashboard(session)
        root.clear()
        with root:
            render_header(dash)
            render_alerts(dash)
            render_kpis(dash)
            # Две колонки на широком экране, друг под другом на узком: flex-basis
            # решает это без медиазапросов, которые в inline-стиле не написать.
            with ui.row().classes("w-full items-start gap-4 flex-wrap"):
                with ui.column().classes("gap-4 min-w-0").style("flex:1.55 1 560px"):
                    if dash.plan is not None:
                        render_plan(dash.plan, dash.day, dash.now.hour)
                    render_hours(dash)
                    render_top(dash)
                    render_recent(dash)
                with ui.column().classes("gap-4 min-w-0").style("flex:1 1 320px"):
                    render_cash(dash)
                    render_methods(dash)
                    render_stock(dash)
                    render_week(dash)

    refresh()
    ui.timer(_REFRESH_SECONDS, refresh)
