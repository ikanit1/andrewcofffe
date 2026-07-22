# Отчётность за период + Excel — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Пять отчётов за выбранный период (выручка по способам, топ товаров, по категориям, себестоимость/маржа, смены/кассиры) с экспортом в Excel на странице `/admin/reports`.

**Architecture:** Три слоя: `reporting_service` (чистые агрегации → dataclass), `report_excel` (openpyxl → bytes), `ui/reports.py` (страница). Только чтение; логика продаж не меняется.

**Tech Stack:** Python 3.13, SQLAlchemy 2.x (func/group_by), openpyxl, NiceGUI, zoneinfo (Asia/Almaty).

**Спека:** `docs/superpowers/specs/2026-07-22-reporting-design.md`

**Соглашение по тестам:** сервисы покрыты pytest на временной файловой SQLite с наполнением; UI — import-smoke. Деньги в тиынах (1 тг = 100 тиын). Полный регресс остаётся зелёным (ориентир 130 + новые).

---

## File Structure

- **Create** `app/services/reporting_service.py` — Period, хелперы периода, 5 агрегаций, dataclass-результаты.
- **Create** `app/services/report_excel.py` — `build_reports_workbook(...) -> bytes`.
- **Create** `app/ui/reports.py` — страница `/admin/reports`.
- **Modify** `app/ui/admin_home.py` — плитка «Отчёты».
- **Modify** `app/ui/__init__.py` — регистрация страницы.
- **Modify** `requirements.txt` — `openpyxl`.
- **Create tests** `tests/test_reporting_service.py`, `tests/test_report_excel.py`.

---

### Task 1: Зависимость openpyxl

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Добавить в `requirements.txt`**

Добавить строку (в конец файла):
```
openpyxl
```

- [ ] **Step 2: Установить**

Run: `python -m pip install openpyxl`
Expected: `Successfully installed openpyxl-...` (или «already satisfied»)

- [ ] **Step 3: Проверить импорт**

Run: `python -c "import openpyxl; print('openpyxl', openpyxl.__version__)"`
Expected: `openpyxl <версия>`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add openpyxl for Excel report export"
```

---

### Task 2: Модуль reporting_service — Period, хелперы, dataclass-ы

**Files:**
- Create: `app/services/reporting_service.py`
- Test: `tests/test_reporting_service.py`

- [ ] **Step 1: Написать падающий тест на периоды**

Создать `tests/test_reporting_service.py`:
```python
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services import reporting_service as rs

ALMATY = ZoneInfo("Asia/Almaty")


def test_period_from_preset_today():
    now = datetime(2026, 7, 22, 10, 0, tzinfo=ALMATY)
    p = rs.period_from_preset("today", now)
    # 22 июля 00:00 Almaty == 21 июля 18:00 UTC (Almaty = UTC+6)
    assert p.start == datetime(2026, 7, 21, 18, 0, tzinfo=timezone.utc)
    assert p.end == datetime(2026, 7, 22, 18, 0, tzinfo=timezone.utc)


def test_period_from_preset_yesterday():
    now = datetime(2026, 7, 22, 10, 0, tzinfo=ALMATY)
    p = rs.period_from_preset("yesterday", now)
    assert p.start == datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)
    assert p.end == datetime(2026, 7, 21, 18, 0, tzinfo=timezone.utc)


def test_period_from_dates_inclusive_end():
    p = rs.period_from_dates(date(2026, 7, 1), date(2026, 7, 31))
    assert p.start == datetime(2026, 6, 30, 18, 0, tzinfo=timezone.utc)
    # конец — начало 1 августа Almaty (эксклюзивно)
    assert p.end == datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_reporting_service.py -q`
Expected: FAIL (нет модуля/функций)

- [ ] **Step 3: Реализовать модуль**

Создать `app/services/reporting_service.py`:
```python
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Order, OrderItem, Payment, Product, Refund, Shift, User
from app.timezone import ALMATY, now_almaty, to_almaty


@dataclass
class Period:
    start: datetime  # aware UTC, включительно
    end: datetime    # aware UTC, исключительно


