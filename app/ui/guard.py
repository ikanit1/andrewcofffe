from nicegui import app, ui


def current_user_id(storage=None) -> int | None:
    store = storage if storage is not None else app.storage
    return store.user.get("user_id")


def is_admin(storage=None) -> bool:
    store = storage if storage is not None else app.storage
    return store.user.get("role") == "admin"


def require_user() -> bool:
    """Вызывать в начале страницы. False + редирект на /login, если не авторизован."""
    if current_user_id() is None:
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
    app.storage.user.clear()
