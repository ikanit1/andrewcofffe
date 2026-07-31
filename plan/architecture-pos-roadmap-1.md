---
goal: Coffee POS future development roadmap
version: 1.0
date_created: 2026-07-30
last_updated: 2026-07-31
owner: Project owner
status: 'Planned'
tags:
  - architecture
  - roadmap
  - inventory
  - sales
  - reporting
  - reliability
  - packaging
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

This plan defines the next development steps for the Coffee POS project. The project is a local Python POS system built with FastAPI, NiceGUI, SQLAlchemy, SQLite, aiogram, and Kaspi terminal integration. The goal is to move the system from a working cafe POS into a more complete, maintainable, auditable, and operator-friendly business system.

## Explicit non-goal: inventory readiness enforcement

Blocking a sale because a product has no recipe, no stock link, or no remaining
balance is **out of scope for this roadmap**. That feature was implemented and
reverted on 2026-07-31: with empty recipes it made every prepared product
unsellable and stopped the till completely. Stock data stays advisory —
dashboards, reports, and low-stock notifications may warn about it, but nothing
may prevent a cashier from taking money. Do not reintroduce `Product.inventory_policy`,
`inventory_audit`, or a setup-issues screen built on the same rules.

## 1. Requirements & Constraints

- **REQ-001**: All money values must remain stored as integer tiyn in database models and services.
- **REQ-002**: All stock quantities must remain stored as integer base units in `Ingredient.stock_qty`, `RecipeItem.qty`, `ModifierItem.qty`, and `StockMove.qty_delta`.
- **REQ-003**: Sales, refunds, stock movements, payments, and notification outbox writes must remain transactional.
- **REQ-004**: UI pages must call service-layer functions for business rules; UI code must not duplicate stock, payment, or reporting rules.
- **REQ-005**: Existing `pos.db`, `.env`, and `backups/` must not be overwritten by install, update, or migration tasks.
- **REQ-006**: Existing production SQLite databases must be upgraded idempotently from application startup.
- **REQ-007**: Cashier flows must stay fast: sale screen interactions must require the minimum number of taps.
- **REQ-008**: Owner/admin flows must surface operational issues (low stock, refunds, failed payments) as information; they must never block a sale.
- **REQ-009**: Desktop packaging must be implemented only after accounting, backup/restore, setup, security, and update workflows are stable.
- **SEC-001**: Default PINs must be treated as insecure and must be replaceable from the admin UI.
- **SEC-002**: Dangerous actions must require admin role and, where applicable, PIN re-confirmation.
- **SEC-003**: Public access through Tailscale Funnel must not expose unauthenticated admin actions.
- **DAT-001**: Historical reports must not change when product names, categories, recipes, or prices change later.
- **DAT-002**: Future database changes must have tests that create an old schema and verify migration to the new schema.
- **OPS-001**: Backups must remain restorable without Git or developer tools.
- **OPS-002**: The final operator launch target is one desktop icon that starts the server hidden and opens the POS window without exposing PowerShell to the cashier.
- **CON-001**: The project currently uses SQLite and has no Alembic migration stack.
- **CON-002**: The app runs as one Python process on a Windows workstation.
- **CON-003**: NiceGUI page files are currently large; refactoring must be incremental and covered by tests.
- **CON-004**: Packaging and update scripts must preserve existing `pos.db`, `.env`, and `backups/`.
- **PAT-001**: Follow the existing structure: `app/models`, `app/services`, `app/ui`, `tests`.
- **PAT-002**: New business logic belongs in `app/services/*`; UI files render state and call services.
- **PAT-003**: New user-visible workflows must include service tests and, when practical, UI logic tests.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Stabilize database evolution and remove hidden schema risk.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Add migration registry in `app/services/migration_service.py` with `Migration(id: str, description: str, apply: Callable)` and `run_migrations(engine)`; keep existing `app.db.ensure_schema(engine)` as the entry point that delegates to the registry. | | |
| TASK-002 | Add table `schema_migrations(id VARCHAR PRIMARY KEY, applied_at DATETIME NOT NULL)` in `app/models/system.py`; import it from `app/models/__init__.py`. | | |
| TASK-003 | Move current SQLite column additions from `app/db.py::ensure_schema` into named migrations: `payments_terminal_fields`, `kaspi_protection_enabled`, `products_image_fields`, `ingredients_category_id`. | | |
| TASK-004 | Add tests in `tests/test_migrations.py` that create minimal old SQLite schemas and verify each migration adds the expected columns exactly once. | | |
| TASK-005 | Add startup logging in `app/main.py::create_app` that reports applied migration ids and failures without printing secrets. | | |

