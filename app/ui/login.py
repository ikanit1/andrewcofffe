from nicegui import ui

from app.db import SessionLocal
from app.services import user_service as us
from app.ui.guard import login_user

# простой лимит попыток пин-кода на вкладку (сбрасывается перезагрузкой)
_MAX_ATTEMPTS = 5


@ui.page("/login")
def login_page() -> None:
    ui.label("Вход").classes("text-2xl font-bold")
    with SessionLocal() as session:
        users = {u.id: f"{u.name} ({u.role})" for u in us.active_users(session)}

    if not users:
        ui.label("Нет пользователей. Запустите seed.py").classes("text-red-600")
        return

    state = {"attempts": 0}
    user_sel = ui.select(users, label="Пользователь")
    pin_in = ui.input("Пин-код", password=True).props("inputmode=numeric")

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
        ui.navigate.to("/cashier")

    pin_in.on("keydown.enter", lambda _: do_login())
    ui.button("Войти", on_click=do_login)
