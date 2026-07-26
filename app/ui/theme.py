from dataclasses import dataclass

from nicegui import app, ui

# Темы оформления из дизайн-системы «Coffee POS» (claude.ai/design).
# Каждая тема — набор CSS-переменных в блоке [data-theme="<id>"]; переключение
# сводится к смене атрибута на <html>, перезагрузка страницы не нужна.
STORAGE_KEY = "theme"
DEFAULT_THEME = "light"


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    sub: str
    swatch: str      # цвет кружка в списке выбора
    icon: str
    dark: bool
    primary: str     # дальше — палитра Quasar (ui.colors), должна совпадать с CSS темы
    accent: str
    positive: str
    negative: str
    warning: str
    info: str


THEMES: list[Theme] = [
    Theme("oled", "OLED", "Почти чёрная — контраст и экономия", "#000000", "dark_mode", True,
          "#c49668", "#dcbd97", "#5fd07a", "#e2594a", "#f0a24a", "#7db2ff"),
    Theme("night", "Ночная смена", "Тёплая, без синего света", "#1c1712", "bedtime", True,
          "#e0b47f", "#dcbd97", "#8fc98a", "#e0705a", "#e8a95c", "#b79b7a"),
    Theme("graphite", "Графит", "Нейтральный тёмно-серый", "#1e2126", "contrast", True,
          "#c49668", "#dcbd97", "#6bd18a", "#e46a5c", "#f0a24a", "#7db2ff"),
    Theme("coffee", "Кофейная", "Тёмный шоколад", "#2a1a12", "local_cafe", True,
          "#dcbd97", "#c49668", "#7fd08a", "#ef7060", "#f2ab5e", "#9fb8e8"),
    Theme("light", "Светлая", "День, яркое солнце в зале", "#fffdf9", "light_mode", False,
          "#6b4226", "#a97648", "#1b5e20", "#a31d1d", "#bf5f00", "#1558b0"),
]

_BY_ID = {t.id: t for t in THEMES}

