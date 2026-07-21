# Хвосты интерфейса кассира — частичный возврат, разделение оплаты — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в экран кассира частичный возврат по позициям чека и разделение
оплаты на два способа — обе возможности уже реализованы и протестированы в сервисном
слое (`sales_service`), в интерфейсе не выведены.

**Architecture:** Только правки `app/ui/cashier.py`. Новых моделей, сервисов и
сервисных тестов не требуется — оба таска добавляют UI-обвязку вокруг уже
существующих вызовов `sales_service.refund_sale(item_qty=...)` и
`sales_service.create_sale(payments=[...])`.

**Tech Stack:** Python, NiceGUI 3.14.

**Спецификация:** `docs/superpowers/specs/2026-07-22-cashier-ui-tails-design.md`

---

## Структура файлов

```
app/ui/cashier.py   # ИЗМЕНИТЬ: refunds_page (частичный возврат), sale_page/open_payment (разделение оплаты)
README.md            # ИЗМЕНИТЬ: упомянуть обе новые возможности в разделе «Работа кассира»
```

---

### Task 1: Частичный возврат по позициям

**Files:**
- Modify: `app/ui/cashier.py` (функция `refunds_page`, строки 243-298 на момент
  написания плана)

Логика возврата (`sales_service.refund_sale`, включая расчёт суммы, обновление
`refunded_qty`, восстановление штучных товаров на склад, ошибки валидации) уже
покрыта тестами `tests/test_sales_service.py`. Эта задача — только UI, проверяется
регрессом полного набора + ручным рендером страницы.

- [ ] **Step 1: Добавить кнопку «Частичный возврат» и новый диалог**

В `app/ui/cashier.py`, функция `refresh()` внутри `refunds_page` — заменить блок:
```python
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"№{o.number}: {names} — {o.total_tiyn/100:.2f} тг").classes("flex-1")
                    ui.button("Вернуть полностью",
                              on_click=lambda oid=o.id: _do_full_refund(oid))
```
на:
```python
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"№{o.number}: {names} — {o.total_tiyn/100:.2f} тг").classes("flex-1")
                    ui.button("Вернуть полностью",
                              on_click=lambda oid=o.id: _do_full_refund(oid))
                    ui.button("Частичный возврат",
                              on_click=lambda oid=o.id: _do_partial_refund(oid))
```

Сразу после функции `_do_full_refund` (перед `refresh()` в самом конце файла функции
`refunds_page`, то есть между `_do_full_refund` и финальным вызовом `refresh()`)
добавить новую функцию:
```python
    def _do_partial_refund(order_id: int) -> None:
        with SessionLocal() as session:
            items = session.query(OrderItem).filter_by(order_id=order_id).all()
        remaining = [(it, it.qty - it.refunded_qty) for it in items if it.qty - it.refunded_qty > 0]

        with ui.dialog() as dialog, ui.card():
            ui.label("Частичный возврат").classes("text-lg")
            if not remaining:
                ui.label("Нечего возвращать").classes("text-gray-500")
                ui.button("Закрыть", on_click=dialog.close)
                dialog.open()
                return

            qty_inputs: dict[int, object] = {}
            for it, rem in remaining:
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"{it.name} (куплено {it.qty}, доступно к возврату {rem})").classes("flex-1")
                    q = ui.number("Вернуть", value=0, min=0, max=rem, format="%.0f")
                    qty_inputs[it.id] = q

            reason = ui.input("Причина")

            def confirm() -> None:
                if not reason.value or not reason.value.strip():
                    ui.notify("Укажите причину", color="red")
                    return
                item_qty = {
                    item_id: round(q.value)
                    for item_id, q in qty_inputs.items()
                    if q.value and q.value > 0
                }
                if not item_qty:
                    ui.notify("Выберите хотя бы одну позицию", color="red")
                    return
                try:
                    with SessionLocal() as s:
                        sales.refund_sale(s, order_id=order_id, cashier_id=uid,
                                          reason=reason.value, item_qty=item_qty)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dialog.close()
                ui.notify("Возврат оформлен", color="green")
                refresh()

            ui.button("Оформить возврат", on_click=confirm, color="red")
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()
```

- [ ] **Step 2: Запустить тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (93 теста — новых тестов эта задача не добавляет, логика уже
покрыта на уровне `sales_service`)

- [ ] **Step 3: Ручная проверка**

1. Запустить `.venv\Scripts\python -m app.main`.
2. Войти кассиром (пин `1234`), открыть смену, провести продажу из 2+ позиций с
   количеством > 1 хотя бы у одной позиции (например, Латте ×2).
3. Открыть «Возвраты» → нажать «Частичный возврат» на этом заказе.
4. Убедиться: диалог показывает все позиции с полем «Вернуть» (max = остаток).
5. Ввести 0 везде и нажать «Оформить возврат» — должно появиться уведомление
   «Выберите хотя бы одну позицию», возврат не создаётся.