### Implementation Phase 2

- GOAL-002: Make filling in recipes easy enough that owners do it willingly — never by blocking sales.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-006 | Add recipe editor service functions in `app/services/recipe_service.py`: `set_recipe_item(session, product_id, ingredient_id, qty)`, `remove_recipe_item(session, item_id)`, `copy_recipe(session, source_product_id, target_product_id)`. | | |
| TASK-007 | Replace direct `RecipeItem(...)` writes in `app/ui/admin_stock.py::admin_stock_page` with `recipe_service.set_recipe_item`; existing ingredient lines must update quantity instead of raising `IntegrityError`. | | |
| TASK-008 | Add tests in `tests/test_recipe_service.py` for upsert, delete, copy, invalid qty, missing product, and missing ingredient. | | |

### Implementation Phase 3

- GOAL-003: Improve stock operations from basic purchase entry into auditable inventory management.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-009 | Add model `Supplier` in `app/models/inventory.py` with fields `id`, `name`, `phone`, `note`, `is_active`; expose CRUD in `app/services/supplier_service.py`. | | |
| TASK-010 | Add model `PurchaseDocument` with fields `id`, `supplier_id`, `total_cost_tiyn`, `created_at`, `note`; link `StockMove.ref_type='purchase_document'` and `ref_id=PurchaseDocument.id` from `inventory_service.receive_purchase`. | | |
| TASK-011 | Replace single-line purchase UI in `app/ui/purchase.py` with multi-line purchase document entry; each line must select ingredient, qty, and total cost. | | |
| TASK-012 | Add stock movement journal page `/admin/stock/moves` with filters by ingredient, kind, date range, and reference id. | | |
| TASK-013 | Add stock count workflow `/admin/stock/count`: snapshot current quantities, enter counted quantities, preview deltas, apply `adjustment` moves only after confirmation. | | |
| TASK-014 | Add tests in `tests/test_purchase_document.py` and `tests/test_stock_count.py` for document totals, average cost recalculation, movement references, and rollback on invalid line. | | |

### Implementation Phase 4

- GOAL-004: Complete cashier financial correctness and operational controls.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-015 | Add role permission checks in `app/services/permission_service.py` for `discount_override`, `refund`, `stock_purchase`, `shift_close`, `system_update`, and `backup_download`. | | |
| TASK-016 | Add refund policy service in `app/services/refund_policy_service.py`; block terminal refund marking unless the cashier confirms manual terminal refund completion. | | |
| TASK-017 | Add payment reconciliation report in `app/services/reporting_service.py`: cash expected, cash counted, cash difference, manual Kaspi QR total, terminal Kaspi total, refund total, terminal refund warnings. | | |
| TASK-018 | Add tests in `tests/test_permission_service.py`, `tests/test_refund_policy_service.py`, and `tests/test_reporting_service.py` for each permission and reconciliation calculation. | | |

### Implementation Phase 5

- GOAL-005: Move reporting from useful summaries to owner-grade decision support.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-019 | Add product profitability report in `app/services/reporting_service.py`: revenue, COGS, margin, margin percent, refund-adjusted quantity, and zero-cost warning per product. | | |
| TASK-020 | Add stock forecast report in `app/services/inventory_forecast_service.py`: average daily usage per ingredient, current stock, days remaining, reorder threshold, suggested purchase qty. | | |
| TASK-021 | Add Excel sheets in `app/services/report_excel.py`: `Profitability`, `Stock Forecast`, and `Payment Reconciliation`. | | |
| TASK-022 | Add UI tabs to `/admin/reports` in `app/ui/reports.py` for profitability and stock forecast; use existing period selectors. | | |
| TASK-023 | Add tests in `tests/test_reporting_profitability.py`, `tests/test_inventory_forecast.py`, and `tests/test_report_excel.py` for generated rows and workbook sheets. | | |

