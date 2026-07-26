from nicegui import ui

from app.db import SessionLocal
from app.services import user_service as us
from app.services.login_throttle import LockedOut
from app.ui.guard import login_user
from app.ui.theme import apply_theme


@ui.page("/login")
def login_page() -> None:
    apply_theme()
    with SessionLocal() as session:
        users = {u.id: f"{u.name} ({u.role})" for u in us.active_users(session)}

    outer = ui.column().classes("w-full min-h-screen items-center justify-center")
    with outer, ui.card().classes("w-96 p-8 gap-4 items-stretch"):
        ui.label("☕ Кофейня").classes("text-3xl font-black text-center") \
            .style("color: var(--brand-primary)")
        ui.label("Вход").classes("text-xl font-bold")

        if not users:
            ui.label("Нет пользователей. Запустите seed.py").classes("text-red-600")
            return

        user_sel = ui.select(users, label="Пользователь").classes("w-full")
        pin_in = ui.input("Пин-код", password=True).props("inputmode=numeric").classes("w-full")

        def do_login() -> None:
            if not user_sel.value or not pin_in.value:
                ui.notify("Выберите пользователя и введите пин", color="red")
                return
            try:
                with SessionLocal() as session:
                    user = us.authenticate(session, user_id=user_sel.value, pin=pin_in.value)
            except LockedOut as e:
                pin_in.value = ""
                ui.notify(f"Слишком много попыток. Подождите {e.retry_after_seconds} с.", color="red")
                return
            if user is None:
                pin_in.value = ""
                ui.notify("Неверный пин-код", color="red")
                return
            login_user(user)
            ui.navigate.to("/admin" if user.role == "admin" else "/cashier")

        pin_in.on("keydown.enter", lambda _: do_login())
        ui.button("Войти", on_click=do_login).classes("w-full")
