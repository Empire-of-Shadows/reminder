"""ImperialReminder's admin panel seam (bot-owned, NEVER vendored).

The vendored engine beside this package reaches every reminder-specific backend
through the names defined here: ``bindings`` (config/audit/premium/cache +
static branding text), ``panel_configs`` (the MAIN_PANEL tree), and
``panel_branding`` (titles and guide text). Tier resolution lives in
``bindings.resolve_panel_role``, which delegates to the vendored engine resolver
(``admin/auth.py``) - there is no bot-owned role_auth module. Engine files
import them as ``from .settings.bindings import ...`` /
``from .settings.panel_configs import MAIN_PANEL``.
"""
