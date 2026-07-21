# Демо-пакет удобства кассира — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Видимый апгрейд экранов кассы для демо: верхняя панель, планшетная вёрстка продажи, крупное подтверждение со звуком, быстрые правки чека, модальный экран ожидания Kaspi.

**Architecture:** Новый модуль `app/ui/layout.py` с двумя переиспользуемыми хелперами (`cashier_header`, `sale_success`). Правки в `app/ui/cashier.py` (`sale_page`) и подключение шапки в остальные страницы кассы. Только UI — модели/сервисы/денежная логика не меняются.

**Tech Stack:** NiceGUI 3.14 (Quasar), Python 3.13, asyncio (отмена оплаты Kaspi через задачу).

**Спека:** `docs/superpowers/specs/2026-07-22-cashier-demo-pack-design.md`

**Соглашение по тестам:** UI-страницы в проекте юнит-тестами не покрываются. Проверка каждой задачи = import-smoke (импорт модулей + `create_app(start_bot=False)`), БЕЗ запуска сервера на порту 8080 (там уже крутится демо-сервер). Итоговая проверка — полный `pytest` (ожидается 122 зелёных, ничего в сервисах не тронуто) + визуальный осмотр в браузере.

**Команда import-smoke (одна строка, PowerShell):**
```
python -c "import app.ui.layout, app.ui.cashier, app.ui.purchase; from app.main import create_app; create_app(start_bot=False); print('SMOKE OK')"
```
Ожидаемый вывод: `SMOKE OK` (плюс возможное предупреждение Telegram — не ошибка).

---

## File Structure

- **Create** `app/ui/layout.py` — переиспользуемые UI-хелперы: `cashier_header(...)` (верхняя панель), `sale_success(...)` (зелёная плашка + звук). Одна ответственность: общие элементы оформления кассы.
- **Modify** `app/ui/cashier.py` — подключить шапку в `cashier_page`/`sale_page`/`refunds_page`; переписать раскладку товаров и корзины в `sale_page`; заменить успех на `sale_success`; переписать терминальную ветку Kaspi на модальное ожидание с отменой.
- **Modify** `app/ui/purchase.py` — подключить шапку.

---

### Task 1: Модуль layout.py + подключение шапки на всех экранах кассы

**Files:**
- Create: `app/ui/layout.py`
- Modify: `app/ui/cashier.py` (импорт + вызовы `cashier_header()`)
- Modify: `app/ui/purchase.py` (импорт + вызов `cashier_header()`)

- [ ] **Step 1: Создать `app/ui/layout.py`**

```python
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
```

- [ ] **Step 2: Подключить шапку в `app/ui/cashier.py`**

Добавить импорт после строки `from app.ui.guard import current_user_id, require_user`:

```python
from app.ui.layout import cashier_header, sale_success
```

В `cashier_page` — сразу после `uid = current_user_id()` (перед `with SessionLocal() as session:`) вставить:

```python
    cashier_header()
```

В `sale_page` — сразу после `uid = current_user_id()` (перед `with SessionLocal() as session:`) вставить:

```python
    cashier_header()
```

В `refunds_page` — сразу после `uid = current_user_id()` (перед `ui.label("Возвраты")...`) вставить:

```python
    cashier_header()
```

- [ ] **Step 3: Подключить шапку в `app/ui/purchase.py`**

Прочитать начало файла, добавить импорт `from app.ui.layout import cashier_header` рядом с прочими `app.ui` импортами и вызвать `cashier_header()` первой UI-строкой в теле страницы (после проверки гварда `require_user`, если она есть; если гварда нет — первой строкой тела функции страницы).

- [ ] **Step 4: import-smoke**

Run:
```
python -c "import app.ui.layout, app.ui.cashier, app.ui.purchase; from app.main import create_app; create_app(start_bot=False); print('SMOKE OK')"
```
Expected: `SMOKE OK`

- [ ] **Step 5: Commit**

```bash
git add app/ui/layout.py app/ui/cashier.py app/ui/purchase.py
git commit -m "feat(cashier): top bar (name, shift status, home, logout) + sale-success helper"
```

---

### Task 2: Планшетная раскладка экрана продажи (вкладки категорий + плитки товаров)

**Files:**
- Modify: `app/ui/cashier.py` — блок отрисовки товаров в `sale_page` (текущие строки ~145-151, `with products_col: ... ui.button(...)`)

- [ ] **Step 1: Заменить рендер товаров на вкладки+плитки**

