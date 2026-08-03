"""Экран «Сервер и обслуживание»: состояние кассы, её скорость и починка.

То же, что показывает deploy/status.ps1, но из браузера. Раньше ответ на вопрос
«всё ли в порядке с кассой?» получал только тот, кто стоит перед моноблоком;
владелец бывает в кофейне не каждый день, а касса доступна снаружи через Funnel.

Всё, что дольше пары десятков миллисекунд, уходит в поток через asyncio.to_thread:
у NiceGUI один event loop на всё приложение, и замер диска, выполненный прямо в
обработчике, заморозил бы экран кассира посреди продажи.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from nicegui import ui

from app.db import SessionLocal
from app.services import maintenance_service as maint
from app.services import perf_service as perf
from app.services import runtime, shift_service, updater
from app.services import system_service as sysinfo
from app.ui.design import confirm_with_pin
from app.ui.guard import require_admin
from app.ui.layout import admin_header
from app.timezone import to_almaty

_CARD = ("background: var(--surface-card); border:1px solid var(--border-subtle);"
         "border-radius:16px")

_VERDICT_COLOR = {"ok": "var(--status-success)", "warn": "var(--status-warning)",
                  "bad": "var(--status-danger)"}
_VERDICT_BG = {"ok": "var(--status-success-bg)", "warn": "var(--status-warning-bg)",
               "bad": "var(--status-danger-bg)"}
_VERDICT_ICON = {"ok": "check_circle", "warn": "warning", "bad": "error"}
_VERDICT_TITLE = {"ok": "Касса в порядке", "warn": "Стоит заглянуть",
                  "bad": "Требует внимания"}

# Сколько строк журнала показываем. Больше на экране всё равно не прочитать,
# а каждая строка — это элемент в браузере моноблока.
_LOG_LINES = 120

_REFRESH_SECONDS = 30.0


def verdict_color(verdict: str) -> str:
    return _VERDICT_COLOR.get(verdict, "var(--text-secondary)")


def verdict_bg(verdict: str) -> str:
    return _VERDICT_BG.get(verdict, "var(--surface-sunken)")


def format_bytes(value: int) -> str:
    """«4,0 МБ» — с запятой, как принято в русских числах."""
    for unit, size in (("ГБ", 1024 ** 3), ("МБ", 1024 ** 2), ("КБ", 1024)):
        if value >= size:
            return f"{value / size:.1f} {unit}".replace(".", ",")
    return f"{value} Б"


def format_uptime(seconds: float | None) -> str:
    """«3 сут 4 ч», «5 ч 12 мин», «7 мин» — секунды владельцу ни о чём не говорят."""
    if seconds is None:
        return "—"
    days, rest = divmod(int(max(seconds, 0)), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} сут {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def format_measure(value: float, unit: str) -> str:
    """Значение замера: крупные числа целыми, мелкие — с одним знаком.

    Процент пишется вплотную к числу, остальные единицы — через пробел:
    «95,0 %» читается как опечатка, а «102 ГБ» без пробела — как одно слово.
    """
    number = f"{value:.0f}" if value >= 100 else f"{value:.1f}".replace(".", ",")
    if unit == "%":
        return f"{number}%"
    return f"{number} {unit}".strip()


@dataclass(frozen=True)
class Snapshot:
    """Всё состояние, собранное за один заход в базу и файловую систему."""

    app: sysinfo.AppInfo
    resources: sysinfo.Resources
    database: sysinfo.DatabaseInfo
    backups: sysinfo.BackupsInfo
    log: sysinfo.LogInfo
    tasks: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    verdict: str = "ok"
    shift_open: bool = False


def collect(*, errors_only: bool = False) -> Snapshot:
    """Снимок состояния. Синхронный и с походом в базу — звать через to_thread."""
    app = sysinfo.app_info()
    res = sysinfo.resources()
    backups = sysinfo.backups_info()
    log = sysinfo.log_tail(limit=_LOG_LINES, errors_only=errors_only)
    tasks = runtime.task_states()
    with SessionLocal() as session:
        database = sysinfo.database_info(session)
        shift_open = shift_service.current_open_shift(session) is not None
    found = sysinfo.issues(app, res, database, backups, tasks, log=log)
    return Snapshot(app=app, resources=res, database=database, backups=backups,
                    log=log, tasks=tasks, issues=found,
                    verdict=sysinfo.overall_verdict(found), shift_open=shift_open)


@ui.page("/admin/system")
def admin_system_page() -> None:
    if not require_admin():
        return
    admin_header()

    state = {
        "snapshot": None,       # Snapshot — пока None, показываем ожидание
        "perf": None,           # последний отчёт о производительности
        "perf_running": False,
        "errors_only": False,   # фильтр журнала
        "busy": "",             # название идущей операции обслуживания
        "result": None,         # MaintenanceResult последней операции
    }

    root = ui.column().classes("w-full gap-4 mx-auto").style("max-width:1100px")

    # ---------- загрузка и перерисовка ----------

    async def reload() -> None:
        state["snapshot"] = await asyncio.to_thread(collect, errors_only=state["errors_only"])
        render()

    async def tick() -> None:
        """Автообновление. Молчит, пока идёт операция, чтобы не стереть её результат."""
        if state["busy"] or state["perf_running"]:
            return
        await reload()

    async def run_maintenance(operation, *, title: str) -> None:
        state["busy"] = title
        render()
        try:
            result = await asyncio.to_thread(operation)
        finally:
            state["busy"] = ""
        state["result"] = result
        ui.notify(result.message, color="green" if result.ok else "red")
        await reload()

    async def run_perf(*, quick: bool = False) -> None:
        state["perf_running"] = True
        render()
        try:
            state["perf"] = await perf.run_performance_check_async(quick=quick)
        finally:
            state["perf_running"] = False
        render()

    # ---------- разделы ----------

    def render_header(snap: Snapshot) -> None:
        with ui.row().classes("w-full items-end justify-between gap-4 flex-wrap"):
            with ui.column().classes("gap-0"):
                ui.label("Сервер и обслуживание").classes("text-2xl font-black leading-tight")
                ui.label(f"Версия {snap.app.version or 'неизвестна'} · "
                         f"работает {format_uptime(snap.app.uptime_seconds)}") \
                    .classes("text-sm").style("color: var(--text-secondary)")
            ui.button("Обновить", icon="refresh", on_click=reload).props("outline no-caps")

    def render_verdict(snap: Snapshot) -> None:
        color = verdict_color(snap.verdict)
        with ui.column().classes("w-full gap-2 p-4 rounded-2xl") \
                .style(f"background: {verdict_bg(snap.verdict)}"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon(_VERDICT_ICON[snap.verdict], size="24px").style(f"color: {color}")
                ui.label(_VERDICT_TITLE[snap.verdict]).classes("text-lg font-bold") \
                    .style(f"color: {color}")
            if not snap.issues:
                ui.label("Место на диске, копии базы и фоновые задачи — всё в норме.") \
                    .classes("text-sm")
            for issue in snap.issues:
                with ui.column().classes("gap-0"):
                    ui.label(issue.text).classes("text-sm font-semibold")
                    ui.label(issue.hint).classes("text-sm") \
                        .style("color: var(--text-secondary)")

    def render_server(snap: Snapshot) -> None:
        app = snap.app
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            ui.label("Сервер").classes("text-lg font-bold")
            with ui.grid().classes("w-full gap-3") \
                    .style("grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))"):
                _fact("Время работы", format_uptime(app.uptime_seconds))
                _fact("Версия кассы", app.version or "неизвестна")
                _fact("Адрес снаружи", app.public_url)
                _fact("Номер процесса", str(app.pid))
                _fact("Python", app.python)
                _fact("Система", app.platform)
            if app.supervised:
                _note("check_circle", "var(--status-success)",
                      "Автоперезапуск включён: если касса упадёт, скрипт поднимет её сам.")
            else:
                _note("warning", "var(--status-warning)",
                      "Сервер запущен в обход start.ps1 — после остановки он сам не "
                      "поднимется, и кнопка перезапуска ниже недоступна.")

    def render_resources(snap: Snapshot) -> None:
        res = snap.resources
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            ui.label("Загрузка моноблока").classes("text-lg font-bold")
            if res.cpu_percent is not None:
                _gauge("Процессор", f"{res.cpu_percent:.0f}%", res.cpu_percent)
            if res.ram_used_percent is not None:
                right = (f"{res.ram_process_mb:.0f} МБ у кассы"
                         if res.ram_process_mb is not None else "")
                _gauge("Память", f"{res.ram_used_percent:.0f}%", res.ram_used_percent,
                       right=right)
            if res.disk_used_percent is not None:
                _gauge("Диск", f"{res.disk_free_gb:.0f} ГБ свободно",
                       res.disk_used_percent,
                       right=f"из {res.disk_total_gb:.0f} ГБ")
            if res.source == "stdlib":
                _note("info", "var(--text-secondary)",
                      "Загрузка процессора здесь не показывается: её умеет считать "
                      "библиотека psutil, она появится после следующего обновления кассы.")

    def render_tasks(snap: Snapshot) -> None:
        with ui.column().classes("w-full gap-2 p-4").style(_CARD):
            ui.label("Фоновые задачи").classes("text-lg font-bold")
            for task in snap.tasks:
                if task.error:
                    icon, color, status = "error", "var(--status-danger)", "остановилась"
                elif task.running:
                    icon, color, status = "check_circle", "var(--status-success)", "работает"
                else:
                    icon, color, status = "pause_circle", "var(--text-muted)", "выключена"
                with ui.row().classes("items-center gap-3 w-full no-wrap p-2 rounded-xl") \
                        .style("background: var(--surface-sunken)"):
                    ui.icon(icon, size="20px").style(f"color: {color}")
                    ui.label(task.name).classes("flex-1 text-base truncate")
                    ui.label(status).classes("text-sm").style(f"color: {color}")
                if task.error:
                    ui.label(task.error).classes("text-xs px-2") \
                        .style("color: var(--status-danger)")
            if not snap.tasks:
                ui.label("Задачи ещё не зарегистрированы — сервер только запустился.") \
                    .classes("text-sm").style("color: var(--text-secondary)")

    def render_database(snap: Snapshot) -> None:
        db = snap.database
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            ui.label("База данных").classes("text-lg font-bold")
            with ui.grid().classes("w-full gap-3") \
                    .style("grid-template-columns: repeat(auto-fit, minmax(190px, 1fr))"):
                _fact("Размер базы", format_bytes(db.size_bytes))
                _fact("Журнал изменений", format_bytes(db.wal_bytes),
                      danger=db.wal_bytes > db.size_bytes * 10 and db.wal_bytes > 8 * 1024 ** 2)
                _fact("Пустое место внутри", format_bytes(db.wasted_bytes))
                _fact("Период данных", _period(db))
            with ui.grid().classes("w-full gap-2") \
                    .style("grid-template-columns: repeat(auto-fit, minmax(210px, 1fr))"):
                for row in db.tables:
                    with ui.row().classes("items-center gap-2 w-full no-wrap px-3 rounded-xl") \
                            .style("min-height:40px; background: var(--surface-sunken)"):
                        ui.label(row.name).classes("flex-1 text-sm truncate") \
                            .style("color: var(--text-secondary)")
                        ui.label(f"{row.rows:,}".replace(",", " ")).classes("text-sm font-bold")

            ui.label("Обслуживание").classes("text-sm font-bold mt-1")
            ui.label("Всё перечисленное безопасно и не меняет продажи: операции наводят "
                     "порядок в файле базы.").classes("text-xs") \
                .style("color: var(--text-secondary)")
            with ui.row().classes("gap-2 flex-wrap"):
                _maint_button("Перенести журнал в базу", "compress",
                              maint.wal_checkpoint, "Контрольная точка WAL")
                _maint_button("Проверить целостность", "verified",
                              maint.integrity_check, "Проверка целостности")
                _maint_button("Обновить статистику", "speed",
                              maint.analyze, "Обновление статистики")
                _vacuum_button(snap)
            _maint_result()

    def _vacuum_button(snap: Snapshot) -> None:
        """Сжатие базы — под PIN: операция переписывает файл целиком."""
        def ask() -> None:
            confirm_with_pin(
                title="Сжать базу",
                question="База будет перестроена, освободится место на диске. "
                         "Продажи не пострадают. Введите PIN администратора.",
                action_label="Сжать",
                on_confirm=lambda: run_maintenance(maint.vacuum, title="Сжатие базы"),
            )

        button = ui.button("Сжать базу", icon="cleaning_services", on_click=ask) \
            .props("outline no-caps")
        if state["busy"]:
            button.disable()
        elif snap.shift_open:
            button.disable()
            button.tooltip("Идёт смена: сжатие ненадолго блокирует базу, "
                           "и чек может не провестись. Сделайте после закрытия смены.")

    def _maint_button(label: str, icon: str, operation, title: str) -> None:
        button = ui.button(label, icon=icon,
                           on_click=lambda: run_maintenance(operation, title=title)) \
            .props("outline no-caps")
        if state["busy"]:
            button.disable()

    def _maint_result() -> None:
        if state["busy"]:
            with ui.row().classes("items-center gap-2"):
                ui.spinner(size="1.2rem")
                ui.label(f"{state['busy']}…").classes("text-sm")
            return
        result = state["result"]
        if result is None:
            return
        color = "var(--status-success)" if result.ok else "var(--status-danger)"
        with ui.column().classes("w-full gap-0 p-3 rounded-xl") \
                .style(f"background: {verdict_bg('ok' if result.ok else 'bad')}"):
            ui.label(f"{result.title}: {result.message}").classes("text-sm font-semibold") \
                .style(f"color: {color}")
            if result.detail:
                ui.label(result.detail).classes("text-xs") \
                    .style("color: var(--text-secondary); white-space: pre-line")

    def render_backups(snap: Snapshot) -> None:
        b = snap.backups
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            ui.label("Резервные копии").classes("text-lg font-bold")
            with ui.grid().classes("w-full gap-3") \
                    .style("grid-template-columns: repeat(auto-fit, minmax(190px, 1fr))"):
                _fact("Последняя копия",
                      f"{to_almaty(b.latest_at):%d.%m %H:%M}" if b.latest_at else "нет",
                      danger=b.stale)
                _fact("Всего копий", str(b.count))
                _fact("Занимают", format_bytes(b.total_bytes))
            with ui.row().classes("gap-2 flex-wrap"):
                ui.button("Сделать копию сейчас", icon="backup",
                          on_click=_do_backup).props("no-caps")
                ui.button("Восстановить из копии", icon="restore",
                          on_click=_restore_dialog).props("outline no-caps")
                _maint_button("Убрать старые копии", "delete_sweep",
                              maint.cleanup_backups, "Чистка копий базы")
            ui.label("Ручные копии (pos-before-*.db) чистка не трогает: их делают перед "
                     "обновлением, и именно к ним возвращаются, если что-то пошло не так.") \
                .classes("text-xs").style("color: var(--text-secondary)")

    def _restore_dialog() -> None:
        """Разворачивает копию поверх рабочей базы — из папки backups или из файла.

        Копию сначала показываем: сколько в ней чеков и товаров, за какое число.
        Подменить базу вслепую — самый быстрый способ потерять день работы.
        """
        from app.config import settings
        from app.services import backup_service as bs

        chosen: dict[str, object] = {"path": None, "check": None}

        with ui.dialog().props("persistent") as dlg, \
                ui.card().classes("gap-3 w-full").style("max-width:560px"):
            ui.label("Восстановление из копии").classes("text-lg font-bold")
            ui.label("База будет заменена целиком. Перед подменой снимается копия "
                     "текущей базы, и касса перезапустится.").classes("text-sm") \
                .style("color: var(--text-secondary)")

            local = sorted(Path(settings.backups_dir).glob("pos-*.db"),
                           key=lambda f: f.stat().st_mtime, reverse=True) \
                if Path(settings.backups_dir).exists() else []
            if local:
                options = {
                    str(f): f"{f.name} · "
                            f"{datetime.fromtimestamp(f.stat().st_mtime):%d.%m %H:%M} · "
                            f"{format_bytes(f.stat().st_size)}"
                    for f in local[:20]
                }
                picker = ui.select(options, label="Копия из папки backups") \
                    .props("outlined dense").classes("w-full")
                picker.on_value_change(lambda e: _pick(Path(e.value)) if e.value else None)

            ui.label("…или загрузите файл .db, присланный ботом в Telegram") \
                .classes("text-sm").style("color: var(--text-secondary)")
            ui.upload(
                label="Выбрать файл копии", auto_upload=True,
                max_file_size=300 * 1024 * 1024,
                on_upload=lambda e: _uploaded(e),
            ).props("accept=.db flat bordered").classes("w-full")

            info = ui.column().classes("w-full gap-1")
            actions = ui.row().classes("gap-2 w-full justify-end")

            def _pick(path: Path) -> None:
                check = bs.inspect_backup(path)
                chosen.update(path=path, check=check)
                _render_check()

            def _uploaded(event) -> None:
                target = Path(settings.backups_dir) / "restore-upload.db"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(event.content.read())
                ui.notify(f"Файл получен: {event.name}", color="green")
                _pick(target)

            def _render_check() -> None:
                info.clear()
                check = chosen["check"]
                actions.clear()
                with actions:
                    ui.button("Отмена", on_click=dlg.close).props("flat no-caps")
                    if check is not None and check.ok:
                        ui.button("Восстановить", icon="restore", color="negative",
                                  on_click=_confirm).props("no-caps")
                if check is None:
                    return
                with info:
                    if check.problems:
                        for problem in check.problems:
                            ui.label(f"• {problem}").classes("text-sm") \
                                .style("color: var(--status-danger)")
                        return
                    with ui.row().classes("w-full gap-4 flex-wrap p-3 rounded-xl") \
                            .style("background: var(--surface-sunken)"):
                        for label, value in check.counts:
                            with ui.column().classes("gap-0"):
                                ui.label(label).classes("text-xs") \
                                    .style("color: var(--text-secondary)")
                                ui.label(str(value)).classes("text-base font-bold")
                    stamp = (f"{check.created_at:%d.%m.%Y %H:%M}"
                             if check.created_at else "дата неизвестна")
                    ui.label(f"{stamp} · {format_bytes(check.size_bytes)}") \
                        .classes("text-xs").style("color: var(--text-secondary)")

            def _confirm() -> None:
                path = chosen["path"]
                if path is None:
                    return
                dlg.close()
                confirm_with_pin(
                    title="Замена базы",
                    question="Текущая база будет заменена копией, касса перезапустится.",
                    action_label="Заменить базу",
                    on_confirm=lambda: _do_restore(Path(str(path))),
                )

            _render_check()
        dlg.open()

    def _do_restore(path: Path) -> None:
        from app.services import backup_service as bs

        result = bs.restore_from_file(path)
        if not result.ok:
            ui.notify(result.message, color="red", multi_line=True, timeout=10000)
            return
        ui.notify(result.message + " Касса перезапускается…", color="green",
                  multi_line=True, timeout=8000)
        if updater.is_supervised():
            updater.schedule_restart()
        else:
            ui.notify("Перезапустите кассу вручную, чтобы она открыла новую базу.",
                      color="orange", multi_line=True, timeout=10000)

    async def _do_backup() -> None:
        from app.services.backup_service import run_backup_once

        state["busy"] = "Делаю копию базы"
        render()
        try:
            result = await run_backup_once()
        finally:
            state["busy"] = ""
        if result.error:
            ui.notify(f"Копия {result.path.name} готова, но: {result.error}", color="orange")
        else:
            ui.notify(f"Копия готова: {result.path.name} "
                      f"({format_bytes(result.size_bytes)}), "
                      f"в Telegram отправлено: {result.delivered_count}", color="green")
        await reload()

    def render_perf() -> None:
        report = state["perf"]
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
                with ui.column().classes("gap-0"):
                    ui.label("Скорость работы").classes("text-lg font-bold")
                    ui.label("Проверка занимает несколько секунд и ничего не меняет "
                             "в продажах.").classes("text-xs") \
                        .style("color: var(--text-secondary)")
                button = ui.button("Проверить", icon="timer",
                                   on_click=lambda: run_perf()).props("no-caps")
                if state["perf_running"]:
                    button.disable()

            if state["perf_running"]:
                with ui.row().classes("items-center gap-2"):
                    ui.spinner(size="1.2rem")
                    ui.label("Меряю отклик базы, отчёты и диск…").classes("text-sm")
                return
            if report is None:
                ui.label("Проверка ещё не запускалась.").classes("text-sm") \
                    .style("color: var(--text-secondary)")
                return

            # Запятую подставляем только в длительность: replace по всей строке
            # съел бы точку в дате и превратил «29.07» в «29,07».
            took = f"{report.took_ms / 1000:.1f}".replace(".", ",")
            ui.label(f"Проверено {to_almaty(report.at):%d.%m в %H:%M} · заняло {took} с") \
                .classes("text-xs").style("color: var(--text-secondary)")
            for check in report.checks:
                _perf_row(check)

    def _perf_row(check) -> None:
        color = verdict_color(check.verdict)
        with ui.column().classes("w-full gap-0 p-3 rounded-xl") \
                .style("background: var(--surface-sunken)"):
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                ui.icon(_VERDICT_ICON[check.verdict], size="18px").style(f"color: {color}")
                ui.label(check.name).classes("flex-1 text-base truncate")
                ui.label(format_measure(check.value, check.unit)) \
                    .classes("text-base font-bold").style(f"color: {color}")
            if check.detail:
                ui.label(check.detail).classes("text-xs pl-7") \
                    .style("color: var(--text-secondary)")
            if check.hint:
                ui.label(check.hint).classes("text-sm pl-7").style(f"color: {color}")

    def render_log(snap: Snapshot) -> None:
        log = snap.log
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
                with ui.column().classes("gap-0"):
                    ui.label("Журнал сервера").classes("text-lg font-bold")
                    ui.label(f"{format_bytes(log.size_bytes)} · "
                             f"ошибок в последних {log.scanned_lines} строках: "
                             f"{log.error_lines}") \
                        .classes("text-xs").style("color: var(--text-secondary)")
                with ui.row().classes("gap-2 flex-wrap"):
                    ui.switch("Только ошибки", value=state["errors_only"],
                              on_change=_toggle_errors).props("dense")
                    ui.button("Скачать", icon="download", on_click=_download_log) \
                        .props("outline no-caps")
                    _maint_button("Архивировать", "archive",
                                  maint.archive_log, "Архивирование журнала")
            if not log.lines:
                ui.label("Записей нет." if log.size_bytes
                         else "Журнала нет — сервер ни разу не запускался через start.ps1.") \
                    .classes("text-sm").style("color: var(--text-secondary)")
                return
            with ui.element("div").classes("w-full rounded-xl p-3") \
                    .style("background: var(--surface-sunken); max-height:320px;"
                           "overflow:auto; font-family: ui-monospace, monospace;"
                           "font-size:12px; line-height:1.5; white-space:pre"):
                for line in log.lines:
                    ui.label(line).classes("whitespace-pre")

    async def _toggle_errors(event) -> None:
        state["errors_only"] = bool(event.value)
        await reload()

    async def _download_log() -> None:
        snap = state["snapshot"]
        if snap is None:
            return
        path = Path(snap.log.path)
        try:
            content = await asyncio.to_thread(path.read_bytes)
        except OSError:
            ui.notify("Журнал не читается — возможно, его сейчас переписывает сервер.",
                      color="red")
            return
        ui.download(content, "server.log")

    def render_control(snap: Snapshot) -> None:
        with ui.column().classes("w-full gap-3 p-4").style(_CARD):
            ui.label("Управление").classes("text-lg font-bold")
            with ui.row().classes("gap-2 flex-wrap"):
                _restart_button(snap)
                ui.button("Версия и обновление", icon="system_update",
                          on_click=lambda: ui.navigate.to("/admin/about")) \
                    .props("outline no-caps")

    def _restart_button(snap: Snapshot) -> None:
        def ask() -> None:
            confirm_with_pin(
                title="Перезапустить кассу",
                question="Сервер выключится и поднимется заново, страница обновится "
                         "сама. Введите PIN администратора.",
                action_label="Перезапустить",
                on_confirm=_restart,
            )

        button = ui.button("Перезапустить кассу", icon="restart_alt", on_click=ask) \
            .props("outline no-caps")
        if not snap.app.supervised:
            button.disable()
            button.tooltip("Сервер запущен без автоперезапуска — поднять его заново "
                           "придётся тем же способом, каким запускали.")
        elif snap.shift_open:
            button.disable()
            button.tooltip("Идёт смена: перезапуск оборвал бы работу кассира. "
                           "Сначала закройте смену.")

    def _restart() -> None:
        ui.notify("Перезапускаю кассу — страница обновится сама.", color="green")
        # Страницу перезагружаем позже перезапуска сервера, иначе браузер
        # постучится в ещё не поднявшийся порт и покажет ошибку.
        ui.timer(8.0, lambda: ui.navigate.reload(), once=True)
        updater.schedule_restart()

    # ---------- мелкие элементы ----------

    def _fact(title: str, value: str, *, danger: bool = False) -> None:
        with ui.column().classes("gap-0 p-3 rounded-xl") \
                .style("background: var(--surface-sunken)"):
            ui.label(title).classes("text-xs").style("color: var(--text-secondary)")
            label = ui.label(value).classes("text-base font-bold truncate")
            if danger:
                label.style("color: var(--status-danger)")

    def _gauge(title: str, value: str, percent: float, *, right: str = "") -> None:
        percent = min(max(percent, 0.0), 100.0)
        color = ("var(--status-danger)" if percent >= 90
                 else "var(--status-warning)" if percent >= 75
                 else "var(--brand-primary)")
        with ui.column().classes("gap-1 w-full"):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.label(title).classes("flex-1 text-base")
                ui.label(value).classes("text-base font-bold")
                if right:
                    ui.label(right).classes("text-xs").style("color: var(--text-secondary)")
            with ui.element("div").classes("w-full rounded-full overflow-hidden") \
                    .style("height:8px; background: var(--surface-sunken)"):
                ui.element("div").classes("h-full rounded-full") \
                    .style(f"width:{percent}%; background: {color}")

    def _note(icon: str, color: str, text: str) -> None:
        with ui.row().classes("items-start gap-2 no-wrap"):
            ui.icon(icon, size="18px").style(f"color: {color}")
            ui.label(text).classes("text-sm").style("color: var(--text-secondary)")

    def _period(db: sysinfo.DatabaseInfo) -> str:
        if db.oldest_order_at is None or db.newest_order_at is None:
            return "продаж ещё не было"
        return (f"{to_almaty(db.oldest_order_at):%d.%m.%y} — "
                f"{to_almaty(db.newest_order_at):%d.%m.%y}")

    # ---------- сборка экрана ----------

    def render() -> None:
        root.clear()
        snap = state["snapshot"]
        with root:
            if snap is None:
                with ui.row().classes("items-center gap-3 p-4"):
                    ui.spinner(size="2rem")
                    ui.label("Собираю сведения о сервере…").classes("text-base")
                return
            render_header(snap)
            render_verdict(snap)
            render_server(snap)
            render_resources(snap)
            render_tasks(snap)
            render_database(snap)
            render_backups(snap)
            render_perf()
            render_log(snap)
            render_control(snap)

    render()
    # Таймер создаётся один раз на страницу, а не внутри render(): перерисовка
    # вызывается на каждое нажатие, и таймеры копились бы, опрашивая сервер всё чаще.
    ui.timer(_REFRESH_SECONDS, tick)
    ui.timer(0.1, reload, once=True)
