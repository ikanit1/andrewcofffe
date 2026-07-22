# Дизайн: отчётность за период + экспорт в Excel

Дата: 2026-07-22
Статус: утверждён владельцем

## Цель

Закрыть раздел ТЗ 4.7 (отчётность) и «произвольный период» из 4.8: пять отчётов за
выбранный период с экспортом в Excel, доступные администратору. Только чтение и агрегация
существующих данных — логика продаж/возвратов не меняется.

## Ключевые решения (утверждены)

- **Возвраты** учитываются **раздельно**: отчёты показывают валовые продажи + отдельную
  строку «Возвраты»; чистая = продажи − возвраты. В «Топе товаров» количество —
  чистое (`qty − refunded_qty`).
- **Первый кусок — все 5 отчётов** + Excel.
- Экспорт — `openpyxl` (новая зависимость), одна книга, лист на отчёт.

## Данные (уже есть в БД)

- `Order(created_at, shift_id, status, total_tiyn, cost_tiyn, discount_tiyn)`.
- `OrderItem(order_id, product_id, name, qty, line_total_tiyn, unit_cost_tiyn, refunded_qty)`.
- `Payment(order_id, method, amount_tiyn, created_at)`.
- `Refund(amount_tiyn, cashier_id, created_at)`.
- `Shift(cashier_id, opened_at, closed_at, status)`, `User(name)`, `Category(name)`.

## Архитектура (3 слоя)

### 1. `app/services/reporting_service.py` — агрегации (чистые, тестируемые)

Общий тип периода и хелперы:
```python
@dataclass
class Period:
    start: datetime  # aware UTC, включительно
    end: datetime    # aware UTC, исключительно

def period_from_preset(preset: str, now: datetime | None = None) -> Period: ...
    # preset ∈ {"today","yesterday","week","month"}; границы дня по Asia/Almaty
def period_from_dates(start_date: date, end_date: date) -> Period: ...
    # [start 00:00 Almaty, end+1 00:00 Almaty)
```

Функции (каждая `(session, period) -> dataclass`), фильтр по `created_at` в `[start, end)`:

- `revenue_by_method(session, period) -> RevenueByMethod`
  - `by_method: dict[str, int]` — сумма `Payment.amount_tiyn` по `method`.
  - `orders_count: int` — число заказов периода.
  - `gross_tiyn` — сумма всех способов; `refunds_tiyn` — сумма `Refund.amount_tiyn`;
    `net_tiyn = gross − refunds`.
- `top_products(session, period, limit=20) -> list[ProductRow]`
  - `ProductRow(name, qty_sold, qty_refunded, qty_net, revenue_tiyn)`;
    `qty_net = qty_sold − qty_refunded`; `revenue_tiyn = Σ line_total_tiyn` (валовая).
  - Сортировка по `revenue_tiyn` убыв., срез `limit`.
- `revenue_by_category(session, period) -> list[CategoryRow]`
  - `CategoryRow(category, revenue_tiyn, qty_net)`; товар с `product_id IS NULL` или без
    категории → «Без категории». Сортировка по выручке убыв.
- `cost_and_margin(session, period) -> CostMargin`
  - `revenue_tiyn = Σ Order.total_tiyn`, `cogs_tiyn = Σ Order.cost_tiyn`,
    `margin_tiyn = revenue − cogs`, `margin_pct = margin/revenue*100` (0 при revenue=0),
    `refunds_tiyn`, `net_revenue_tiyn = revenue − refunds`.
  - Примечание: COGS в этом упрощении не уменьшается на возвраты (снимок себестоимости
    на момент продажи) — осознанное упрощение первого куска.
- `shifts_and_cashiers(session, period) -> ShiftsReport`
  - Смены с `opened_at` в периоде. `ShiftRow(shift_id, cashier_name, opened_at,
    closed_at, orders_count, revenue_tiyn, cogs_tiyn, margin_tiyn)`.
  - `by_cashier: list[CashierRow(cashier_name, shifts_count, orders_count, revenue_tiyn,
    margin_tiyn)]` — сводка по кассиру.

### 2. `app/services/report_excel.py` — сборка книги

```python
def build_reports_workbook(period, rev, top, cats, margin, shifts) -> bytes
```
- `openpyxl.Workbook`, по листу на отчёт: «Способы оплаты», «Топ товаров», «Категории»,
  «Маржа», «Смены». Первый лист — период и краткая сводка (продажи/возвраты/чистая/маржа).
- Деньги пишутся в тенге (`tiyn/100`, число). Заголовки столбцов — жирным.
- Возвращает `wb`-байты (`io.BytesIO`).

### 3. `app/ui/reports.py` — страница `/admin/reports`

- `admin_header()` + заголовок «Отчёты».
- Панель периода: `ui.toggle({"today","yesterday","week","month","custom"})` + при
  «custom» — два `ui.date` (с/по). Кнопка «Показать».
- Кнопка **«Скачать Excel»** → `ui.download(build_reports_workbook(...),
  f"Отчёт_{start:%Y%m%d}-{end:%Y%m%d}.xlsx")`.
- Пять секций-таблиц (`ui.table` или строки) с форматированием тенге.
- Плитка «📈 Отчёты» → `/admin/reports` добавляется в `app/ui/admin_home.py`.

## Обработка ошибок и краёв

- Пустой период — таблицы показывают «Нет данных за период»; Excel формируется с
  заголовками и нулями.
- `end < start` в «custom» — `ui.notify(..., red)`, отчёт не строится.
- `margin_pct` при нулевой выручке — 0 (без деления на ноль).
- Заказы с `product_id IS NULL` (снятый товар) — в «Категориях» идут в «Без категории»,
  в «Топе» — по снимку названия `OrderItem.name`.

## Тестирование

Юнит-тесты (pytest) на временной файловой SQLite с наполнением (смены/заказы/позиции/
оплаты/возвраты):
- `period_from_preset`/`period_from_dates` — границы дня в Almaty (в т.ч. «вчера», месяц).
- `revenue_by_method` — суммы по способам, `net = gross − refunds`, `orders_count`.
- `top_products` — `qty_net = qty − refunded_qty`, сортировка, `limit`.
- `revenue_by_category` — суммы по категориям, «Без категории» для `product_id IS NULL`.
- `cost_and_margin` — `margin = revenue − cogs`, `margin_pct`, `net_revenue`.
- `shifts_and_cashiers` — построчно и сводка по кассиру.
- `report_excel` — собрать книгу из образца, снова открыть `openpyxl`, проверить имена
  листов и несколько ячеек (суммы в тенге).
- Страница `/admin/reports` — только import-smoke.

Полный регресс остаётся зелёным (текущий ориентир — 130 + новые).

## Вне рамок

X-отчёт (текущая смена без закрытия), экспорт в Google-таблицу (нужен коннектор), графики/
диаграммы, вычет возвратов построчно из COGS, отчёты по скидкам. — следующие итерации.
