from nicegui import ui

from app.db import SessionLocal
from app.services import user_service as us
from app.ui.guard import login_user
from app.ui.theme import apply_theme

# простой лимит попыток пин-кода на вкладку (сбрасывается перезагрузкой)
_MAX_ATTEMPTS = 5


@ui.page("/login")
def login_page() -> None:
    apply_theme()
    with SessionLocal() as session:
        users = {u.id: f"{u.name} ({u.role})" for u in us.active_users(session)}

    state = {"attempts": 0}

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
            if state["attempts"] >= _MAX_ATTEMPTS:
                ui.notify("Слишком много попыток. Перезагрузите страницу.", color="red")
                return
            if not user_sel.value or not pin_in.value:
                ui.notify("Выберите пользователя и введите пин", color="red")
                return
            with SessionLocal() as session:
                user = us.authenticate(session, user_id=user_sel.value, pin=pin_in.value)
            if user is None:
                state["attempts"] += 1
                pin_in.value = ""
                ui.notify("Неверный пин-код", color="red")
                return
            login_user(user)
            ui.navigate.to("/admin" if user.role == "admin" else "/cashier")

        pin_in.on("keydown.enter", lambda _: do_login())
        ui.button("Войти", on_click=do_login).classes("w-full")