def period_from_preset(preset: str, now: datetime | None = None) -> Period:
    local_now = to_almaty(now) if now is not None else now_almaty()
    today_start = datetime.combine(local_now.date(), time.min, tzinfo=ALMATY)
    today_end = today_start + timedelta(days=1)
    if preset == "today":
        s, e = today_start, today_end
    elif preset == "yesterday":
        s, e = today_start - timedelta(days=1), today_start
    elif preset == "week":
        s, e = today_start - timedelta(days=6), today_end
    elif preset == "month":
        s, e = today_start.replace(day=1), today_end
    else:
        raise ValueError(f"Неизвестный период: {preset}")
    return Period(s.astimezone(timezone.utc), e.astimezone(timezone.utc))


def period_from_dates(start_date: date, end_date: date) -> Period:
    s = datetime.combine(start_date, time.min, tzinfo=ALMATY)
    e = datetime.combine(end_date, time.min, tzinfo=ALMATY) + timedelta(days=1)
    return Period(s.astimezone(timezone.utc), e.astimezone(timezone.utc))


@dataclass
class RevenueByMethod:
    by_method: dict[str, int]
    gross_tiyn: int
    refunds_tiyn: int
    net_tiyn: int
    orders_count: int


@dataclass
class ProductRow:
    name: str
    qty_sold: int
    qty_refunded: int
    qty_net: int
    revenue_tiyn: int


@dataclass
class CategoryRow:
    category: str
    revenue_tiyn: int
    qty_net: int


@dataclass
class CostMargin:
    revenue_tiyn: int
    cogs_tiyn: int
    margin_tiyn: int
    margin_pct: float
    refunds_tiyn: int
    net_revenue_tiyn: int


@dataclass
class ShiftRow:
    shift_id: int
    cashier_name: str
    opened_at: datetime
    closed_at: datetime | None
    orders_count: int
    revenue_tiyn: int
    cogs_tiyn: int
    margin_tiyn: int


@dataclass
class CashierRow:
    cashier_name: str
    shifts_count: int
    orders_count: int
    revenue_tiyn: int
    margin_tiyn: int


@dataclass
class ShiftsReport:
    shifts: list[ShiftRow] = field(default_factory=list)
    by_cashier: list[CashierRow] = field(default_factory=list)


def _refunds_tiyn(session: Session, period: Period) -> int:
    return int(session.scalar(
        select(func.coalesce(func.sum(Refund.amount_tiyn), 0))
        .where(Refund.created_at >= period.start, Refund.created_at < period.end)
    ) or 0)
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_reporting_service.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/reporting_service.py tests/test_reporting_service.py
git commit -m "feat(reporting): Period helpers and result dataclasses"
```

---

### Task 3: Выручка по способам оплаты

**Files:**
- Modify: `app/services/reporting_service.py`
- Test: `tests/test_reporting_service.py`

- [ ] **Step 1: Добавить общий seed-хелпер и тест**

В `tests/test_reporting_service.py` добавить вверху импорты и seed-функцию:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Category, Order, OrderItem, Payment, Product, Refund, Shift, User,
)


def _seed(tmp_path):
    """Наполняет временную БД: 1 смена, 2 заказа, оплаты (нал+карта), 1 возврат."""
    engine = create_engine(f"sqlite:///{tmp_path / 'r.db'}")
    Base.metadata.create_all(engine)
    Sm = sessionmaker(bind=engine)
    # период — «сегодня» относительно фиксированного момента
    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    with Sm() as s:
        cashier = User(telegram_id=1, name="Айгуль", role="cashier", is_active=True)
        cat = Category(name="Кофе")
        s.add_all([cashier, cat]); s.flush()
        prod = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=1500)
        s.add(prod); s.flush()
        shift = Shift(cashier_id=cashier.id, opened_at=now, status="open", opening_cash_tiyn=0)
        s.add(shift); s.flush()
        # заказ 1: 2 латте, оплата наличными 3000, COGS 800
        o1 = Order(shift_id=shift.id, number=1, status="paid", subtotal_tiyn=3000,
                   total_tiyn=3000, cost_tiyn=800, created_at=now)
        s.add(o1); s.flush()
        s.add(OrderItem(order_id=o1.id, product_id=prod.id, name="Латте",
                        unit_price_tiyn=1500, qty=2, line_total_tiyn=3000,
                        unit_cost_tiyn=400, refunded_qty=1))
        s.add(Payment(order_id=o1.id, method="cash", amount_tiyn=3000, created_at=now))
        # заказ 2: 1 латте, оплата картой 1500, COGS 400
        o2 = Order(shift_id=shift.id, number=2, status="paid", subtotal_tiyn=1500,
                   total_tiyn=1500, cost_tiyn=400, created_at=now)
        s.add(o2); s.flush()
        s.add(OrderItem(order_id=o2.id, product_id=prod.id, name="Латте",
                        unit_price_tiyn=1500, qty=1, line_total_tiyn=1500,
                        unit_cost_tiyn=400, refunded_qty=0))
        s.add(Payment(order_id=o2.id, method="card", amount_tiyn=1500, created_at=now))
        # возврат 1 латте из заказа 1 — 1500
        s.add(Refund(order_id=o1.id, amount_tiyn=1500, reason="брак",
                     cashier_id=cashier.id, created_at=now))
        s.commit()
    return Sm, now


def test_revenue_by_method(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        r = rs.revenue_by_method(s, p)
    assert r.by_method == {"cash": 3000, "card": 1500}
    assert r.gross_tiyn == 4500
    assert r.refunds_tiyn == 1500
    assert r.net_tiyn == 3000
    assert r.orders_count == 2
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_reporting_service.py::test_revenue_by_method -q`
Expected: FAIL (нет `revenue_by_method`)