Заменить блок:
```python
    with products_col:
        for cat, products in menu:
            ui.label(cat.name).classes("text-xl mt-2")
            with ui.row().classes("flex-wrap gap-2"):
                for p in products:
                    ui.button(f"{p.name}\n{p.price_tiyn/100:.2f} тг",
                              on_click=lambda p=p: add_to_cart(p)).classes("w-40 h-20")
```
на:
```python
    with products_col:
        if not menu:
            ui.label("Меню пустое").classes("text-gray-500")
        else:
            with ui.tabs().classes("w-full") as cat_tabs:
                for cat, _ in menu:
                    ui.tab(name=str(cat.id), label=cat.name)
            with ui.tab_panels(cat_tabs, value=str(menu[0][0].id)).classes("w-full"):
                for cat, products in menu:
                    with ui.tab_panel(str(cat.id)):
                        with ui.grid(columns=3).classes("w-full gap-3"):
                            for p in products:
                                card = ui.card().classes(
                                    "w-full h-28 items-center justify-center cursor-pointer "
                                    "p-2 hover:bg-blue-50 transition"
                                )
                                card.on("click", lambda p=p: add_to_cart(p))
                                with card:
                                    ui.label(p.name).classes("text-lg font-bold text-center leading-tight")
                                    ui.label(f"{p.price_tiyn/100:.0f} тг").classes("text-base text-gray-600")
```

- [ ] **Step 2: import-smoke**

Run:
```
python -c "import app.ui.cashier; from app.main import create_app; create_app(start_bot=False); print('SMOKE OK')"
```
Expected: `SMOKE OK`

- [ ] **Step 3: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat(cashier): tablet sale layout — category tabs and large product tiles"
```

---

### Task 3: Крупная корзина, «Очистить чек», крупные степперы, плашка успеха

**Files:**
- Modify: `app/ui/cashier.py` — функция `render_cart` в `sale_page` (текущие строки ~170-196) и финал успеха в `confirm_payment` (строки ~349-352)

- [ ] **Step 1: Переписать `render_cart`**

Заменить тело `render_cart` на:
```python
    def render_cart() -> None:
        cart_col.clear()
        with cart_col:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Чек").classes("text-2xl font-bold")
                if cart:
                    ui.button("Очистить чек", icon="delete",
                              on_click=clear_cart).props("flat color=red")
            if not cart:
                ui.label("Пусто").classes("text-gray-500 text-lg")
            for idx, c in enumerate(cart):
                label = c["name"] + (f" [{', '.join(c['mod_labels'])}]" if c["mod_labels"] else "")
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.label(label).classes("flex-1 text-lg")

                    def dec(i=idx) -> None:
                        cart[i]["qty"] -= 1
                        if cart[i]["qty"] <= 0:
                            cart.pop(i)
                        render_cart()

                    def inc(i=idx) -> None:
                        cart[i]["qty"] += 1
                        render_cart()

                    ui.button("−", on_click=dec).props("round").classes("text-xl")
                    ui.label(f"{c['qty']}").classes("text-xl font-bold w-8 text-center")
                    ui.button("+", on_click=inc).props("round").classes("text-xl")
            ui.separator()
            ui.label(f"Итого: {cart_total_tiyn()/100:.0f} тг").classes("text-2xl font-bold")
            if cart:
                ui.button("Оплата", on_click=open_payment).classes("w-full h-16 text-xl")
```

- [ ] **Step 2: Добавить `clear_cart` рядом с `render_cart`**

Сразу перед `def render_cart() -> None:` вставить:
```python
    def clear_cart() -> None:
        cart.clear()
        render_cart()
```

- [ ] **Step 3: Использовать `sale_success` в обычном (не терминальном) успехе**

Заменить хвост `confirm_payment`:
```python
                dialog.close()
                cart.clear()
                render_cart()
                msg = f"Заказ №{num} проведён."
                if change:
                    msg += f" Сдача: {change/100:.2f} тг"
                ui.notify(msg, color="green")
```
на:
```python
                dialog.close()
                cart.clear()
                render_cart()
                extra = f"Сдача: {change/100:.0f} тг" if change else ""
                sale_success(num, extra)
```

- [ ] **Step 4: import-smoke**

Run:
```
python -c "import app.ui.cashier; from app.main import create_app; create_app(start_bot=False); print('SMOKE OK')"
```
Expected: `SMOKE OK`

- [ ] **Step 5: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat(cashier): bigger cart, clear-cart button, large steppers, success banner"
```

---

### Task 4: Модальный экран ожидания Kaspi с отменой

**Files:**
- Modify: `app/ui/cashier.py` — терминальная ветка `confirm_payment` (строки ~254-303) + импорт `asyncio`

- [ ] **Step 1: Добавить импорт asyncio**

В начало файла (первой строкой, до `from nicegui import ui`) добавить:
```python
import asyncio
```

- [ ] **Step 2: Переписать терминальную ветку**

