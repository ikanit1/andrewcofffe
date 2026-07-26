from nicegui import app, ui

from app.models import User


def current_user_id(storage=None) -> int | None:
    store = storage if storage is not None else app.storage
    return store.user.get("user_id")


def is_admin(storage=None) -> bool:
    store = storage if storage is not None else app.storage
    return store.user.get("role") == "admin"


def session_user(session, storage=None) -> User | None:
    """Пользователь сессии, сверенный с базой. None — сессии верить нельзя.

    В storage лежит снимок на момент входа. Без сверки уволенный кассир
    продолжал бы работать в уже открытой вкладке, а понижённый администратор —
    сохранять доступ к админке до тех пор, пока сам не нажмёт «Выход».
    """
    user_id = current_user_id(storage)
    if user_id is None:
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    store = storage if storage is not None else app.storage
    if user.role != store.user.get("role"):
        return None
    return user


def _session_is_valid() -> bool:
    from app.db import SessionLocal

    with SessionLocal() as session:
        return session_user(session) is not None


def require_user() -> bool:
    """Вызывать в начале страницы. False + редирект на /login, если не авторизован."""
    if current_user_id() is None or not _session_is_valid():
        logout()
        ui.navigate.to("/login")
        return False
    return True


def require_admin() -> bool:
    if not require_user():
        return False
    if not is_admin():
        ui.label("Доступ только для администратора").classes("text-red-600 text-xl")
        return False
    return True


def login_user(user) -> None:
    app.storage.user["user_id"] = user.id
    app.storage.user["role"] = user.role
    app.storage.user["name"] = user.name


def logout() -> None:
    # Тема — настройка устройства, а не пользователя: переживает выход,
    # иначе кассир на тёмном моноблоке каждый раз получал бы светлый экран входа.
    from app.ui.theme import STORAGE_KEY as THEME_KEY

    theme = app.storage.user.get(THEME_KEY)
    app.storage.user.clear()
    if theme is not None:
        app.storage.user[THEME_KEY] = theme