- [ ] **Step 3: Реализовать**

В `app/services/reporting_service.py` добавить:
```python
def revenue_by_method(session: Session, period: Period) -> RevenueByMethod:
    rows = session.execute(
        select(Payment.method, func.sum(Payment.amount_tiyn))
        .where(Payment.created_at >= period.start, Payment.created_at < period.end)
        .group_by(Payment.method)
    ).all()
    by_method = {m: int(total or 0) for m, total in rows}
    gross = sum(by_method.values())
    refunds = _refunds_tiyn(session, period)
    orders_count = int(session.scalar(
        select(func.count(Order.id))
        .where(Order.created_at >= period.start, Order.created_at < period.end)
    ) or 0)
    return RevenueByMethod(by_method=by_method, gross_tiyn=gross,
                           refunds_tiyn=refunds, net_tiyn=gross - refunds,
                           orders_count=orders_count)
```

- [ ] **Step 4: Запустить — PASS**

Run: `python -m pytest tests/test_reporting_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/reporting_service.py tests/test_reporting_service.py
git commit -m "feat(reporting): revenue by payment method"
```

---

### Task 4: Топ товаров

**Files:**
- Modify: `app/services/reporting_service.py`
- Test: `tests/test_reporting_service.py`

- [ ] **Step 1: Тест**

Добавить в `tests/test_reporting_service.py`:
```python
def test_top_products_net_qty(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        rows = rs.top_products(s, p)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "Латте"
    assert row.qty_sold == 3          # 2 + 1
    assert row.qty_refunded == 1
    assert row.qty_net == 2
    assert row.revenue_tiyn == 4500   # 3000 + 1500 (валовая)
```

- [ ] **Step 2: Запустить — FAIL**

Run: `python -m pytest tests/test_reporting_service.py::test_top_products_net_qty -q`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
def top_products(session: Session, period: Period, limit: int = 20) -> list[ProductRow]:
    rows = session.execute(
        select(
            OrderItem.name,
            func.sum(OrderItem.qty),
            func.sum(OrderItem.refunded_qty),
            func.sum(OrderItem.line_total_tiyn),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.created_at >= period.start, Order.created_at < period.end)
        .group_by(OrderItem.name)
    ).all()
    result = [
        ProductRow(name=name, qty_sold=int(qty), qty_refunded=int(refunded),
                   qty_net=int(qty) - int(refunded), revenue_tiyn=int(revenue))
        for name, qty, refunded, revenue in rows
    ]
    result.sort(key=lambda r: r.revenue_tiyn, reverse=True)
    return result[:limit]
