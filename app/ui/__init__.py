def register_pages() -> None:
    """Импортирует модули страниц NiceGUI (каждый регистрирует свои @ui.page)."""
    from app.ui import (  # noqa: F401
        admin_about,
        admin_dashboard,
        admin_home,
        admin_menu,
        admin_users,
        admin_modifiers,
        admin_stock,
        admin_system,
        cashier,
        kaspi_admin,
        login,
        purchase,
        reports,
    )
