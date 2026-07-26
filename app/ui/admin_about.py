from nicegui import ui

from app.services import updates
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
            ui.label("Как обновить").classes("text-base font-bold")
            ui.label(
                "Закройте смену, затем запустите update.ps1 в папке кассы: "
                "правой кнопкой → Run with PowerShell. Скрипт заберёт новую "
                "версию, доставит зависимости и перезапустит сервер."
            ).classes("text-sm").style("color: var(--text-secondary)")
            with ui.row().classes("items-start gap-2 no-wrap p-3 rounded-xl") \
                    .style("background: var(--status-success-bg)"):
                ui.icon("shield", size="20px").style("color: var(--status-success)")
                ui.label(
                    "База данных при обновлении не трогается: продажи, меню, "
                    "пользователи и остатки останутся на месте. Обновляется только код."
                ).classes("text-sm").style("color: var(--text-primary)")
            with ui.row().classes("items-start gap-2 no-wrap p-3 rounded-xl") \
                    .style("background: var(--surface-sunken)"):
                ui.icon("info", size="20px").style("color: var(--text-secondary)")
                ui.label(
                    "Кнопки «обновить» здесь намеренно нет: касса доступна из "
                    "интернета, и запуск обновления через веб дал бы способ "
                    "выполнить чужой код. Обновление — только с самого моноблока."
                ).classes("text-sm").style("color: var(--text-secondary)")

        btn = ui.button("Проверить обновление", icon="refresh", on_click=check) \
            .props("no-caps")
        ui.label("Сверяется с версией, опубликованной на GitHub. "
                 "Проверка ничего не скачивает и не меняет.") \
            .classes("text-xs").style("color: var(--text-muted)")