```

- [ ] **Step 4: PASS**

Run: `python -m pytest tests/test_reporting_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/reporting_service.py tests/test_reporting_service.py
git commit -m "feat(reporting): top products with net quantity"
```

---

### Task 5: Выручка по категориям

**Files:**
- Modify: `app/services/reporting_service.py`
- Test: `tests/test_reporting_service.py`

- [ ] **Step 1: Тест**

```python
def test_revenue_by_category(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        rows = rs.revenue_by_category(s, p)
    assert len(rows) == 1
    assert rows[0].category == "Кофе"
    assert rows[0].revenue_tiyn == 4500
    assert rows[0].qty_net == 2       # 3 продано − 1 возврат
```

- [ ] **Step 2: FAIL**

Run: `python -m pytest tests/test_reporting_service.py::test_revenue_by_category -q`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
def revenue_by_category(session: Session, period: Period) -> list[CategoryRow]:
    rows = session.execute(
        select(
            Category.name,
            func.sum(OrderItem.line_total_tiyn),
            func.sum(OrderItem.qty - OrderItem.refunded_qty),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .outerjoin(Product, OrderItem.product_id == Product.id)
        .outerjoin(Category, Product.category_id == Category.id)
        .where(Order.created_at >= period.start, Order.created_at < period.end)
        .group_by(Category.name)
    ).all()
    result = [
        CategoryRow(category=(name or "Без категории"),
                    revenue_tiyn=int(revenue), qty_net=int(qty_net))
        for name, revenue, qty_net in rows
    ]
    result.sort(key=lambda c: c.revenue_tiyn, reverse=True)
    return result
```

- [ ] **Step 4: PASS**

Run: `python -m pytest tests/test_reporting_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/reporting_service.py tests/test_reporting_service.py
git commit -m "feat(reporting): revenue by category"
```

---

### Task 6: Себестоимость и маржа

**Files:**
- Modify: `app/services/reporting_service.py`
- Test: `tests/test_reporting_service.py`

- [ ] **Step 1: Тест**

```python
def test_cost_and_margin(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        m = rs.cost_and_margin(s, p)
    assert m.revenue_tiyn == 4500     # 3000 + 1500
    assert m.cogs_tiyn == 1200        # 800 + 400
    assert m.margin_tiyn == 3300
    assert m.margin_pct == 73.3       # round(3300/4500*100, 1)
    assert m.refunds_tiyn == 1500
    assert m.net_revenue_tiyn == 3000
```

- [ ] **Step 2: FAIL**

Run: `python -m pytest tests/test_reporting_service.py::test_cost_and_margin -q`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
def cost_and_margin(session: Session, period: Period) -> CostMargin:
    revenue = int(session.scalar(
        select(func.coalesce(func.sum(Order.total_tiyn), 0))
        .where(Order.created_at >= period.start, Order.created_at < period.end)
    ) or 0)
    cogs = int(session.scalar(
        select(func.coalesce(func.sum(Order.cost_tiyn), 0))
        .where(Order.created_at >= period.start, Order.created_at < period.end)
    ) or 0)
    refunds = _refunds_tiyn(session, period)
    margin = revenue - cogs
    margin_pct = round(margin / revenue * 100, 1) if revenue else 0.0
    return CostMargin(revenue_tiyn=revenue, cogs_tiyn=cogs, margin_tiyn=margin,
                      margin_pct=margin_pct, refunds_tiyn=refunds,
                      net_revenue_tiyn=revenue - refunds)
```

- [ ] **Step 4: PASS**

Run: `python -m pytest tests/test_reporting_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/reporting_service.py tests/test_reporting_service.py
git commit -m "feat(reporting): cost and margin"
```

---

### Task 7: Смены и кассиры

**Files:**
- Modify: `app/services/reporting_service.py`
- Test: `tests/test_reporting_service.py`

- [ ] **Step 1: Тест**

```python
def test_shifts_and_cashiers(tmp_path):
    Sm, now = _seed(tmp_path)
    p = rs.period_from_preset("today", now)
    with Sm() as s:
        rep = rs.shifts_and_cashiers(s, p)
    assert len(rep.shifts) == 1
    sh = rep.shifts[0]
    assert sh.cashier_name == "Айгуль"
    assert sh.orders_count == 2
    assert sh.revenue_tiyn == 4500
    assert sh.margin_tiyn == 3300
    assert len(rep.by_cashier) == 1
    c = rep.by_cashier[0]
    assert c.cashier_name == "Айгуль"
    assert c.shifts_count == 1
    assert c.orders_count == 2
    assert c.revenue_tiyn == 4500
    assert c.margin_tiyn == 3300
```

- [ ] **Step 2: FAIL**

Run: `python -m pytest tests/test_reporting_service.py::test_shifts_and_cashiers -q`
Expected: FAIL

- [ ] **Step 3: Реализовать**

```python
def shifts_and_cashiers(session: Session, period: Period) -> ShiftsReport:
    shifts = session.scalars(
        select(Shift)
        .where(Shift.opened_at >= period.start, Shift.opened_at < period.end)
        .order_by(Shift.opened_at)
    ).all()
    rows: list[ShiftRow] = []
    agg: dict[str, list[int]] = {}  # name -> [shifts, orders, revenue, margin]
    for sh in shifts:
        cashier = session.get(User, sh.cashier_id)
        name = cashier.name if cashier is not None else "?"
        oc, revenue, cogs = session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_tiyn), 0),
                func.coalesce(func.sum(Order.cost_tiyn), 0),
            ).where(Order.shift_id == sh.id)
        ).one()
        oc, revenue, cogs = int(oc), int(revenue), int(cogs)
        margin = revenue - cogs
        rows.append(ShiftRow(shift_id=sh.id, cashier_name=name, opened_at=sh.opened_at,
                             closed_at=sh.closed_at, orders_count=oc,
                             revenue_tiyn=revenue, cogs_tiyn=cogs, margin_tiyn=margin))
        a = agg.setdefault(name, [0, 0, 0, 0])
        a[0] += 1; a[1] += oc; a[2] += revenue; a[3] += margin
    by_cashier = [
        CashierRow(cashier_name=name, shifts_count=v[0], orders_count=v[1],
                   revenue_tiyn=v[2], margin_tiyn=v[3])
        for name, v in agg.items()
    ]
    return ShiftsReport(shifts=rows, by_cashier=by_cashier)