_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;900&display=swap');
:root{
  --coffee-950:#2a1a12;--coffee-900:#3b2417;--coffee-800:#4e301e;--coffee-700:#6b4226;
  --coffee-600:#8a5a34;--coffee-500:#a97648;--coffee-400:#c49668;--coffee-300:#dcbd97;
  --coffee-200:#ecdcc2;--coffee-100:#f5ece0;--coffee-50:#faf6ef;
  --cream-0:#fffdf9;
  --ink-900:#241b14;--ink-700:#4a3d32;--ink-500:#71685e;--ink-300:#a89e93;--ink-100:#ded6cb;
  --gray-50:#f7f5f2;--gray-100:#efeae3;--gray-300:#c9c0b5;
  --radius-md:10px;--radius-lg:16px;
}
[data-theme="light"]{
  --surface-app:#fffdf9;--surface-card:#fff;--surface-sunken:#f7f5f2;--surface-header:#3b2417;
  --text-primary:#241b14;--text-secondary:#71685e;--text-muted:#a89e93;
  --border-subtle:#efeae3;--border-default:#c9c0b5;
  --brand-primary:#6b4226;--brand-primary-hover:#4e301e;--brand-accent:#a97648;--text-on-brand:#fff;
  --coffee-50:#faf6ef;--gray-50:#f7f5f2;
  --status-success:#1b5e20;--status-success-bg:#e8f5e9;--status-success-border:#81c784;
  --status-danger:#a31d1d;--status-danger-bg:#fdecea;--status-danger-border:#e57373;
  --status-warning:#bf5f00;--status-warning-bg:#fff3e0;
  --status-info:#1558b0;--status-info-bg:#e8f0fe;
  --shadow-sm:0 1px 2px rgba(36,27,20,.08);--shadow-md:0 4px 12px rgba(36,27,20,.1);
  --shadow-lg:0 18px 48px rgba(36,27,20,.18);--shadow-header:0 2px 8px rgba(0,0,0,.18);
}
[data-theme="oled"]{
  --surface-app:#000;--surface-card:#101012;--surface-sunken:#1b1b1f;--surface-header:#08080a;
  --text-primary:#f4f2ee;--text-secondary:#a6a29b;--text-muted:#6f6b64;
  --border-subtle:#212126;--border-default:#3a3a42;
  --brand-primary:#c49668;--brand-primary-hover:#dcbd97;--brand-accent:#dcbd97;--text-on-brand:#1a1208;
  --coffee-50:#18181c;--gray-50:#1b1b1f;
  --status-success:#5fd07a;--status-success-bg:#0f2417;--status-success-border:#2f6b41;
  --status-danger:#e2594a;--status-danger-bg:#2a1210;--status-danger-border:#7a2b23;
  --status-warning:#f0a24a;--status-warning-bg:#2a1c0d;
  --status-info:#7db2ff;--status-info-bg:#0f1b2e;
  --shadow-sm:0 1px 2px rgba(0,0,0,.7);--shadow-md:0 6px 18px rgba(0,0,0,.6);
  --shadow-lg:0 18px 48px rgba(0,0,0,.75);--shadow-header:0 1px 0 #212126;
}
[data-theme="night"]{
  --surface-app:#120f0b;--surface-card:#1c1712;--surface-sunken:#251e17;--surface-header:#0d0a07;
  --text-primary:#f2e5d2;--text-secondary:#b09a80;--text-muted:#7a6a58;
  --border-subtle:#2a2219;--border-default:#453728;
  --brand-primary:#e0b47f;--brand-primary-hover:#f0cda1;--brand-accent:#dcbd97;--text-on-brand:#1a1208;
  --coffee-50:#241d16;--gray-50:#251e17;
  --status-success:#8fc98a;--status-success-bg:#16240f;--status-success-border:#3f6b39;
  --status-danger:#e0705a;--status-danger-bg:#2a150f;--status-danger-border:#7a3a2b;
  --status-warning:#e8a95c;--status-warning-bg:#2a1e0d;
  --status-info:#b79b7a;--status-info-bg:#231a10;
  --shadow-sm:0 1px 2px rgba(0,0,0,.55);--shadow-md:0 6px 18px rgba(0,0,0,.5);
  --shadow-lg:0 18px 48px rgba(0,0,0,.65);--shadow-header:0 1px 0 #2a2219;
}
[data-theme="graphite"]{
  --surface-app:#15171a;--surface-card:#1e2126;--surface-sunken:#272b31;--surface-header:#101215;
  --text-primary:#e9ebee;--text-secondary:#a0a6ae;--text-muted:#6d737b;
  --border-subtle:#272b31;--border-default:#3d434b;
  --brand-primary:#c49668;--brand-primary-hover:#dcbd97;--brand-accent:#dcbd97;--text-on-brand:#151719;
  --coffee-50:#252930;--gray-50:#272b31;
  --status-success:#6bd18a;--status-success-bg:#13251b;--status-success-border:#356b46;
  --status-danger:#e46a5c;--status-danger-bg:#2a1614;--status-danger-border:#7a322a;
  --status-warning:#f0a24a;--status-warning-bg:#2a1f10;
  --status-info:#7db2ff;--status-info-bg:#131d2c;
  --shadow-sm:0 1px 2px rgba(0,0,0,.5);--shadow-md:0 6px 18px rgba(0,0,0,.45);
  --shadow-lg:0 18px 48px rgba(0,0,0,.6);--shadow-header:0 1px 0 #272b31;
}
[data-theme="coffee"]{
  --surface-app:#1a120e;--surface-card:#2a1a12;--surface-sunken:#35231a;--surface-header:#120c09;
  --text-primary:#f5ece0;--text-secondary:#bda88f;--text-muted:#8a7460;
  --border-subtle:#35231a;--border-default:#54382a;
  --brand-primary:#dcbd97;--brand-primary-hover:#ecdcc2;--brand-accent:#c49668;--text-on-brand:#241b14;
  --coffee-50:#33211a;--gray-50:#35231a;
  --status-success:#7fd08a;--status-success-bg:#17280f;--status-success-border:#3d6b3a;
  --status-danger:#ef7060;--status-danger-bg:#31150f;--status-danger-border:#82372a;
  --status-warning:#f2ab5e;--status-warning-bg:#31200e;
  --status-info:#9fb8e8;--status-info-bg:#1a2030;
  --shadow-sm:0 1px 2px rgba(0,0,0,.55);--shadow-md:0 6px 18px rgba(0,0,0,.5);
  --shadow-lg:0 18px 48px rgba(0,0,0,.65);--shadow-header:0 1px 0 #35231a;
}

