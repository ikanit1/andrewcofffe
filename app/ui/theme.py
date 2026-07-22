from nicegui import ui

# Кофейная тема из дизайн-системы «Coffee POS» (claude.ai/design).
# Токены (цвета/типографика/формы) + базовые стили, применяемые ко всем экранам.
_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;900&display=swap');
:root{
  --coffee-950:#2a1a12;--coffee-900:#3b2417;--coffee-800:#4e301e;--coffee-700:#6b4226;
  --coffee-600:#8a5a34;--coffee-500:#a97648;--coffee-400:#c49668;--coffee-300:#dcbd97;
  --coffee-200:#ecdcc2;--coffee-100:#f5ece0;--coffee-50:#faf6ef;
  --cream-0:#fffdf9;
  --ink-900:#241b14;--ink-700:#4a3d32;--ink-500:#71685e;--ink-300:#a89e93;--ink-100:#ded6cb;
  --green-700:#1b5e20;--red-700:#a31d1d;--orange-700:#bf5f00;--blue-600:#1558b0;
  --surface-app:var(--cream-0);--surface-card:#ffffff;--surface-header:var(--coffee-900);
  --text-primary:var(--ink-900);--text-secondary:var(--ink-500);--text-muted:var(--ink-300);
  --text-on-brand:#ffffff;
  --brand-primary:var(--coffee-700);--brand-accent:var(--coffee-500);
  --status-success:var(--green-700);--status-danger:var(--red-700);
  --status-warning:var(--orange-700);--status-info:var(--blue-600);
  --border-subtle:#efeae3;--border-default:#c9c0b5;
  --radius-md:10px;--radius-lg:16px;
  --shadow-sm:0 1px 2px rgba(36,27,20,.08);--shadow-md:0 4px 12px rgba(36,27,20,.10);
  --shadow-header:0 2px 8px rgba(0,0,0,.18);
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
}
.q-btn {
  border-radius: var(--radius-md) !important;
  font-weight: 700;
  text-transform: none;
}
.q-tab { text-transform: none; font-weight: 700; }
</style>
"""


def apply_theme() -> None:
    """Применяет кофейную палитру Quasar и базовые стили. Вызывать в начале каждой страницы."""
    ui.colors(
        primary="#6b4226",     # coffee-700
        secondary="#a97648",   # coffee-500
        accent="#a97648",
        positive="#1b5e20",    # green-700
        negative="#a31d1d",    # red-700
        warning="#bf5f00",     # orange-700
        info="#1558b0",        # blue-600
    )
    ui.add_head_html(_THEME_CSS)