```

- [ ] **Step 4: PASS**

Run: `python -m pytest tests/test_reporting_service.py -q`
Expected: PASS (все тесты модуля)

- [ ] **Step 5: Commit**

```bash
git add app/services/reporting_service.py tests/test_reporting_service.py
git commit -m "feat(reporting): shifts and cashiers report"
```

---

### Task 8: Экспорт в Excel

**Files:**
- Create: `app/services/report_excel.py`
- Test: `tests/test_report_excel.py`

- [ ] **Step 1: Тест**

Создать `tests/test_report_excel.py`:
```python
import io

from openpyxl import load_workbook

from app.services import reporting_service as rs
from app.services.report_excel import build_reports_workbook


def _sample():
    period = rs.Period.__call__ if False else None  # заглушка, не используется
    from datetime import datetime, timezone
    period = rs.Period(datetime(2026, 7, 21, 18, tzinfo=timezone.utc),
                       datetime(2026, 7, 22, 18, tzinfo=timezone.utc))
    rev = rs.RevenueByMethod(by_method={"cash": 3000, "card": 1500}, gross_tiyn=4500,
                             refunds_tiyn=1500, net_tiyn=3000, orders_count=2)
    top = [rs.ProductRow(name="Латте", qty_sold=3, qty_refunded=1, qty_net=2,
                         revenue_tiyn=4500)]
    cats = [rs.CategoryRow(category="Кофе", revenue_tiyn=4500, qty_net=2)]
    margin = rs.CostMargin(revenue_tiyn=4500, cogs_tiyn=1200, margin_tiyn=3300,
                           margin_pct=73.3, refunds_tiyn=1500, net_revenue_tiyn=3000)
    shifts = rs.ShiftsReport(shifts=[], by_cashier=[])
    return period, rev, top, cats, margin, shifts