### Implementation Phase 6

- GOAL-006: Reduce UI file size and make the project easier to change.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-024 | Split `app/ui/cashier.py` into `app/ui/cashier_home.py`, `app/ui/cashier_sale.py`, `app/ui/cashier_refunds.py`, and shared helpers in `app/ui/cashier_components.py`; preserve routes `/cashier`, `/cashier/sale`, `/cashier/refunds`. | | |
| TASK-025 | Split `app/ui/admin_stock.py` into `app/ui/admin_stock_items.py`, `app/ui/admin_stock_recipes.py`, `app/ui/admin_stock_categories.py`, and shared helpers in `app/ui/admin_stock_components.py`. | | |
| TASK-026 | Move remaining repeated money formatting, stock labels, and status colors from UI files into `app/ui/design.py` (already holds `money_tg`, `checks_word`, `PAYMENT_LABELS`); update UI imports. | | |
| TASK-027 | Add smoke imports for all UI pages in `tests/test_ui_imports.py`; assert `app.ui.register_pages()` imports all page modules without exception. | | |
| TASK-028 | Run `python -m py_compile app` and full pytest after each split to keep behavior unchanged. | | |

### Implementation Phase 7

- GOAL-007: Improve security and deployment readiness for real cafe operation.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-029 | Add `.env` validation in `app/config.py`: reject default `STORAGE_SECRET`, warn on missing `BOT_TOKEN`, validate `PUBLIC_URL` format, and validate backup settings. | | |
| TASK-030 | Add first-run setup wizard `/setup` that creates admin user, sets non-default PIN, validates storage secret, and disables default seed credentials when setup is complete. | | |
| TASK-031 | Add audit log model `AuditEvent` in `app/models/system.py` with actor, action, entity_type, entity_id, created_at, and metadata_json. | | |
| TASK-032 | Log audit events for product changes, stock adjustments, refunds, shift close, backup creation, and update attempts. | | |
| TASK-033 | Add tests in `tests/test_audit_log.py` and `tests/test_config_validation.py`. | | |

### Implementation Phase 8

- GOAL-008: Strengthen backup, restore, and update confidence.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-034 | Add restore validator in `app/services/backup_service.py`: verify SQLite integrity, required tables, schema version, and readable user/order counts before restore. | | |
| TASK-035 | Add admin restore page `/admin/backup/restore` that uploads a `.db` file, runs restore validation, creates pre-restore backup, and requires closed shift. | | |
| TASK-036 | Add update preflight in `app/services/updater.py`: run migration dry-check, disk-space check, Git cleanliness check, and backup freshness check before applying update. | | |
| TASK-037 | Add tests in `tests/test_backup_restore.py` and `tests/test_updater_preflight.py` for invalid backup, valid backup, open shift block, dirty Git block, and stale backup warning. | | |

### Implementation Phase 9

- GOAL-009: Package the mature POS as a Windows desktop-style application after core workflows are stable.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-038 | Add `deploy/launch-pos.ps1` that starts the FastAPI/NiceGUI server hidden, waits for `http://127.0.0.1:8080/health`, and opens the cashier UI in a dedicated Edge or Chrome app window. | | |
| TASK-039 | Add `deploy/install-desktop-shortcut.ps1` that creates one desktop shortcut named `Coffee POS` pointing to `deploy/launch-pos.ps1` with icon `deploy/coffee-pos.ico`; preserve existing `pos.db`, `.env`, and `backups/`. | | |
| TASK-040 | Add optional Windows autostart task in `deploy/install-autostart.ps1`; the task must start the server on login without a visible console window. | | |
| TASK-041 | Add build research document `docs/packaging-windows.md` comparing shortcut-based packaging, PyInstaller, Nuitka, and a full installer; choose shortcut-based packaging first and executable packaging only after Phase 8 is complete. | | |
| TASK-042 | Add future executable build script `deploy/build-windows-app.ps1` that packages the app into `dist/CoffeePOS/` only after all tests pass and restore/update workflows are complete. | | |
| TASK-043 | Add installer smoke checklist in `tests/manual/packaging-smoke.md`: clean machine install, existing machine update, reboot autostart, backup restore, one-icon launch, and no PowerShell visible to cashier. | | |