body, .nicegui-content, .q-page-container, .q-page {
  background: var(--surface-app);
  font-family: 'Roboto', -apple-system, 'Segoe UI', Arial, sans-serif;
  color: var(--text-primary);
}
.q-header {
  background: var(--surface-header) !important;
  box-shadow: var(--shadow-header) !important;
  color: #ffffff;
}
.q-card, .nicegui-card {
  border-radius: var(--radius-lg) !important;
  box-shadow: var(--shadow-md) !important;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
}
.q-btn { border-radius: var(--radius-md) !important; font-weight: 700; text-transform: none; }
.q-tab { text-transform: none; font-weight: 700; }
/* Подсветка кликабельных карточек. Раньше цвет был вписан хексом (#f5ece0) прямо
   в классы — в тёмных темах карточка вспыхивала белым под курсором. */
.cp-hover { transition: background 150ms ease-out, border-color 150ms ease-out; }
.cp-hover:hover { background: var(--coffee-50) !important; border-color: var(--brand-primary) !important; }
.cp-hover:active { transform: scale(.985); }
/* Тёмные темы: подменяем собственные поверхности Quasar своими токенами, чтобы
   меню, диалоги, таблицы и поля ввода красились темой, а не дефолтным серым. */
body.body--dark { --q-dark: var(--surface-card); --q-dark-page: var(--surface-app); }
body.body--dark .q-field__control { background: var(--surface-sunken); }
body.body--dark .q-table tbody td, body.body--dark .q-table thead th { color: var(--text-primary); }
body.body--dark .text-grey-8, body.body--dark .text-grey-7, body.body--dark .text-grey-6 {
  color: var(--text-secondary) !important;
}

/* Всё, что перебивает классы Tailwind, обязано лежать внутри @layer: Tailwind
   объявлен слоем, а !important внутри слоя сильнее !important вне слоёв —
   без этой обёртки правила ниже молча не применяются. */
