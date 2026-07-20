def register_pages() -> None:
    """Импортирует модули страниц NiceGUI (каждый регистрирует свои @ui.page)."""
    from app.ui import (  # noqa: F401
        admin_menu,
        admin_modifiers,
        admin_stock,
        cashier,
        login,
    )