6. Ввести 1 в поле Латте, не указывая причину — уведомление «Укажите причину».
7. Указать причину, вернуть 1 из 2 Латте — уведомление «Возврат оформлен», статус
   заказа должен стать `partially_refunded` (проверить на `/admin/dashboard` —
   выручка за сегодня должна уменьшиться ровно на сумму возврата).
8. Открыть диалог возврата по тому же заказу повторно — убедиться, что доступный
   остаток по Латте теперь 1 (не 2).
9. Остановить сервер.

- [ ] **Step 4: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat: partial refund by item in cashier UI"
```

---

### Task 2: Разделение оплаты на два способа

**Files:**
- Modify: `app/ui/cashier.py` (функция `open_payment` внутри `sale_page`, строки
  196-237 на момент написания плана)

Расчёт итога, сдачи и сама атомарная продажа с несколькими `Payment` уже покрыты
тестами (`tests/test_sales_service.py::test_split_payment_and_change`). Эта задача —
только UI.

- [ ] **Step 1: Заменить функцию `open_payment`**

Полностью заменить текущую функцию `open_payment` (от `def open_payment() -> None:`
до закрывающего `dialog.open()` перед определением `ui.button("← К смене", ...)`) на:
```python
    def open_payment() -> None:
        total = cart_total_tiyn()
        with ui.dialog() as dialog, ui.card():
            ui.label(f"К оплате: {total/100:.2f} тг").classes("text-xl")
            split = ui.checkbox("Разделить оплату")

            single_col = ui.column()
            with single_col:
                method = ui.select({"cash": "Наличные", "card": "Карта", "kaspi_qr": "Kaspi QR"},
                                   label="Способ", value="cash")
                tendered = ui.number("Получено (наличные), тг", value=total / 100, format="%.0f")

            split_col = ui.column()
            with split_col:
                method_a = ui.select({"cash": "Наличные", "card": "Карта", "kaspi_qr": "Kaspi QR"},
                                     label="Способ 1", value="cash")
                amount_a = ui.number("Сумма способа 1, тг", value=0, min=0, format="%.0f")
                tendered_a = ui.number("Получено (наличные) способ 1, тг", value=0, format="%.0f")
                method_b = ui.select({"cash": "Наличные", "card": "Карта", "kaspi_qr": "Kaspi QR"},
                                     label="Способ 2", value="card")
                amount_b_label = ui.label("")
                tendered_b = ui.number("Получено (наличные) способ 2, тг", value=0, format="%.0f")

            def refresh_split() -> None:
                remainder = max(total - round((amount_a.value or 0) * 100), 0)
                amount_b_label.set_text(f"Сумма способа 2: {remainder / 100:.2f} тг")
                tendered_a.set_visibility(method_a.value == "cash")
                tendered_b.set_visibility(method_b.value == "cash")

            def toggle_mode() -> None:
                single_col.set_visibility(not split.value)
                split_col.set_visibility(split.value)
                if split.value:
                    refresh_split()

            split.on_value_change(lambda e: toggle_mode())
            amount_a.on_value_change(lambda e: refresh_split())
            method_a.on_value_change(lambda e: refresh_split())
            method_b.on_value_change(lambda e: refresh_split())
            toggle_mode()

            def _cash_payment(method_name: str, amount_tiyn: int, tendered_field) -> PaymentInput | None:
                if method_name != "cash":
                    return PaymentInput(method_name, amount_tiyn, None)
                tnd = round((tendered_field.value or 0) * 100)
                if tnd < amount_tiyn:
                    ui.notify("Получено меньше суммы по наличному способу", color="red")
                    return None
                return PaymentInput("cash", amount_tiyn, tnd)

            def confirm_payment() -> None:
                if split.value:
                    amt_a = round((amount_a.value or 0) * 100)
                    if amt_a <= 0 or amt_a >= total:
                        ui.notify("Сумма способа 1 должна быть больше 0 и меньше итога", color="red")
                        return
                    amt_b = total - amt_a
                    pay_a = _cash_payment(method_a.value, amt_a, tendered_a)
                    if pay_a is None:
                        return
                    pay_b = _cash_payment(method_b.value, amt_b, tendered_b)
                    if pay_b is None:
                        return
                    payments = [pay_a, pay_b]
                    change = sum(
                        (p.tendered_tiyn - p.amount_tiyn) for p in payments
                        if p.method == "cash" and p.tendered_tiyn is not None
                    )
                else:
                    pay_method = method.value
                    if pay_method == "cash":
                        tnd = round((tendered.value or 0) * 100)
                        if tnd < total:
                            ui.notify("Получено меньше суммы чека", color="red")
                            return
                        payments = [PaymentInput("cash", total, tnd)]
                        change = tnd - total
                    else:
                        payments = [PaymentInput(pay_method, total, None)]
                        change = 0
                try:
                    with SessionLocal() as s:
                        lines = [sales.SaleLineInput(product_id=c["product_id"], qty=c["qty"],
                                                     modifier_ids=c["modifier_ids"]) for c in cart]
                        order = sales.create_sale(s, cashier_id=uid, lines=lines, payments=payments)
                        num = order.number
                except (ValueError, PermissionError) as e:
                    ui.notify(str(e), color="red")
                    return
                except Exception:
                    ui.notify("Не удалось провести чек. Ничего не списано, попробуйте ещё раз.", color="red")
                    return
                dialog.close()
                cart.clear()
                render_cart()
                msg = f"Заказ №{num} проведён."
                if change:
                    msg += f" Сдача: {change/100:.2f} тг"
                ui.notify(msg, color="green")

            ui.button("Провести", on_click=confirm_payment)
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()
```

Если NiceGUI 3.14 отвергнет `.set_visibility(bool)` на `ui.column()`/`ui.number()`/
`ui.label()` (маловероятно — это штатный метод `Element`), адаптировать минимально
(например, через `.style("display: none" if not visible else "")`) и отметить
отклонение в отчёте.

- [ ] **Step 2: Запустить тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 3: Ручная проверка**

1. Запустить `.venv\Scripts\python -m app.main`.
2. Войти кассиром, открыть смену, на экране продажи собрать корзину (например, 2
   Латте по 1500 тг = 3000 тг).
3. Нажать «Оплата» — без галочки «Разделить оплату» убедиться, что поведение как
   раньше (один способ, наличные считают сдачу).
4. Включить «Разделить оплату» — должны появиться поля «Способ 1»/«Сумма способа 1»/
   «Способ 2», однострочный «Способа 1» скрыться.
5. Ввести сумму способа 1 меньше итога (например 1000 тг при итоге 3000 тг) —
   убедиться, что подпись «Сумма способа 2» показывает 2000.00 тг и обновляется
   при изменении первого поля.
6. Оставить способ 1 = «Наличные» — должно появиться поле «Получено способ 1»;
   переключить способ 1 на «Карта» — поле должно скрыться.
7. Нажать «Провести» с суммой способа 1 = 0 — уведомление о недопустимой сумме,
   чек не проводится.
8. Провести реальный сплит (например, 1000 тг наличными с получением 1000,
   2000 тг картой) — чек должен провестись, в `/admin/dashboard` — выручка за
   сегодня вырасти на 3000 тг.
9. Проверить в БД (или по логике теста `test_split_payment_and_change`), что
   создались два `Payment` — необязательно вручную, если шаг 8 прошёл успешно и
   сумма на дашборде верна, значит оба `Payment` учтены.
10. Остановить сервер.

- [ ] **Step 4: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat: split payment across two methods in sale screen"
```