@layer utilities {
  /* Фирменный цвет в тёмных темах светлый, и дефолтный белый текст Quasar дал бы
     на нём контраст ~2.7:1. Для этого в дизайн-системе и заведён --text-on-brand. */
  .q-btn.bg-primary, .q-badge.bg-primary, .q-chip.bg-primary {
    color: var(--text-on-brand) !important;
  }
  /* Пилюли категорий, переключатель раскладок и карточки способов оплаты.
     Цвет текста задаём здесь, а не инлайном: у flat-кнопки Quasar текст красится
     в primary — то есть в тот же цвет, что фон активной пилюли, и надпись пропадает.
     Инлайновый style этому не помеха — правило Quasar лежит в слое с !important. */
  .cp-pill-active, .cp-pill-active .q-icon, .cp-pill-active .q-btn__content {
    color: var(--text-on-brand) !important;
  }
  .cp-pill-active { background: var(--brand-primary) !important; border-color: var(--brand-primary) !important; }
  .cp-pill-idle, .cp-pill-idle .q-icon, .cp-pill-idle .q-btn__content {
    color: var(--text-primary) !important;
  }
  .cp-pill-idle { background: var(--surface-card) !important; border: 1px solid var(--border-subtle) !important; }
  .cp-pill-idle .q-icon { color: var(--brand-primary) !important; }
  /* Неактивная кнопка переключателя раскладок — без фона, приглушённый текст */
  .cp-pill-flat, .cp-pill-flat .q-btn__content { color: var(--text-secondary) !important; }
  .cp-pill-flat { background: transparent !important; }
  /* Карточка способа оплаты: подпись всегда основным цветом, иконка — фирменным */
  .cp-method .q-btn__content, .cp-method .cp-method-label { color: var(--text-primary) !important; }
  .cp-method .q-icon { color: var(--brand-primary) !important; }

  /* Светлые фоны-утилиты в тёмной теме давали белые пятна. */
  body.body--dark .bg-white, body.body--dark .bg-gray-50, body.body--dark .bg-gray-100 {
    background: var(--surface-card) !important;
  }
  body.body--dark .bg-green-50 { background: var(--status-success-bg) !important; }
  body.body--dark .text-green-800, body.body--dark .text-green-700,
  body.body--dark .text-green-600 { color: var(--status-success) !important; }
}
</style>
"""


def theme_by_id(theme_id: str | None) -> Theme:
    return _BY_ID.get(theme_id or "", _BY_ID[DEFAULT_THEME])


def current_theme() -> Theme:
    """Выбранная тема. Хранится в storage.user: storage.browser доступен только
    на чтение вне построения страницы, а тему меняют кликом уже на открытой."""
    try:
        return theme_by_id(app.storage.user.get(STORAGE_KEY))
    except Exception:  # вне контекста запроса (например, в тестах)
        return _BY_ID[DEFAULT_THEME]


def set_theme(theme_id: str) -> None:
    """Сохраняет выбор темы в сессии."""
    app.storage.user[STORAGE_KEY] = theme_by_id(theme_id).id


def _apply_colors(theme: Theme) -> None:
    ui.colors(primary=theme.primary, secondary=theme.accent, accent=theme.accent,
              positive=theme.positive, negative=theme.negative,
              warning=theme.warning, info=theme.info)


def apply_theme() -> None:
    """Применяет выбранную тему. Вызывать в начале каждой страницы."""
    theme = current_theme()
    ui.add_head_html(_THEME_CSS)
    # data-theme ставим на <html> до отрисовки — иначе видна вспышка светлой темы
    ui.add_head_html(
        f"<script>document.documentElement.dataset.theme = '{theme.id}';</script>"
    )
    ui.dark_mode(theme.dark)
    _apply_colors(theme)


def theme_button(*, on_header: bool = True) -> None:
    """Кнопка выбора темы: иконка, название и выпадающий список тем.

    on_header=False — для светлой карточки (экран входа), где белый текст не виден.
    """
    theme = current_theme()
    props = "flat no-caps " + ("color=white" if on_header else "color=primary")
    with ui.button(icon=theme.icon).props(props) as btn:
        ui.label(theme.label).classes("ml-1 text-sm font-normal")
        with ui.menu().props("auto-close").classes("w-80"):
            ui.label("Тема оформления").classes("px-4 pt-3 pb-1 text-sm opacity-70")
            for t in THEMES:
                _theme_menu_item(t, selected=t.id == theme.id)
    btn.tooltip("Тема оформления")


def _theme_menu_item(t: Theme, *, selected: bool) -> None:
    with ui.item(on_click=lambda t=t: _pick(t.id)).classes("items-center gap-3"):
        with ui.item_section().props("avatar"):
            ui.element("div").style(
                f"width:38px;height:38px;border-radius:10px;background:{t.swatch};"
                "border:1px solid var(--border-default)"
            )
        with ui.item_section():
            ui.label(t.label).classes("text-base font-bold")
            ui.label(t.sub).classes("text-xs opacity-70")
        if selected:
            with ui.item_section().props("side"):
                ui.icon("check_circle").classes("text-xl").style("color:var(--brand-primary)")


def _pick(theme_id: str) -> None:
    set_theme(theme_id)
    ui.navigate.reload()
