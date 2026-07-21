from nicegui import app, ui

from app.db import SessionLocal
from app.services import shift_service as ss
from app.ui import guard


def _logout() -> None:
    guard.logout()
    ui.navigate.to("/login")


def cashier_header() -> None:
    """Верхняя панель на всех экранах кассы: имя кассира, статус смены, Домой, Выход."""
    name = app.storage.user.get("name", "Кассир")
    with SessionLocal() as session:
        shift_open = ss.current_open_shift(session) is not None

    with ui.header().classes("items-center justify-between px-4 py-2"):
        with ui.row().classes("items-center gap-3"):
            ui.label("☕ Кофейня").classes("text-lg font-bold")
            ui.label(name).classes("text-base opacity-90")
            if shift_open:
                ui.label("● Смена открыта").classes("text-sm text-green-300")
            else:
                ui.label("● Смена закрыта").classes("text-sm text-red-300")
        with ui.row().classes("items-center gap-1"):
            ui.button("Домой", icon="home",
                      on_click=lambda: ui.navigate.to("/cashier")).props("flat color=white")
            ui.button("Выход", icon="logout", on_click=_logout).props("flat color=white")


def sale_success(order_number: int, extra: str = "") -> None:
    """Крупная зелёная плашка подтверждения + короткий звук; авто-закрытие ~1.8с."""
    ui.run_javascript(
        "try{const c=new (window.AudioContext||window.webkitAudioContext)();"
        "const o=c.createOscillator();const g=c.createGain();"
        "o.connect(g);g.connect(c.destination);o.type='sine';o.frequency.value=880;"
        "g.gain.setValueAtTime(0.0001,c.currentTime);"
        "g.gain.exponentialRampToValueAtTime(0.3,c.currentTime+0.02);"
        "g.gain.exponentialRampToValueAtTime(0.0001,c.currentTime+0.35);"
        "o.start();o.stop(c.currentTime+0.36);}catch(e){}"
    )
    with ui.dialog().props("persistent") as dialog, \
            ui.card().classes("items-center p-8 gap-2 bg-green-50"):
        ui.icon("check_circle", size="5rem").classes("text-green-600")
        ui.label(f"Заказ №{order_number} проведён").classes("text-2xl font-bold text-green-800")
        if extra:
            ui.label(extra).classes("text-lg text-green-700")
    dialog.open()
    ui.timer(1.8, dialog.close, once=True)