Заменить блок (от `# Терминальная Kaspi-оплата: только как единственный способ (не в split)` до `finally: submit_btn.enable()` включительно) на:
```python
                # Терминальная Kaspi-оплата: только как единственный способ (не в split)
                if not split.value and method.value == "kaspi_terminal":
                    if total % 100 != 0:
                        ui.notify("Kaspi принимает только целые тенге", color="red")
                        return
                    submit_btn.disable()  # защита от повторного нажатия во время оплаты
                    pay_task: asyncio.Task | None = None
                    with ui.dialog().props("persistent") as wait_dialog, \
                            ui.card().classes("items-center p-8 gap-4"):
                        ui.spinner(size="4rem")
                        ui.label("Ожидание оплаты на терминале…").classes("text-xl font-bold")
                        ui.label(f"К оплате: {total/100:.0f} тг").classes("text-2xl")
                        ui.label("Клиент сканирует QR или прикладывает карту").classes("text-gray-600")
                        ui.button("Отменить", color="red",
                                  on_click=lambda: pay_task.cancel() if pay_task else None)
                    wait_dialog.open()
                    try:
                        async def _run_pay():
                            with SessionLocal() as s:
                                return await kaspi_service.pay(s, total)

                        pay_task = asyncio.create_task(_run_pay())
                        try:
                            result = await pay_task
                        except asyncio.CancelledError:
                            wait_dialog.close()
                            ui.notify("Оплата отменена. Если клиент уже оплатил — проверьте статус на терминале.",
                                      color="orange")
                            return
                        except (ValueError, KaspiError) as e:
                            wait_dialog.close()
                            ui.notify(str(e), color="red")
                            return
                        except Exception:
                            wait_dialog.close()
                            ui.notify("Ошибка связи с терминалом. Чек не проведён.", color="red")
                            return
                        wait_dialog.close()
                        if result.status != "success":
                            ui.notify(result.message or "Оплата не подтверждена терминалом. Чек не проведён.",
                                      color="red")
                            return
                        try:
                            with SessionLocal() as s:
                                lines = [sales.SaleLineInput(product_id=c["product_id"], qty=c["qty"],
                                                             modifier_ids=c["modifier_ids"]) for c in cart]
                                order = sales.create_sale(
                                    s, cashier_id=uid, lines=lines,
                                    payments=[PaymentInput("kaspi_terminal", total, None,
                                                           provider="terminal",
                                                           terminal_method=result.terminal_method,
                                                           transaction_id=result.transaction_id)],
                                )
                                num = order.number
                        except Exception as e:
                            # деньги уже ушли: закрываем диалог и чистим корзину, чтобы кассир не пробил повторно
                            dialog.close()
                            cart.clear()
                            render_cart()
                            ui.notify(f"Оплата прошла, но чек не сохранён ({e}). Запишите заказ вручную.",
                                      color="red")
                            return
                        dialog.close()
                        cart.clear()
                        render_cart()
                        sale_success(num, f"Kaspi ({result.terminal_method})")
                        return
                    finally:
                        submit_btn.enable()
```

- [ ] **Step 3: import-smoke**

Run:
```
python -c "import app.ui.cashier; from app.main import create_app; create_app(start_bot=False); print('SMOKE OK')"
```
Expected: `SMOKE OK`

- [ ] **Step 4: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat(cashier): Kaspi waiting modal with spinner, amount and cancel"
```

---

### Task 5: Итоговая проверка

- [ ] **Step 1: Полный регресс**

Run: `python -m pytest -q`
Expected: все тесты зелёные (ориентир 122 passed), новых падений нет.

- [ ] **Step 2: Финальный import-smoke**

Run:
```
python -c "import app.ui.layout, app.ui.cashier, app.ui.purchase; from app.main import create_app; create_app(start_bot=False); print('SMOKE OK')"
```
Expected: `SMOKE OK`

- [ ] **Step 3: Визуальная проверка (владелец)**

Перезапустить демо-сервер и вручную проверить: шапку на всех экранах, вкладки категорий и плитки, добавление в чек, «Очистить чек», крупные степперы, оплату наличными → зелёную плашку со звуком, ветку Kaspi-терминала → модальное ожидание с «Отменить».

---

## Self-Review

**Spec coverage:**
- П.1 Верхняя панель → Task 1 (`cashier_header` + подключение в 4 экрана). ✓
- П.2 Планшетный экран → Task 2 (вкладки + плитки) и Task 3 (крупная корзина/оплата). ✓
- П.3 Подтверждение + звук → Task 1 (`sale_success`) + Task 3/4 (вызовы). ✓
- П.4 Быстрые правки → Task 3 (очистить чек, крупные степперы). ✓
- П.5 Экран ожидания Kaspi → Task 4 (модальное + отмена через asyncio.Task). ✓

**Placeholder scan:** плейсхолдеров нет; весь код приведён целиком.

**Type consistency:** `cashier_header()`/`sale_success(order_number, extra="")` определены в Task 1 и вызываются с этой сигнатурой в Task 3/4. `clear_cart`/`render_cart`/`cart_total_tiyn`/`open_payment` — существующие/добавляемые в одном скоупе `sale_page`. Терминальная ветка сохраняет прежние имена (`kaspi_service.pay`, `sales.create_sale`, `PaymentInput`, `result.terminal_method/transaction_id`).

**Примечание по отмене Kaspi:** `pay_task.cancel()` прерывает ожидание на нашей стороне; терминал может завершить платёж самостоятельно — поэтому сообщение об отмене просит проверить статус на терминале. Чек создаётся только после `status=="success"`, денежный инвариант сохранён.