def test_build_workbook_has_sheets_and_values():
    data = build_reports_workbook(*_sample())
    wb = load_workbook(io.BytesIO(data))
    assert set(wb.sheetnames) >= {"Сводка", "Способы оплаты", "Топ товаров",
                                  "Категории", "Маржа", "Смены"}
    ws = wb["Способы оплаты"]
    # где-то в листе должны быть значения в тенге: 30 (cash 3000 тиын) и 15 (card)
    values = [c.value for row in ws.iter_rows() for c in row]
    assert 30 in values and 15 in values
```

- [ ] **Step 2: FAIL**

Run: `python -m pytest tests/test_report_excel.py -q`
Expected: FAIL (нет `report_excel`)

- [ ] **Step 3: Реализовать**

Создать `app/services/report_excel.py`:
```python
import io

from openpyxl import Workbook
from openpyxl.styles import Font

from app.services import reporting_service as rs

METHOD_LABELS = {"cash": "Наличные", "card": "Карта",
                 "kaspi_qr": "Kaspi QR", "kaspi_terminal": "Kaspi (терминал)"}
_BOLD = Font(bold=True)


def _t(tiyn: int) -> float:
    return round(tiyn / 100, 2)


def _header(ws, titles):
    ws.append(titles)
    for cell in ws[ws.max_row]:
        cell.font = _BOLD


def build_reports_workbook(period: rs.Period, rev: rs.RevenueByMethod,
                           top: list[rs.ProductRow], cats: list[rs.CategoryRow],
                           margin: rs.CostMargin, shifts: rs.ShiftsReport) -> bytes:
    wb = Workbook()

    ws = wb.active
    ws.title = "Сводка"
    _header(ws, ["Показатель", "Значение, тг"])
    ws.append(["Период (UTC)", f"{period.start:%Y-%m-%d %H:%M} — {period.end:%Y-%m-%d %H:%M}"])
    ws.append(["Продажи (валовые)", _t(rev.gross_tiyn)])
    ws.append(["Возвраты", _t(rev.refunds_tiyn)])
    ws.append(["Чистая выручка", _t(rev.net_tiyn)])
    ws.append(["Себестоимость (COGS)", _t(margin.cogs_tiyn)])
    ws.append(["Маржа", _t(margin.margin_tiyn)])
    ws.append(["Маржа, %", margin.margin_pct])
    ws.append(["Чеков", rev.orders_count])

    ws = wb.create_sheet("Способы оплаты")
    _header(ws, ["Способ", "Сумма, тг"])
    for method, amount in rev.by_method.items():
        ws.append([METHOD_LABELS.get(method, method), _t(amount)])
    ws.append(["Возвраты", _t(rev.refunds_tiyn)])
    ws.append(["Чистая", _t(rev.net_tiyn)])

    ws = wb.create_sheet("Топ товаров")
    _header(ws, ["Товар", "Продано", "Возвращено", "Чисто", "Выручка, тг"])
    for r in top:
        ws.append([r.name, r.qty_sold, r.qty_refunded, r.qty_net, _t(r.revenue_tiyn)])

    ws = wb.create_sheet("Категории")
    _header(ws, ["Категория", "Выручка, тг", "Продано (чисто)"])
    for c in cats:
        ws.append([c.category, _t(c.revenue_tiyn), c.qty_net])

    ws = wb.create_sheet("Маржа")
    _header(ws, ["Показатель", "Значение, тг"])
    ws.append(["Выручка", _t(margin.revenue_tiyn)])
    ws.append(["Себестоимость", _t(margin.cogs_tiyn)])
    ws.append(["Маржа", _t(margin.margin_tiyn)])
    ws.append(["Маржа, %", margin.margin_pct])
    ws.append(["Возвраты", _t(margin.refunds_tiyn)])
    ws.append(["Чистая выручка", _t(margin.net_revenue_tiyn)])

    ws = wb.create_sheet("Смены")
    _header(ws, ["Смена", "Кассир", "Открыта", "Закрыта", "Чеков",
                 "Выручка, тг", "Маржа, тг"])
    for sh in shifts.shifts:
        ws.append([sh.shift_id, sh.cashier_name,
                   f"{sh.opened_at:%Y-%m-%d %H:%M}",
                   f"{sh.closed_at:%Y-%m-%d %H:%M}" if sh.closed_at else "",
                   sh.orders_count, _t(sh.revenue_tiyn), _t(sh.margin_tiyn)])
    ws.append([])
    _header(ws, ["Кассир", "Смен", "Чеков", "Выручка, тг", "Маржа, тг"])
    for c in shifts.by_cashier:
        ws.append([c.cashier_name, c.shifts_count, c.orders_count,
                   _t(c.revenue_tiyn), _t(c.margin_tiyn)])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: PASS**