## 3. Alternatives

- **ALT-001**: Keep adding direct checks inside UI pages. Rejected because cashier, admin, tests, and Kaspi flows would drift and allow inconsistent behavior.
- **ALT-002**: Replace SQLite with PostgreSQL immediately. Rejected for the next roadmap because the current deployment target is a single Windows workstation and SQLite is operationally simpler.
- **ALT-003**: Convert the project to a JavaScript desktop app. Rejected because the current Python stack already covers FastAPI, NiceGUI, Telegram bot, Excel reports, and SQLite with a strong test suite.
- **ALT-004**: Build every future feature in one release. Rejected because inventory, reporting, security, and backup workflows can be shipped independently with lower operational risk.
- **ALT-005**: Leave schema evolution in ad hoc `ALTER TABLE` blocks forever. Rejected because the number of schema changes is increasing and each new feature needs tested, named, repeatable migrations.
- **ALT-006**: Build a Windows installer immediately. Rejected because business logic, migrations, restore, setup, and security workflows must stabilize first; early packaging would add update friction while core behavior is still changing.

## 4. Dependencies

- **DEP-001**: Python 3.13 runtime as documented in `README.md`.
- **DEP-002**: FastAPI application factory in `app/main.py::create_app`.
- **DEP-003**: NiceGUI page registration in `app/ui/__init__.py::register_pages`.
- **DEP-004**: SQLAlchemy models under `app/models`.
- **DEP-005**: SQLite production database `pos.db` with WAL sidecar files during runtime.
- **DEP-006**: Existing service modules: `app/services/sales_service.py`, `app/services/inventory_service.py`, `app/services/catalog_service.py`, `app/services/reporting_service.py`, `app/services/backup_service.py`, `app/services/updater.py`.
- **DEP-007**: Existing test runner command `.venv\Scripts\python.exe -m pytest -q`.
- **DEP-008**: Telegram bot delivery path in `app/bot/notifier.py` and notification outbox model `NotificationOutbox`.
- **DEP-009**: Kaspi terminal modules under `app/kaspi`.
- **DEP-010**: Windows launcher, shortcut, and autostart scripts under `deploy/`.
- **DEP-011**: Installed Microsoft Edge or Google Chrome for browser app or kiosk window launch.
- **DEP-012**: Optional PyInstaller or Nuitka executable packaging after Phase 8 is complete.

## 5. Files

- **FILE-001**: `app/db.py` will keep the public `init_db()` and `ensure_schema(engine)` entry points.
- **FILE-002**: `app/models/catalog.py` contains `Product`, `Category`, and modifiers.
- **FILE-003**: `app/models/inventory.py` contains stock categories, ingredients, recipes, and stock movements.
- **FILE-004**: `app/models/system.py` must be added for schema migrations and audit events.
- **FILE-005**: `app/services/migration_service.py` must be added for named schema migrations.
- **FILE-006**: `app/services/recipe_service.py` must be added for recipe CRUD.
- **FILE-007**: `app/services/supplier_service.py` must be added for supplier CRUD.
- **FILE-008**: `app/services/inventory_forecast_service.py` must be added for stock forecasting.
- **FILE-009**: `app/services/permission_service.py` must be added for role and action checks.
- **FILE-010**: `app/services/refund_policy_service.py` must be added for refund confirmation rules.
- **FILE-011**: `app/ui/purchase.py` must be changed from one-line receipt to purchase document entry.
- **FILE-012**: `app/ui/admin_stock.py` must be split after service extraction is complete.
- **FILE-013**: `app/ui/cashier.py` must be split after cashier behavior is fully covered.
- **FILE-014**: `app/ui/reports.py` must add profitability, forecast, and reconciliation views.
- **FILE-015**: `app/services/report_excel.py` must add new workbook sheets.
- **FILE-016**: `README.md` must document migrations and the restore flow.
- **FILE-017**: `tests/` must receive one focused test module per new service or major UI logic change.
- **FILE-018**: `deploy/launch-pos.ps1` must start the app and open the cashier UI as a desktop-style window.
- **FILE-019**: `deploy/install-desktop-shortcut.ps1` must create the final one-icon launcher.
- **FILE-020**: `deploy/install-autostart.ps1` must register optional Windows login startup.
- **FILE-021**: `deploy/build-windows-app.ps1` must package a future executable build only after stability gates pass.
- **FILE-022**: `docs/packaging-windows.md` must document the packaging decision and tradeoffs.
- **FILE-023**: `tests/manual/packaging-smoke.md` must document manual installer and shortcut checks.

