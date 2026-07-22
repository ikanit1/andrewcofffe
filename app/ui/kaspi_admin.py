from nicegui import ui

from app.db import SessionLocal
from app.kaspi import service as kaspi_service
from app.kaspi import settings as ksettings
from app.ui.guard import require_admin
from app.ui.theme import apply_theme


@ui.page("/admin/kaspi")
def kaspi_admin_page() -> None:
    if not require_admin():
        return
    apply_theme()

    ui.label("Настройка терминала Kaspi").classes("text-2xl font-bold")

    with SessionLocal() as session:
        s = ksettings.get_settings(session)
        url_value = s.terminal_url
        name_value = s.cashier_name
        has_token = s.access_token is not None
        term_id = s.terminal_id

    url_in = ui.input("Адрес терминала", value=url_value).classes("w-full max-w-md")
    name_in = ui.input("Имя кассы", value=name_value).classes("w-full max-w-md")
    status_box = ui.column().classes("gap-1 mt-2")

    with status_box:
        ui.label(f"Токен: {'получен' if has_token else 'не получен'}").classes(
            "text-green-700" if has_token else "text-gray-500")
        if term_id:
            ui.label(f"ID терминала: {term_id}")

    def save_config() -> None:
        with SessionLocal() as session:
            ksettings.save_config(session, terminal_url=url_in.value.strip(),
                                  cashier_name=name_in.value.strip())
        ui.notify("Настройки сохранены", color="green")

    async def check() -> None:
        save_config()
        try:
            with SessionLocal() as session:
                data = await kaspi_service.check_connection(session)
        except Exception as e:
            ui.notify(f"Нет связи с терминалом: {e}", color="red")
            return
        ui.notify(
            f"Терминал на связи. Серийный: {data.get('serialNum')}, ID: {data.get('terminalId')}",
            color="green",
        )

    async def register() -> None:
        save_config()
        ui.notify("Подтвердите доступ на экране терминала…", color="blue")
        try:
            with SessionLocal() as session:
                await kaspi_service.register_cashier(session)
        except Exception as e:
            ui.notify(f"Регистрация не удалась: {e}", color="red")
            return
        ui.notify("Касса зарегистрирована, токен получен", color="green")

    with ui.row().classes("gap-2 mt-2"):
        ui.button("Сохранить", on_click=save_config)
        ui.button("Проверить связь", on_click=check)
        ui.button("Зарегистрировать кассу", on_click=register, color="green")
