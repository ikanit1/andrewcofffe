from nicegui import ui

from app.db import SessionLocal
from app.services import shift_service as ss
from app.services import updater, updates, user_service
from app.services.login_throttle import LockedOut
from app.ui.design import numpad
from app.ui.guard import require_admin
from app.ui.layout import admin_header

_STATUS_VIEW = {
    "current": ("check_circle", "var(--status-success)", "Установлена последняя версия"),
    "outdated": ("system_update", "var(--status-warning)", "Вышла новая версия"),
    "ahead": ("science", "var(--text-secondary)",
              "Версия новее опубликованной — похоже, это машина разработчика"),
    "unknown": ("help_outline", "var(--text-secondary)", "Не удалось проверить"),
}


@ui.page("/admin/about")
def admin_about_page() -> None:
    if not require_admin():
        return
    admin_header()

    with ui.column().classes("w-full max-w-2xl gap-4 p-1"):
        ui.label("Версия и обновление").classes("text-2xl font-black")

        with ui.card().classes("w-full p-5 gap-2"):
            ui.label("Установленная версия").classes("text-sm") \
                .style("color: var(--text-secondary)")
            ui.label(updates.local_version() or "неизвестна") \
                .classes("text-3xl font-black")

        result_box = ui.column().classes("w-full gap-3")

        async def check() -> None:
            btn.disable()
            result_box.clear()
            with result_box:
                ui.label("Проверяю…").style("color: var(--text-secondary)")
            try:
                res = await updates.check_for_update()
            finally:
                btn.enable()
            _render(res)

        def _subtitle(res: updates.UpdateCheck) -> str:
            """Пояснение под статусом.

            Слово «сервер» здесь не годится: в кассе так называют моноблок,
            на котором она и работает, — владелец решит, что сравнивают с ним.
            Когда версии совпали, второй строки нет вовсе: повторять одно и то же
            число дважды бессмысленно.
            """
            if res.status == "outdated":
                return f"Доступна {res.remote}, у вас {res.local}"
            if res.status == "ahead":
                return f"У вас {res.local}, опубликована {res.remote}"
            if res.error:
                return "Нет связи с GitHub — касса работает как обычно"
            return ""

        def _render(res: updates.UpdateCheck) -> None:
            icon, color, title = _STATUS_VIEW[res.status]
            result_box.clear()
            with result_box, ui.card().classes("w-full p-5 gap-3"):
                with ui.row().classes("items-center gap-3 no-wrap"):
                    ui.icon(icon, size="28px").style(f"color: {color}")
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(title).classes("text-lg font-bold leading-tight")
                        sub = _subtitle(res)
                        if sub:
                            ui.label(sub).classes("text-sm") \
                                .style("color: var(--text-secondary)")
                if res.status == "outdated":
                    _how_to_update()

        def _how_to_update() -> None:
            ui.separator()
            with ui.row().classes("items-start gap-2 no-wrap p-3 rounded-xl") \
                    .style("background: var(--status-success-bg)"):
                ui.icon("shield", size="20px").style("color: var(--status-success)")
                ui.label(
                    "База данных не трогается: продажи, меню, пользователи, остатки "
                    "и настройки Kaspi останутся на месте. Обновляется только код, "
                    "а копия базы кладётся в backups перед началом."
                ).classes("text-sm").style("color: var(--text-primary)")

            with SessionLocal() as s:
                shift_open = ss.current_open_shift(s) is not None

            if shift_open:
                with ui.row().classes("items-start gap-2 no-wrap p-3 rounded-xl") \
                        .style("background: var(--status-warning-bg)"):
                    ui.icon("lock_clock", size="20px").style("color: var(--status-warning)")
                    ui.label(
                        "Сейчас открыта смена. Обновление перезапускает кассу, "
                        "поэтому сначала закройте смену."
                    ).classes("text-sm").style("color: var(--text-primary)")
                return

            ui.button("Обновить и перезапустить", icon="system_update",
                      on_click=_ask_pin).props("no-caps")
            hint = ("После обновления касса перезапустится сама, страница обновится."
                    if updater.is_supervised() else
                    "Автоперезапуск не настроен: код обновится, а кассу нужно будет "
                    "перезапустить вручную через start.ps1.")
            ui.label(hint).classes("text-xs").style("color: var(--text-muted)")

        def _ask_pin() -> None:
            """PIN администратора перед обновлением.

            Касса смотрит в интернет через Funnel. Одной открытой вкладки
            для запуска обновления мало: пусть тот, кто нажимает, подтвердит,
            что он администратор, а не перехваченная сессия.
            """
            with ui.dialog() as dlg, ui.card().classes("gap-3 min-w-80"):
                ui.label("Подтвердите обновление").classes("text-lg font-bold")
                ui.label("Касса будет перезапущена. Введите PIN администратора.") \
                    .classes("text-sm").style("color: var(--text-secondary)")
                pin = ui.input("PIN", password=True).props("inputmode=numeric readonly") \
                    .classes("w-full")
                numpad(pin, money=False, max_len=6)

                async def confirm() -> None:
                    try:
                        with SessionLocal() as s:
                            admin = user_service.admin_by_pin(s, (pin.value or "").strip())
                    except LockedOut as e:
                        pin.value = ""
                        ui.notify(f"Слишком много попыток. Подождите {e.retry_after_seconds} с.",
                                  color="red")
                        return
                    if admin is None:
                        pin.value = ""
                        ui.notify("Неверный PIN администратора", color="red")
                        return
                    dlg.close()
                    await _do_update()

                with ui.row().classes("gap-2"):
                    ui.button("Обновить", on_click=confirm).props("no-caps")
                    ui.button("Отмена", on_click=dlg.close).props("flat no-caps")
            dlg.open()

        async def _do_update() -> None:
            result_box.clear()
            with result_box, ui.card().classes("w-full p-5 gap-2"):
                ui.spinner(size="2rem")
                ui.label("Обновляю: забираю код и ставлю зависимости…") \
                    .classes("text-base")
                ui.label("Это занимает до минуты. Не закрывайте страницу.") \
                    .classes("text-xs").style("color: var(--text-muted)")

            with SessionLocal() as s:
                res = await updater.apply_update(s)

            result_box.clear()
            color = "var(--status-success)" if res.ok else "var(--status-danger)"
            with result_box, ui.card().classes("w-full p-5 gap-3"):
                with ui.row().classes("items-center gap-3 no-wrap"):
                    ui.icon("check_circle" if res.ok else "error", size="28px") \
                        .style(f"color: {color}")
                    ui.label(res.message).classes("text-base font-bold")
                for step in res.steps:
                    ui.label(f"• {step}").classes("text-sm") \
                        .style("color: var(--text-secondary)")
                if res.log:
                    with ui.expansion("Подробности").classes("w-full"):
                        ui.code(res.log).classes("w-full text-xs")

            if res.restart_scheduled:
                # Перезагружаем страницу позже перезапуска сервера, иначе браузер
                # постучится в ещё не поднявшийся порт и покажет ошибку.
                ui.timer(8.0, lambda: ui.navigate.reload(), once=True)
                updater.schedule_restart()

        btn = ui.button("Проверить обновление", icon="refresh", on_click=check) \
            .props("no-caps")
        ui.label("Сверяется с версией, опубликованной на GitHub. "
                 "Проверка ничего не скачивает и не меняет.") \
            .classes("text-xs").style("color: var(--text-muted)")