## 6. Testing

- **TEST-001**: Run `.venv\Scripts\python.exe -m pytest -q` after every phase.
- **TEST-002**: Run `.venv\Scripts\python.exe -m py_compile app` after UI file splits.
- **TEST-003**: Add migration tests that start from old SQLite schemas and assert idempotent upgrades.
- **TEST-004**: Add service tests before UI changes for recipe service, supplier service, stock count, refund policy, permissions, forecast, and restore validation.
- **TEST-005**: Add regression tests proving a sale still goes through when a product has no recipe, no stock link, or a negative balance — stock data must never block the till.
- **TEST-006**: Add report tests that verify refund-adjusted quantities, zero-cost warnings, margin percent, payment reconciliation totals, and Excel sheet names.
- **TEST-007**: Add backup restore tests using temporary SQLite files and corrupted files.
- **TEST-008**: Add smoke tests that import all NiceGUI page modules without starting Telegram bot or external services.
- **TEST-009**: Verify one-icon launch on a clean Windows workstation.
- **TEST-010**: Verify the launcher starts the server hidden and opens the browser app window only after `/health` succeeds.
- **TEST-011**: Verify optional autostart launches the POS after reboot.
- **TEST-012**: Verify packaging and update flows do not overwrite `pos.db`, `.env`, or `backups/`.

## 7. Risks & Assumptions

- **RISK-001**: Stock figures stay approximate while recipes are incomplete; reports and forecasts must show that as a data gap, never as a reason to refuse a sale.
- **RISK-002**: Large UI files make changes risky because nested functions share mutable state.
- **RISK-003**: Manual schema migration code can drift from SQLAlchemy models if not covered by old-schema tests.
- **RISK-004**: Public access through Tailscale Funnel increases the impact of weak PINs and default setup credentials.
- **RISK-005**: Terminal Kaspi payment can succeed while local receipt creation fails; recovery workflows must be explicit.
- **RISK-006**: SQLite is suitable for one workstation but needs careful backup, restore, WAL handling, and update sequencing.
- **RISK-007**: Packaging too early can freeze unstable cashier, accounting, and stock workflows into harder-to-update install artifacts.
- **RISK-008**: PyInstaller or Nuitka packaging can break NiceGUI static assets, aiogram startup, SQLite paths, or subprocess update scripts.
- **ASSUMPTION-001**: The target deployment remains one cafe workstation with local network or Tailscale access.
- **ASSUMPTION-002**: The owner values an always-working till above strict accounting: an incomplete menu item must still be sellable, and stock gaps are reported rather than enforced (decided 2026-07-31).
- **ASSUMPTION-003**: The existing pytest suite is the mandatory regression gate before push.
- **ASSUMPTION-004**: Existing historical orders must remain reportable without depending on current product records.
- **ASSUMPTION-005**: Installer and executable work starts only after Phases 1-8 are completed or explicitly accepted as stable.

## 8. Related Specifications / Further Reading

- `README.md`
- `docs/superpowers/plans/2026-07-20-coffee-pos-stage1-foundation.md`
- `docs/superpowers/plans/2026-07-20-coffee-pos-stage2-sales.md`
- `docs/superpowers/plans/2026-07-21-coffee-pos-stage3-notifications.md`
- `docs/superpowers/plans/2026-07-22-kaspi-terminal-payment.md`
- `docs/superpowers/plans/2026-07-22-reporting.md`
- `app/services/sales_service.py`
- `app/services/inventory_service.py`
- `app/services/reporting_service.py`
- `app/services/backup_service.py`
- `app/services/updater.py`
- `deploy/install-shortcuts.ps1`
- `deploy/run-server.ps1`
- `deploy/run-kiosk.ps1`
- `deploy/coffee-pos.ico`
