from nicegui import ui

from app.db import SessionLocal
from app.models import User
from app.services import user_service as us
from app.ui.design import numpad
from app.ui.guard import require_admin
from app.ui.layout import admin_header

_ROLE_LABELS = {"cashier": "Кассир", "admin": "Администратор"}


@ui.page("/admin/users")
def admin_users_page() -> None:
    if not require_admin():
        return
    admin_header()

    ui.label("Пользователи").classes("text-2xl font-bold")

    box = ui.column().classes("w-full max-w-2xl gap-2")

    def refresh() -> None:
        box.clear()
        with box, SessionLocal() as session:
            users = session.query(User).order_by(User.is_active.desc(), User.name).all()
            for u in users:
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-3 w-full"):
                        ui.label(u.name).classes("text-lg font-bold flex-1")
                        ui.label(_ROLE_LABELS.get(u.role, u.role)).classes("text-gray-500")
                        if u.is_active:
                            ui.label("● активен").classes("text-green-700 text-sm")
                        else:
                            ui.label("● отключён").classes("text-red-600 text-sm")
                    with ui.row().classes("gap-2"):
                        ui.button("Имя", icon="edit",
                                  on_click=lambda uid=u.id, n=u.name: _rename(uid, n)).props("flat")
                        ui.button("Сменить PIN", icon="password",
                                  on_click=lambda uid=u.id, n=u.name: _change_pin(uid, n)).props("flat")
                        if u.is_active:
                            ui.button("Отключить", color="red",
                                      on_click=lambda uid=u.id: _set_active(uid, False)).props("flat")
                        else:
                            ui.button("Включить", color="green",
                                      on_click=lambda uid=u.id: _set_active(uid, True)).props("flat")

    def _set_active(user_id: int, active: bool) -> None:
        try:
            with SessionLocal() as session:
                us.set_active(session, user_id, active)
        except ValueError as e:
            ui.notify(str(e), color="red")
            return
        ui.notify("Готово", color="green")
        refresh()

    def _rename(user_id: int, name: str) -> None:
        with ui.dialog() as dialog, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Имя пользователя «{name}»").classes("text-lg font-bold")
            ui.label("Видно кассиру при входе, попадает в отчёты и уведомления.") \
                .classes("text-sm").style("color: var(--text-secondary)")
            name_in = ui.input("Имя", value=name).classes("w-full")

            def confirm() -> None:
                try:
                    with SessionLocal() as session:
                        us.set_name(session, user_id, name_in.value)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dialog.close()
                ui.notify("Имя изменено", color="green")
                refresh()

            name_in.on("keydown.enter", lambda _: confirm())
            with ui.row().classes("gap-2"):
                ui.button("Сохранить", on_click=confirm)
                ui.button("Отмена", on_click=dialog.close).props("flat")
        dialog.open()

    def _change_pin(user_id: int, name: str) -> None:
        with ui.dialog() as dialog, ui.card().classes("gap-3 min-w-80"):
            ui.label(f"Новый PIN для «{name}»").classes("text-lg font-bold")
            pin_in = ui.input("PIN (4–6 цифр)", password=True) \
                .props("inputmode=numeric readonly").classes("w-full")
            # Моноблок в кофейне без клавиатуры — PIN набирается мышью
            numpad(pin_in, money=False, max_len=6)

            def confirm() -> None:
                try:
                    with SessionLocal() as session:
                        us.set_pin(session, user_id, (pin_in.value or "").strip())
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dialog.close()
                ui.notify("PIN изменён", color="green")

            with ui.row().classes("gap-2"):
                ui.button("Сохранить", on_click=confirm)
                ui.button("Отмена", on_click=dialog.close).props("flat")
        dialog.open()

    with ui.expansion("Добавить пользователя").classes("w-full max-w-2xl mt-2"):
        name_in = ui.input("Имя").classes("w-full")
        tg_in = ui.number("Telegram ID", format="%.0f").classes("w-full")
        role_sel = ui.select({"cashier": "Кассир", "admin": "Администратор"},
                             value="cashier", label="Роль").classes("w-full")
        new_pin = ui.input("PIN (4–6 цифр)", password=True) \
            .props("inputmode=numeric readonly").classes("w-full")
        numpad(new_pin, money=False, max_len=6)

        def add_user() -> None:
            try:
                with SessionLocal() as session:
                    us.create_user(
                        session,
                        name=name_in.value,
                        telegram_id=int(tg_in.value) if tg_in.value is not None else None,
                        role=role_sel.value,
                        pin=(new_pin.value or "").strip(),
                    )
            except (ValueError, TypeError) as e:
                ui.notify(str(e), color="red")
                return
            name_in.value = ""
            tg_in.value = None
            new_pin.value = ""
            ui.notify("Пользователь добавлен", color="green")
            refresh()

        ui.button("Добавить", on_click=add_user)

    refresh()