Run: `python -m pytest tests/test_report_excel.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/report_excel.py tests/test_report_excel.py
git commit -m "feat(reporting): Excel workbook export (openpyxl)"
```

---

### Task 9: Страница `/admin/reports` + плитка

**Files:**
- Create: `app/ui/reports.py`
- Modify: `app/ui/admin_home.py`
- Modify: `app/ui/__init__.py`

- [ ] **Step 1: Создать `app/ui/reports.py`**

```python
from datetime import date

from nicegui import ui

from app.db import SessionLocal
from app.services import reporting_service as rs
from app.services.report_excel import build_reports_workbook
from app.ui.guard import require_admin
from app.ui.layout import admin_header

_PRESETS = {"today": "Сегодня", "yesterday": "Вчера", "week": "7 дней",
            "month": "Месяц", "custom": "Свой"}
_METHOD_LABELS = {"cash": "Наличные", "card": "Карта",
                  "kaspi_qr": "Kaspi QR", "kaspi_terminal": "Kaspi (терминал)"}


def _tg(tiyn: int) -> str:
    return f"{tiyn / 100:,.0f} тг".replace(",", " ")


@ui.page("/admin/reports")
def reports_page() -> None:
    if not require_admin():
        return
    admin_header()

    ui.label("Отчёты").classes("text-2xl font-bold")

    preset = ui.toggle(_PRESETS, value="today")
    with ui.row().classes("items-center gap-2") as custom_row:
        d_from = ui.date(value=date.today().isoformat())
        d_to = ui.date(value=date.today().isoformat())
    custom_row.bind_visibility_from(preset, "value", value="custom")

    body = ui.column().classes("w-full max-w-4xl gap-4")

    def current_period() -> rs.Period | None:
        if preset.value == "custom":
            try:
                s = date.fromisoformat(d_from.value)
                e = date.fromisoformat(d_to.value)
            except (TypeError, ValueError):
                ui.notify("Укажите даты", color="red")
                return None
            if e < s:
                ui.notify("Конец периода раньше начала", color="red")
                return None
            return rs.period_from_dates(s, e)
        return rs.period_from_preset(preset.value)

    def build_reports():
        period = current_period()
        if period is None:
            return None
        with SessionLocal() as session:
            return (
                period,
                rs.revenue_by_method(session, period),
                rs.top_products(session, period),
                rs.revenue_by_category(session, period),
                rs.cost_and_margin(session, period),
                rs.shifts_and_cashiers(session, period),
            )

    def show() -> None:
        data = build_reports()
        body.clear()
        if data is None:
            return
        _, rev, top, cats, margin, shifts = data
        with body:
            with ui.card().classes("w-full"):
                ui.label("Сводка").classes("text-xl font-bold")
                ui.label(f"Продажи: {_tg(rev.gross_tiyn)}   Возвраты: {_tg(rev.refunds_tiyn)}"
                         f"   Чистая: {_tg(rev.net_tiyn)}")
                ui.label(f"Маржа: {_tg(margin.margin_tiyn)} ({margin.margin_pct}%)   "
                         f"Чеков: {rev.orders_count}")

            with ui.card().classes("w-full"):
                ui.label("Выручка по способам").classes("text-xl font-bold")
                if not rev.by_method:
                    ui.label("Нет данных за период").classes("text-gray-500")
                for method, amount in rev.by_method.items():
                    ui.label(f"{_METHOD_LABELS.get(method, method)}: {_tg(amount)}")

            with ui.card().classes("w-full"):
                ui.label("Топ товаров").classes("text-xl font-bold")
                if not top:
                    ui.label("Нет данных за период").classes("text-gray-500")
                for r in top:
                    ui.label(f"{r.name}: {r.qty_net} шт, {_tg(r.revenue_tiyn)}")

            with ui.card().classes("w-full"):
                ui.label("По категориям").classes("text-xl font-bold")
                if not cats:
                    ui.label("Нет данных за период").classes("text-gray-500")
                for c in cats:
                    ui.label(f"{c.category}: {_tg(c.revenue_tiyn)}")

            with ui.card().classes("w-full"):
                ui.label("Смены и кассиры").classes("text-xl font-bold")
                if not shifts.by_cashier:
                    ui.label("Нет данных за период").classes("text-gray-500")
                for c in shifts.by_cashier:
                    ui.label(f"{c.cashier_name}: смен {c.shifts_count}, чеков {c.orders_count}, "
                             f"{_tg(c.revenue_tiyn)}, маржа {_tg(c.margin_tiyn)}")

    def download() -> None:
        data = build_reports()
        if data is None:
            return
        period = data[0]
        content = build_reports_workbook(*data)
        ui.download(content, f"Отчёт_{period.start:%Y%m%d}-{period.end:%Y%m%d}.xlsx")

    with ui.row().classes("gap-2 mt-2"):
        ui.button("Показать", on_click=show)
        ui.button("Скачать Excel", icon="download", on_click=download)

    show()
```