---

### Task 3: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Обновить раздел «Работа кассира»**

Найти строку:
```markdown
5. Возвраты — на отдельном экране, с указанием причины.
```
и заменить на:
```markdown
5. Возвраты — на отдельном экране: «Вернуть полностью» либо «Частичный возврат»
   (выбор количества по каждой позиции), с указанием причины.
```

Найти строку:
```markdown
4. Экран продажи: категория → товар → (модификаторы) → корзина → «Оплата»
   (наличные со сдачей, карта или Kaspi QR).
```
и заменить на:
```markdown
4. Экран продажи: категория → товар → (модификаторы) → корзина → «Оплата»
   (наличные со сдачей, карта или Kaspi QR; можно разделить оплату на два способа
   галочкой «Разделить оплату»).
```

- [ ] **Step 2: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: mention partial refund and split payment in README"
```

---

## Самопроверка плана

- **Покрытие спецификации:** частичный возврат по позициям — задача 1; разделение
  оплаты на два способа — задача 2; README — задача 3. Скидка в UI явно не входит ни
  в одну задачу (по решению владельца).
- **Согласованность типов/сигнатур:** `sales_service.refund_sale(item_qty=dict[int,int])`
  и `sales_service.create_sale(payments=list[PaymentInput])` используются в задачах 1
  и 2 без изменений сигнатур — оба уже существуют и протестированы с этапа 2.
  `PaymentInput(method, amount_tiyn, tendered_tiyn=None)` — конструктор не меняется.
- **Плейсхолдеров нет** — весь код задач 1 и 2 приведён полностью, без «TODO» и
  отсылок к «как в задаче N».
- **Новых сервисных тестов не требуется** — обе задачи UI-only, регресс полного
  набора (93/93) и ручная проверка — единственная верификация, как и для прочих
  UI-задач в этом проекте (`admin_dashboard.py`, `purchase.py` и т.д. тоже без
  собственных unit-тестов).