- [ ] **Step 2: Добавить плитку в `app/ui/admin_home.py`**

В список `_SECTIONS` добавить перед строкой «Открыть кассу»:
```python
    ("📈 Отчёты", "Выручка, маржа, Excel", "/admin/reports"),
```

- [ ] **Step 3: Зарегистрировать страницу в `app/ui/__init__.py`**

В импорт-кортеж `register_pages` добавить `reports` (по алфавиту после `purchase`):
```python
    from app.ui import (  # noqa: F401
        admin_dashboard,
        admin_home,
        admin_menu,
        admin_modifiers,
        admin_stock,
        cashier,
        kaspi_admin,
        login,
        purchase,
        reports,
    )
```

- [ ] **Step 4: import-smoke**

Run:
```
python -c "import app.ui.reports, app.ui.admin_home; from app.main import create_app; create_app(start_bot=False); print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/ui/reports.py app/ui/admin_home.py app/ui/__init__.py
git commit -m "feat(reporting): /admin/reports page with period picker and Excel download"
```

---

### Task 10: Итоговая проверка

- [ ] **Step 1: Полный регресс**

Run: `python -m pytest -q`
Expected: все зелёные (130 прежних + новые reporting/excel).

- [ ] **Step 2: Финальный import-smoke**

Run:
```
python -c "import app.ui.reports; from app.main import create_app; create_app(start_bot=False); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Визуальная проверка (владелец)**

Открыть `/admin` → плитка «Отчёты» → выбрать период → «Показать» и «Скачать Excel».

---

## Self-Review

**Spec coverage:**
- Период (пресеты + свой) → Task 2. ✓
- Выручка по способам → Task 3. ✓
- Топ товаров (net qty) → Task 4. ✓
- По категориям → Task 5. ✓
- Себестоимость/маржа → Task 6. ✓
- Смены/кассиры → Task 7. ✓
- Excel (лист на отчёт) → Task 8. ✓
- Страница + плитка + регистрация → Task 9. ✓
- openpyxl → Task 1. ✓

**Placeholder scan:** плейсхолдеров нет; код приведён целиком. Имя Excel-файла строится из `period.start/end`.

**Type consistency:** dataclass-поля из Task 2 используются в Task 3–8 и в Excel/UI с теми же именами (`by_method`, `gross_tiyn`, `net_tiyn`, `qty_net`, `revenue_tiyn`, `margin_tiyn`, `margin_pct`, `by_cashier`, `shifts`). Функции `revenue_by_method/top_products/revenue_by_category/cost_and_margin/shifts_and_cashiers` и `period_from_preset/period_from_dates` названы одинаково в тестах, сервисе, Excel и UI.

**Заметка по времени:** фильтры сравнивают `created_at` с aware-UTC границами — тот же приём, что в `dashboard_service.today_summary`; тесты используют файловую БД и фиксированный `now`, чтобы не зависеть от текущей даты.
