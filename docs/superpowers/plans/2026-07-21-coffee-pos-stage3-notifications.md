# Coffee POS — этап 3 (приход товара, уведомления, дашборд) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить приход товара через интерфейс (кассир+админ), надёжные уведомления
администратору в Telegram (очередь + фоновый отправитель) и live-дашборд администратора
(выручка/чеки за сегодня, остатки, «на исходе», статус смены).

**Architecture:** Три независимых куска поверх существующего стека (FastAPI + NiceGUI +
aiogram + SQLAlchemy/SQLite, один процесс). Уведомления — таблица-очередь
`NotificationOutbox`, бизнес-сервисы только пишут в неё внутри своих уже существующих
транзакций; фоновый asyncio-таск внутри бота вычитывает и рассылает. Дашборд —
периодический опрос БД через `ui.timer` (без событийной шины). Приход товара — тонкая
UI-обёртка вокруг уже существующего `inventory_service.receive_purchase`.

**Tech Stack:** Python 3.12, FastAPI, NiceGUI, aiogram, SQLAlchemy 2.x, pytest, zoneinfo (+ `tzdata` для Windows).

**Спецификация:** `docs/superpowers/specs/2026-07-21-coffee-pos-stage3-notifications-design.md`

---

## Структура файлов

```
app/
  timezone.py                     # НОВЫЙ: Asia/Almaty конвертация и границы суток
  models/
    inventory.py                  # ИЗМЕНИТЬ: + Ingredient.low_stock_notified
    notifications.py              # НОВЫЙ: NotificationOutbox
    __init__.py                   # ИЗМЕНИТЬ: экспорт NotificationOutbox
  services/
    inventory_service.py          # ИЗМЕНИТЬ: apply_move проверяет порог остатка
    shift_service.py               # ИЗМЕНИТЬ: enqueue при открытии/закрытии/инкассации
    sales_service.py                # ИЗМЕНИТЬ: enqueue при возврате
    notification_service.py       # НОВЫЙ: enqueue/pending/mark_sent/mark_failed
    dashboard_service.py           # НОВЫЙ: TodaySummary, today_summary, low_stock_ingredients
  bot/
    __init__.py                    # ИЗМЕНИТЬ: запуск фонового отправителя вместе с run_bot
    notifier.py                     # НОВЫЙ: цикл рассылки очереди уведомлений
  ui/
    __init__.py                     # ИЗМЕНИТЬ: register_pages + admin_dashboard, purchase
    admin_dashboard.py               # НОВЫЙ: /admin/dashboard
    purchase.py                      # НОВЫЙ: /stock/purchase
    cashier.py                       # ИЗМЕНИТЬ: кнопка «Приход товара»
    admin_stock.py                   # ИЗМЕНИТЬ: кнопки «Дашборд» и «Приход товара»
tests/
  test_timezone.py                 # НОВЫЙ
  test_notification_service.py     # НОВЫЙ
  test_inventory_service.py        # ИЗМЕНИТЬ: тесты низкого остатка
  test_shift_service.py            # ИЗМЕНИТЬ: тесты уведомлений
  test_sales_service.py            # ИЗМЕНИТЬ: тест уведомления о возврате
  test_dashboard_service.py        # НОВЫЙ
README.md                           # ИЗМЕНИТЬ: разделы дашборда и прихода
requirements.txt                    # ИЗМЕНИТЬ: + tzdata
```

---

### Task 1: Часовой пояс Asia/Almaty

**Files:**
- Modify: `requirements.txt`
- Create: `app/timezone.py`
- Test: `tests/test_timezone.py`

- [ ] **Step 1: Добавить зависимость**

`requirements.txt` — добавить строку `tzdata` (нужна модулю `zoneinfo` на Windows, где
нет системной базы часовых поясов):
```
fastapi
uvicorn[standard]
nicegui
aiogram
sqlalchemy>=2.0
pydantic-settings
httpx
pytest
tzdata
```

Run: `.venv\Scripts\python -m pip install -r requirements.txt`
Expected: установка `tzdata` без ошибок.

- [ ] **Step 2: Написать падающий тест**

`tests/test_timezone.py`:
```python
from datetime import datetime, timezone

from app.timezone import now_almaty, to_almaty, today_bounds_utc


def test_to_almaty_converts_utc_to_plus5():
    utc_dt = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    almaty_dt = to_almaty(utc_dt)
    assert almaty_dt.hour == 15
    assert almaty_dt.utcoffset().total_seconds() == 5 * 3600


def test_now_almaty_is_aware_and_offset_plus5():
    dt = now_almaty()
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 5 * 3600


def test_today_bounds_utc_midnight_almaty_is_19_utc_previous_day():
    # 2026-07-21 02:00 UTC = 2026-07-21 07:00 Алматы (UTC+5) — те же сутки Алматы
    now = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    start, end = today_bounds_utc(now)
    assert start == datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc)


def test_today_bounds_utc_before_almaty_midnight_uses_previous_utc_day():
    # 2026-07-20 18:00 UTC = 2026-07-20 23:00 Алматы — ещё те же сутки (20 июля Алматы)
    now = datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)
    start, end = today_bounds_utc(now)
    assert start == datetime(2026, 7, 19, 19, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc)
```

- [ ] **Step 3: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_timezone.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.timezone'`

- [ ] **Step 4: Реализация**

`app/timezone.py`:
```python
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.inventory import utcnow

ALMATY = ZoneInfo("Asia/Almaty")


def to_almaty(dt: datetime) -> datetime:
    return dt.astimezone(ALMATY)


def now_almaty() -> datetime:
    return to_almaty(utcnow())


def today_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Границы текущих суток по времени Алматы, выраженные в UTC.

    Нужны для сравнения с полями created_at (хранятся в UTC).
    """
    local_now = to_almaty(now) if now is not None else now_almaty()
    start_local = datetime.combine(local_now.date(), time.min, tzinfo=ALMATY)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
```

- [ ] **Step 5: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_timezone.py -q`
Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/timezone.py tests/test_timezone.py
git commit -m "feat: Asia/Almaty timezone helpers for dashboard day boundaries"
```

---

### Task 2: Очередь уведомлений — модель и сервис

**Files:**
- Create: `app/models/notifications.py`, `app/services/notification_service.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_notification_service.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_notification_service.py`:
```python
from app.models import NotificationOutbox
from app.services import notification_service as ns


def test_enqueue_creates_pending_record(session):
    note = ns.enqueue(session, kind="shift_open", text="Смена открыта")
    session.commit()
    assert note.status == "pending"
    assert note.sent_at is None
    assert session.query(NotificationOutbox).count() == 1


def test_pending_returns_only_pending(session):
    ns.enqueue(session, kind="shift_open", text="A")
    b = ns.enqueue(session, kind="shift_open", text="B")
    session.commit()
    ns.mark_sent(session, b.id)
    pending = ns.pending(session)
    assert [n.text for n in pending] == ["A"]


def test_mark_sent_sets_status_and_timestamp(session):
    note = ns.enqueue(session, kind="shift_open", text="A")
    session.commit()
    ns.mark_sent(session, note.id)
    got = session.get(NotificationOutbox, note.id)
    assert got.status == "sent"
    assert got.sent_at is not None


def test_mark_failed_sets_status(session):
    note = ns.enqueue(session, kind="shift_open", text="A")
    session.commit()
    ns.mark_failed(session, note.id)
    got = session.get(NotificationOutbox, note.id)
    assert got.status == "failed"
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_notification_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'NotificationOutbox'`

- [ ] **Step 3: Модель**

`app/models/notifications.py`:
```python
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inventory import utcnow


class NotificationOutbox(Base):
    """Очередь уведомлений админу. Получатель не хранится — берётся из активных
    админов на момент отправки (переживает изменение состава админов)."""

    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]  # "shift_open" | "shift_close" | "collection" | "refund" | "low_stock"
    text: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")  # "pending" | "sent" | "failed"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

`app/models/__init__.py` — добавить импорт и в `__all__` (по алфавиту):
```python
from app.models.catalog import (
    Category,
    Modifier,
    ModifierGroup,
    ModifierItem,
    Product,
    ProductModifierGroup,
)
from app.models.inventory import Ingredient, RecipeItem, StockMove
from app.models.notifications import NotificationOutbox
from app.models.orders import Order, OrderItem, OrderItemModifier
from app.models.payments import Payment, Refund, RefundItem
from app.models.shifts import CashCollection, Shift
from app.models.users import User

__all__ = [
    "CashCollection",
    "Category",
    "Ingredient",
    "Modifier",
    "ModifierGroup",
    "ModifierItem",
    "NotificationOutbox",
    "Order",
    "OrderItem",
    "OrderItemModifier",
    "Payment",
    "Product",
    "ProductModifierGroup",
    "RecipeItem",
    "Refund",
    "RefundItem",
    "Shift",
    "StockMove",
    "User",
]
```

- [ ] **Step 4: Сервис**

`app/services/notification_service.py`:
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NotificationOutbox
from app.models.inventory import utcnow


def enqueue(session: Session, *, kind: str, text: str) -> NotificationOutbox:
    """Кладёт уведомление в очередь. Не коммитит — участвует в транзакции вызывающего."""
    note = NotificationOutbox(kind=kind, text=text)
    session.add(note)
    session.flush()
    return note


def pending(session: Session) -> list[NotificationOutbox]:
    return list(session.scalars(
        select(NotificationOutbox)
        .where(NotificationOutbox.status == "pending")
        .order_by(NotificationOutbox.created_at)
    ).all())


def mark_sent(session: Session, notification_id: int) -> None:
    note = session.get(NotificationOutbox, notification_id)
    if note is not None:
        note.status = "sent"
        note.sent_at = utcnow()
        session.commit()


def mark_failed(session: Session, notification_id: int) -> None:
    note = session.get(NotificationOutbox, notification_id)
    if note is not None:
        note.status = "failed"
        session.commit()
```

- [ ] **Step 5: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_notification_service.py -q`
Expected: `4 passed`

- [ ] **Step 6: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (существующие 72 + 4 новых = 76)

- [ ] **Step 7: Commit**

```bash
git add app/models/notifications.py app/models/__init__.py app/services/notification_service.py tests/test_notification_service.py
git commit -m "feat: notification outbox model and service"
```

---

### Task 3: Уведомления смены (открытие, закрытие, инкассация)

**Files:**
- Modify: `app/services/shift_service.py`
- Test: `tests/test_shift_service.py`

- [ ] **Step 1: Написать падающие тесты (добавить в tests/test_shift_service.py)**

Добавить импорт в начало файла (объединить с существующим):
```python
from app.models import NotificationOutbox, Order, Payment, Refund, Shift, User
```

Добавить тесты:
```python
def test_open_shift_enqueues_notification(session):
    c = _cashier(session)
    ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=500000)
    notes = session.query(NotificationOutbox).filter_by(kind="shift_open").all()
    assert len(notes) == 1
    assert "Кассир" in notes[0].text


def test_close_shift_enqueues_notification(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    ss.close_shift(session, shift_id=sh.id, counted_cash_tiyn=95000)
    notes = session.query(NotificationOutbox).filter_by(kind="shift_close").all()
    assert len(notes) == 1
    assert "Кассир" in notes[0].text


def test_collection_enqueues_notification(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=500000)
    ss.add_collection(session, shift_id=sh.id, amount_tiyn=200000, note="в сейф")
    notes = session.query(NotificationOutbox).filter_by(kind="collection").all()
    assert len(notes) == 1
    assert "Кассир" in notes[0].text


def test_collection_rejects_unknown_shift(session):
    with pytest.raises(ValueError):
        ss.add_collection(session, shift_id=999, amount_tiyn=1000)
```

Обратите внимание: последний тест проверяет новое поведение — раньше `add_collection`
не проверял существование смены; теперь это нужно, чтобы получить кассира для текста
уведомления, и заодно закрывает дыру в целостности данных.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv\Scripts\python -m pytest tests/test_shift_service.py -q`
Expected: FAIL — новые тесты падают (`NotificationOutbox` пуст / `add_collection` не
кидает `ValueError` на несуществующей смене)

- [ ] **Step 3: Реализация — полностью заменить app/services/shift_service.py**

```python
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models import CashCollection, Order, Payment, Refund, Shift, User
from app.models.inventory import utcnow
from app.services import notification_service
from app.timezone import to_almaty


def current_open_shift(session: Session) -> Shift | None:
    return session.scalars(select(Shift).where(Shift.status == "open")).first()


def open_shift(session: Session, *, cashier_id: int, opening_cash_tiyn: int) -> Shift:
    if current_open_shift(session) is not None:
        raise ValueError("Уже есть открытая смена")
    if opening_cash_tiyn < 0:
        raise ValueError("Стартовая наличность не может быть отрицательной")
    cashier = session.get(User, cashier_id)
    sh = Shift(cashier_id=cashier_id, opening_cash_tiyn=opening_cash_tiyn, status="open")
    session.add(sh)
    session.flush()
    notification_service.enqueue(
        session, kind="shift_open",
        text=(
            f"Смена открыта: {cashier.name}, {to_almaty(sh.opened_at):%d.%m.%Y %H:%M}, "
            f"старт {opening_cash_tiyn / 100:.2f} тг"
        ),
    )
    session.commit()
    return sh


def add_collection(session: Session, *, shift_id: int, amount_tiyn: int, note: str | None = None) -> CashCollection:
    if amount_tiyn <= 0:
        raise ValueError("Сумма инкассации должна быть больше нуля")
    sh = session.get(Shift, shift_id)
    if sh is None:
        raise ValueError(f"Смена {shift_id} не найдена")
    cashier = session.get(User, sh.cashier_id)
    coll = CashCollection(shift_id=shift_id, amount_tiyn=amount_tiyn, note=note)
    session.add(coll)
    notification_service.enqueue(
        session, kind="collection",
        text=f"Инкассация {amount_tiyn / 100:.2f} тг, смена №{shift_id}, {cashier.name}",
    )
    session.commit()
    return coll


def _sum(session: Session, stmt) -> int:
    return session.scalar(stmt) or 0


def expected_cash_tiyn(session: Session, shift_id: int) -> int:
    """Ожидаемая наличность = старт + продажи наличными − инкассации − возвраты по наличным чекам."""
    sh = session.get(Shift, shift_id)
    if sh is None:
        raise ValueError(f"Смена {shift_id} не найдена")
    cash_sales = _sum(
        session,
        select(func.sum(Payment.amount_tiyn))
        .join(Order, Order.id == Payment.order_id)
        .where(Order.shift_id == shift_id, Payment.method == "cash"),
    )
    collections = _sum(
        session,
        select(func.sum(CashCollection.amount_tiyn)).where(CashCollection.shift_id == shift_id),
    )
    # В кассе физически лежат только наличные — возврат Kaspi/карты не трогает кассу.
    # Заказ считается "наличным" только если ВСЕ его оплаты — cash (сплит-оплата
    # наличные+безнал сейчас не создаётся из UI, это упрощение задокументировано).
    non_cash_payment = select(Payment.id).where(
        Payment.order_id == Order.id, Payment.method != "cash"
    )
    refunds = _sum(
        session,
        select(func.sum(Refund.amount_tiyn))
        .join(Order, Order.id == Refund.order_id)
        .where(Order.shift_id == shift_id, ~exists(non_cash_payment)),
    )
    return sh.opening_cash_tiyn + cash_sales - collections - refunds


def close_shift(session: Session, *, shift_id: int, counted_cash_tiyn: int) -> Shift:
    sh = session.get(Shift, shift_id)
    if sh is None:
        raise ValueError(f"Смена {shift_id} не найдена")
    if sh.status != "open":
        raise ValueError("Смена уже закрыта")
    sh.expected_cash_tiyn = expected_cash_tiyn(session, shift_id)
    sh.counted_cash_tiyn = counted_cash_tiyn
    sh.closed_at = utcnow()
    sh.status = "closed"
    cashier = session.get(User, sh.cashier_id)
    diff = sh.counted_cash_tiyn - sh.expected_cash_tiyn
    notification_service.enqueue(
        session, kind="shift_close",
        text=(
            f"Смена закрыта: {cashier.name}, {to_almaty(sh.closed_at):%d.%m.%Y %H:%M}, "
            f"ожидалось {sh.expected_cash_tiyn / 100:.2f} тг, "
            f"по факту {sh.counted_cash_tiyn / 100:.2f} тг, расхождение {diff / 100:+.2f} тг"
        ),
    )
    session.commit()
    return sh
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_shift_service.py -q`
Expected: все PASS (10 тестов: 6 существующих + 4 новых)

- [ ] **Step 5: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/shift_service.py tests/test_shift_service.py
git commit -m "feat: shift notifications (open, close, collection)"
```

---

### Task 4: Уведомление о возврате

**Files:**
- Modify: `app/services/sales_service.py`
- Test: `tests/test_sales_service.py`

- [ ] **Step 1: Написать падающий тест (добавить в tests/test_sales_service.py)**

Добавить `NotificationOutbox` в существующий блок импорта моделей (по алфавиту):
```python
from app.models import (
    Category,
    Ingredient,
    NotificationOutbox,
    Order,
    OrderItem,
    Payment,
    Product,
    RecipeItem,
    Refund,
    RefundItem,
    StockMove,
    User,
)
```

Добавить тест:
```python
def test_refund_enqueues_notification(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                              payments=[PaymentInput("cash", 150000, 150000)])
    sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id, reason="брак")
    notes = session.query(NotificationOutbox).filter_by(kind="refund").all()
    assert len(notes) == 1
    assert "150000" not in notes[0].text  # сумма должна быть в тенге, не в тиынах
    assert "1500.00" in notes[0].text
    assert "брак" in notes[0].text
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_sales_service.py::test_refund_enqueues_notification -q`
Expected: FAIL — `AssertionError` (уведомлений пока нет) или `ImportError`

- [ ] **Step 3: Реализация**

В `app/services/sales_service.py` изменить строку импорта сервисов:
```python
from app.services import costing, modifier_service, notification_service, pricing
```

В функции `refund_sale`, внутри `try`, заменить конец блока (после `it.refunded_qty += q`
и цикла) — найти строки:
```python
    refund.amount_tiyn = refunded_amount
    all_refunded = all(it.refunded_qty >= it.qty for it in items)
    order.status = "refunded" if all_refunded else "partially_refunded"
    session.commit()
```
и заменить на:
```python
    refund.amount_tiyn = refunded_amount
    all_refunded = all(it.refunded_qty >= it.qty for it in items)
    order.status = "refunded" if all_refunded else "partially_refunded"
    cashier = session.get(User, cashier_id)
    notification_service.enqueue(
        session, kind="refund",
        text=(
            f"Возврат {refunded_amount / 100:.2f} тг по заказу №{order.number}, "
            f"причина: {refund.reason}, {cashier.name}"
        ),
    )
    session.commit()
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_sales_service.py -q`
Expected: все PASS

- [ ] **Step 5: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/sales_service.py tests/test_sales_service.py
git commit -m "feat: refund notification"
```

---

### Task 5: Уведомление о низком остатке

**Files:**
- Modify: `app/models/inventory.py`, `app/services/inventory_service.py`
- Test: `tests/test_inventory_service.py`

- [ ] **Step 1: Написать падающие тесты (добавить в tests/test_inventory_service.py)**

Добавить `NotificationOutbox` в импорт:
```python
from app.models import Ingredient, NotificationOutbox, StockMove
```

Добавить тесты:
```python
def test_low_stock_triggers_notification_once(session):
    milk = Ingredient(name="Молоко", unit="мл", low_stock_threshold=1000)
    session.add(milk)
    session.commit()
    inv.receive_purchase(session, milk.id, qty=5000, total_cost_tiyn=100000)  # 5000, выше порога
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 0

    inv.apply_move(session, milk.id, qty_delta=-4500, kind="sale", commit=True)  # 500, ниже порога
    notes = session.query(NotificationOutbox).filter_by(kind="low_stock").all()
    assert len(notes) == 1
    assert "Молоко" in notes[0].text

    inv.apply_move(session, milk.id, qty_delta=-100, kind="sale", commit=True)  # 400, всё ещё ниже
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1  # без дублей


def test_low_stock_notifies_again_after_restock_and_fall(session):
    milk = Ingredient(name="Молоко", unit="мл", low_stock_threshold=1000)
    session.add(milk)
    session.commit()
    inv.receive_purchase(session, milk.id, qty=5000, total_cost_tiyn=100000)
    inv.apply_move(session, milk.id, qty_delta=-4500, kind="sale", commit=True)  # 500 → уведомление №1
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1

    inv.receive_purchase(session, milk.id, qty=5000, total_cost_tiyn=100000)  # 5500, выше порога — сброс флага
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 1  # само пополнение не уведомляет

    inv.apply_move(session, milk.id, qty_delta=-4600, kind="sale", commit=True)  # 900 → уведомление №2
    assert session.query(NotificationOutbox).filter_by(kind="low_stock").count() == 2
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv\Scripts\python -m pytest tests/test_inventory_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'NotificationOutbox'` либо количество
уведомлений не совпадает

- [ ] **Step 3: Добавить поле в модель**

В `app/models/inventory.py`, класс `Ingredient`, после строки `low_stock_threshold`
добавить:
```python
    low_stock_notified: Mapped[bool] = mapped_column(default=False)
```

- [ ] **Step 4: Реализация проверки порога**

В `app/services/inventory_service.py` изменить импорты (добавить строку) и добавить
вызов проверки внутри `apply_move`, плюс саму функцию проверки:

```python
from sqlalchemy.orm import Session

from app.models import Ingredient, StockMove
from app.services import notification_service


def apply_move(
    session: Session,
    ingredient_id: int,
    *,
    qty_delta: int,
    kind: str,
    cost_tiyn: int | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
    commit: bool = False,
) -> StockMove:
    """Единственная точка изменения остатка: журнал + кэш в одной транзакции.

    Коммитит владелец транзакции: по умолчанию делается только flush,
    session.commit() — забота вызывающего кода (или commit=True явно).
    """
    ing = session.get(Ingredient, ingredient_id)
    if ing is None:
        raise ValueError(f"Позиция склада {ingredient_id} не найдена")
    move = StockMove(
        ingredient_id=ingredient_id,
        qty_delta=qty_delta,
        kind=kind,
        cost_tiyn=cost_tiyn,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )
    # атомарный UPDATE ... SET stock_qty = stock_qty + qty_delta (без гонок на уровне БД)
    ing.stock_qty = Ingredient.stock_qty + qty_delta
    session.add(move)
    session.flush()
    _check_low_stock(session, ing)
    if commit:
        session.commit()
    return move


def _check_low_stock(session: Session, ing: Ingredient) -> None:
    """Уведомляет один раз при пересечении порога вниз; повтор — только после
    пересечения порога вверх (пополнение) и нового падения."""
    if ing.stock_qty < ing.low_stock_threshold:
        if not ing.low_stock_notified:
            notification_service.enqueue(
                session, kind="low_stock",
                text=(
                    f"Низкий остаток: {ing.name} — {ing.stock_qty} {ing.unit} "
                    f"(порог {ing.low_stock_threshold})"
                ),
            )
            ing.low_stock_notified = True
    else:
        ing.low_stock_notified = False


def receive_purchase(
    session: Session, ingredient_id: int, *, qty: int, total_cost_tiyn: int
) -> None:
    """Приход: остаток растёт, себестоимость пересчитывается средневзвешенно."""
    if qty <= 0:
        raise ValueError("Количество прихода должно быть больше нуля")
    if total_cost_tiyn < 0:
        raise ValueError("Сумма прихода не может быть отрицательной")
    ing = session.get(Ingredient, ingredient_id)
    if ing is None:
        raise ValueError(f"Позиция склада {ingredient_id} не найдена")

    old_qty = max(ing.stock_qty, 0)  # отрицательный остаток не должен ломать среднюю
    new_total_qty = old_qty + qty
    ing.avg_cost_tiyn = (old_qty * ing.avg_cost_tiyn + total_cost_tiyn) / new_total_qty
    apply_move(
        session,
        ingredient_id,
        qty_delta=qty,
        kind="purchase",
        cost_tiyn=total_cost_tiyn,
        commit=False,
    )
    session.commit()
```

- [ ] **Step 5: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_inventory_service.py -q`
Expected: все PASS (4 существующих + 2 новых)

- [ ] **Step 6: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 7: Commit**

```bash
git add app/models/inventory.py app/services/inventory_service.py tests/test_inventory_service.py
git commit -m "feat: low-stock threshold notification with re-arm on restock"
```

---

### Task 6: Фоновая рассылка уведомлений в боте

**Files:**
- Create: `app/bot/notifier.py`
- Modify: `app/bot/__init__.py`

Логика уже покрыта тестами `notification_service` (задача 2); сам бот-код, как и
`cmd_start`, проверяется импортом и ручной проверкой (так же, как весь `app/bot` в
предыдущих этапах) — без юнит-тестов асинхронного цикла с реальным `aiogram.Bot`.

- [ ] **Step 1: Реализация**

`app/bot/notifier.py`:
```python
import asyncio
import logging

from aiogram import Bot
from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.services import notification_service as ns

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5


async def run_notifier(bot: Bot) -> None:
    """Фоновый цикл: раз в POLL_INTERVAL_SECONDS рассылает накопленные уведомления
    всем активным админам. Сбой отправки не меняет статус — запись остаётся
    "pending" и будет отправлена на следующем тике (переживает недоступность Telegram)."""
    while True:
        await _drain_once(bot)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _drain_once(bot: Bot) -> None:
    with SessionLocal() as session:
        notes = ns.pending(session)
        if not notes:
            return
        admin_ids = [
            u.telegram_id
            for u in session.scalars(
                select(User).where(User.role == "admin", User.is_active)
            ).all()
        ]
        for note in notes:
            try:
                for tg_id in admin_ids:
                    await bot.send_message(tg_id, note.text)
                ns.mark_sent(session, note.id)
            except Exception:
                logger.exception("Не удалось отправить уведомление %s", note.id)
```

- [ ] **Step 2: Подключить к run_bot**

В `app/bot/__init__.py` заменить функцию `run_bot`:
```python
async def run_bot() -> None:
    if not settings.bot_token:
        return
    bot = Bot(settings.bot_token)
    from app.bot.notifier import run_notifier

    notifier_task = asyncio.create_task(run_notifier(bot))
    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        notifier_task.cancel()
```

Добавить `import asyncio` в начало файла (первой строкой, перед `from aiogram import ...`).

- [ ] **Step 3: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (импорт `app.bot` не должен ломаться)

- [ ] **Step 4: Ручная проверка (опционально, если есть BOT_TOKEN и хотя бы один
  активный админ)**

1. Запустить `.venv\Scripts\python -m app.main`.
2. Через `/admin` открыть смену/сделать возврат — убедиться, что в БД появилась
   запись `NotificationOutbox` (можно проверить через `python -c` с запросом к БД).
3. В течение ~5 секунд сообщение должно прийти в Telegram-чат админа.
4. Остановить сервер.

- [ ] **Step 5: Commit**

```bash
git add app/bot/notifier.py app/bot/__init__.py
git commit -m "feat: background notifier loop draining the outbox"
```

---

### Task 7: Сервис дашборда

**Files:**
- Create: `app/services/dashboard_service.py`
- Test: `tests/test_dashboard_service.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_dashboard_service.py`:
```python
from datetime import datetime, timedelta, timezone

from app.models import Ingredient, Order, OrderItem, Shift, User
from app.services import dashboard_service as ds


def _shift(session):
    u = User(telegram_id=1, name="Кассир", role="cashier")
    session.add(u)
    session.flush()
    sh = Shift(cashier_id=u.id, opening_cash_tiyn=0)
    session.add(sh)
    session.commit()
    return sh


def _order(session, shift_id, *, number, created_at, total_tiyn=150000,
           status="paid", items_qty=1, refunded_qty=0):
    order = Order(shift_id=shift_id, number=number, status=status,
                  subtotal_tiyn=total_tiyn, total_tiyn=total_tiyn, created_at=created_at)
    session.add(order)
    session.flush()
    session.add(OrderItem(order_id=order.id, product_id=None, name="Латте",
                          unit_price_tiyn=total_tiyn, qty=items_qty,
                          line_total_tiyn=total_tiyn, refunded_qty=refunded_qty))
    session.commit()
    return order


def test_today_summary_counts_only_today(session):
    sh = _shift(session)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    _order(session, sh.id, number=1, created_at=now, total_tiyn=150000, items_qty=2)
    _order(session, sh.id, number=2, created_at=now - timedelta(hours=25),
           total_tiyn=999999, items_qty=9)  # вчера — не должно попасть в сводку
    summary = ds.today_summary(session, now=now)
    assert summary.revenue_tiyn == 150000
    assert summary.orders_count == 1
    assert summary.items_count == 2


def test_today_summary_excludes_refunded_orders(session):
    sh = _shift(session)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    _order(session, sh.id, number=1, created_at=now, total_tiyn=150000, status="refunded")
    summary = ds.today_summary(session, now=now)
    assert summary.orders_count == 0
    assert summary.revenue_tiyn == 0


def test_today_summary_subtracts_refunded_qty(session):
    sh = _shift(session)
    now = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
    _order(session, sh.id, number=1, created_at=now, total_tiyn=150000,
           items_qty=3, refunded_qty=1)
    summary = ds.today_summary(session, now=now)
    assert summary.items_count == 2


def test_low_stock_ingredients_lists_only_active_below_threshold(session):
    ok = Ingredient(name="Сахар", unit="г", stock_qty=1000, low_stock_threshold=500)
    low = Ingredient(name="Молоко", unit="мл", stock_qty=100, low_stock_threshold=500)
    inactive_low = Ingredient(name="Старое", unit="шт", stock_qty=0,
                             low_stock_threshold=10, is_active=False)
    session.add_all([ok, low, inactive_low])
    session.commit()
    result = ds.low_stock_ingredients(session)
    assert [i.name for i in result] == ["Молоко"]
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.dashboard_service'`

- [ ] **Step 3: Реализация**

`app/services/dashboard_service.py`:
```python
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ingredient, Order, OrderItem
from app.timezone import today_bounds_utc


@dataclass
class TodaySummary:
    revenue_tiyn: int
    orders_count: int
    items_count: int


def today_summary(session: Session, *, now: datetime | None = None) -> TodaySummary:
    start_utc, end_utc = today_bounds_utc(now)
    orders = session.scalars(
        select(Order).where(
            Order.created_at >= start_utc,
            Order.created_at < end_utc,
            Order.status != "refunded",
        )
    ).all()
    revenue = sum(o.total_tiyn for o in orders)
    order_ids = [o.id for o in orders]
    items_count = 0
    if order_ids:
        items_count = session.scalar(
            select(func.sum(OrderItem.qty - OrderItem.refunded_qty))
            .where(OrderItem.order_id.in_(order_ids))
        ) or 0
    return TodaySummary(revenue_tiyn=revenue, orders_count=len(orders), items_count=items_count)


def low_stock_ingredients(session: Session) -> list[Ingredient]:
    return list(session.scalars(
        select(Ingredient)
        .where(Ingredient.is_active, Ingredient.stock_qty < Ingredient.low_stock_threshold)
        .order_by(Ingredient.name)
    ).all())
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_dashboard_service.py -q`
Expected: `4 passed`

- [ ] **Step 5: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/dashboard_service.py tests/test_dashboard_service.py
git commit -m "feat: dashboard service (today summary, low stock list)"
```

---

### Task 8: Экран дашборда

**Files:**
- Create: `app/ui/admin_dashboard.py`
- Modify: `app/ui/__init__.py`

Логика уже покрыта тестами `dashboard_service` (задача 7); здесь — только UI-обвязка,
проверяется рендером страницы вручную (по образцу этапов 1-2).

- [ ] **Step 1: Реализация**

`app/ui/admin_dashboard.py`:
```python
from nicegui import ui

from app.db import SessionLocal
from app.models import User
from app.services import dashboard_service as ds
from app.services import shift_service as ss
from app.timezone import to_almaty
from app.ui.guard import require_admin


@ui.page("/admin/dashboard")
def admin_dashboard_page() -> None:
    if not require_admin():
        return

    ui.label("Дашборд").classes("text-2xl font-bold")
    box = ui.column().classes("w-full max-w-3xl gap-3")

    def refresh() -> None:
        box.clear()
        with box, SessionLocal() as session:
            summary = ds.today_summary(session)
            shift = ss.current_open_shift(session)
            low_stock = ds.low_stock_ingredients(session)

            with ui.row().classes("gap-6"):
                ui.label(f"Выручка сегодня: {summary.revenue_tiyn / 100:.2f} тг").classes("text-lg")
                ui.label(f"Чеков: {summary.orders_count}").classes("text-lg")
                ui.label(f"Позиций продано: {summary.items_count}").classes("text-lg")

            if shift is None:
                ui.label("Смена закрыта").classes("text-gray-500")
            else:
                cashier = session.get(User, shift.cashier_id)
                ui.label(
                    f"Смена открыта: {cashier.name}, с {to_almaty(shift.opened_at):%d.%m %H:%M}"
                ).classes("text-green-700")

            ui.label("На исходе").classes("text-xl mt-4")
            if not low_stock:
                ui.label("Все позиции в норме").classes("text-gray-500")
            for ing in low_stock:
                ui.label(
                    f"{ing.name}: {ing.stock_qty} {ing.unit} (порог {ing.low_stock_threshold})"
                ).classes("text-red-600")

    ui.timer(3.0, refresh)
```

- [ ] **Step 2: Зарегистрировать страницу**

`app/ui/__init__.py` — полностью заменить:
```python
def register_pages() -> None:
    """Импортирует модули страниц NiceGUI (каждый регистрирует свои @ui.page)."""
    from app.ui import (  # noqa: F401
        admin_dashboard,
        admin_menu,
        admin_modifiers,
        admin_stock,
        cashier,
        login,
    )
```

- [ ] **Step 3: Запустить тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (импорт `admin_dashboard` через `register_pages` не должен ломаться
— это косвенно проверяется существующим `tests/test_app.py::test_health`)

- [ ] **Step 4: Ручная проверка**

Run: `.venv\Scripts\python -m app.main`, открыть `http://localhost:8080/admin/dashboard`
(после входа админом через `/login`): убедиться, что страница рендерится без ошибок,
цифры за сегодня показываются (0, если продаж не было), блок «На исходе» — «Все позиции
в норме» на свежей БД. Оставить открытой ~10 секунд, убедиться что нет ошибок в
консоли сервера (таймер тикает). Остановить сервер.

- [ ] **Step 5: Commit**

```bash
git add app/ui/admin_dashboard.py app/ui/__init__.py
git commit -m "feat: live admin dashboard (today summary, low stock, shift status)"
```

---

### Task 9: Экран прихода товара + навигация

**Files:**
- Create: `app/ui/purchase.py`
- Modify: `app/ui/__init__.py`, `app/ui/cashier.py`, `app/ui/admin_stock.py`

- [ ] **Step 1: Реализация страницы прихода**

`app/ui/purchase.py`:
```python
from nicegui import ui
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Ingredient, StockMove
from app.services import inventory_service as inv
from app.timezone import to_almaty
from app.ui.guard import require_user


@ui.page("/stock/purchase")
def purchase_page() -> None:
    if not require_user():
        return

    ui.label("Приход товара").classes("text-2xl font-bold")

    with SessionLocal() as session:
        ing_options = {
            i.id: f"{i.name} ({i.unit})"
            for i in session.scalars(select(Ingredient).where(Ingredient.is_active)).all()
        }

    if not ing_options:
        ui.label("Нет складских позиций. Добавьте их в /admin/stock").classes("text-red-600")
        return

    sel_ing = ui.select(ing_options, label="Позиция склада")
    qty = ui.number("Количество", value=0, min=1, format="%.0f")
    total = ui.number("Сумма закупки, тг", value=0, min=0, format="%.0f")

    history_box = ui.column().classes("w-full max-w-2xl gap-1 mt-4")

    def refresh_history() -> None:
        history_box.clear()
        with history_box, SessionLocal() as session:
            ui.label("Последние приходы").classes("text-xl")
            moves = session.scalars(
                select(StockMove).where(StockMove.kind == "purchase")
                .order_by(StockMove.created_at.desc()).limit(10)
            ).all()
            if not moves:
                ui.label("Приходов ещё не было").classes("text-gray-500")
            for m in moves:
                ing = session.get(Ingredient, m.ingredient_id)
                cost = (m.cost_tiyn or 0) / 100
                ui.label(
                    f"{to_almaty(m.created_at):%d.%m %H:%M} — {ing.name}: "
                    f"+{m.qty_delta} {ing.unit}, {cost:.2f} тг"
                )

    def do_receive() -> None:
        if not sel_ing.value:
            ui.notify("Выберите позицию склада", color="red")
            return
        if not qty.value or qty.value <= 0:
            ui.notify("Введите количество", color="red")
            return
        if total.value is None or total.value < 0:
            ui.notify("Введите сумму закупки", color="red")
            return
        try:
            with SessionLocal() as s:
                inv.receive_purchase(
                    s, sel_ing.value,
                    qty=round(qty.value),
                    total_cost_tiyn=round(total.value * 100),
                )
        except (ValueError, IntegrityError) as e:
            ui.notify(str(e), color="red")
            return
        ui.notify("Приход оформлен", color="green")
        qty.value = 0
        total.value = 0
        refresh_history()

    ui.button("Оформить приход", on_click=do_receive)
    refresh_history()
```

- [ ] **Step 2: Зарегистрировать страницу**

`app/ui/__init__.py` — полностью заменить (добавлен `purchase`):
```python
def register_pages() -> None:
    """Импортирует модули страниц NiceGUI (каждый регистрирует свои @ui.page)."""
    from app.ui import (  # noqa: F401
        admin_dashboard,
        admin_menu,
        admin_modifiers,
        admin_stock,
        cashier,
        login,
        purchase,
    )
```

- [ ] **Step 3: Добавить навигацию из экрана кассира**

В `app/ui/cashier.py`, в функции `cashier_page`, сразу после строки
```python
    ui.button("Возвраты", on_click=lambda: ui.navigate.to("/cashier/refunds"))
```
добавить:
```python
    ui.button("Приход товара", on_click=lambda: ui.navigate.to("/stock/purchase"))
```

- [ ] **Step 4: Добавить навигацию со страницы склада админа**

В `app/ui/admin_stock.py`, в функции `admin_stock_page`, сразу после строк
```python
    ui.label("Склад: позиции и тех-карты").classes("text-2xl font-bold")
```
добавить:
```python
    with ui.row().classes("gap-2"):
        ui.button("Дашборд", on_click=lambda: ui.navigate.to("/admin/dashboard"))
        ui.button("Приход товара", on_click=lambda: ui.navigate.to("/stock/purchase"))
```

- [ ] **Step 5: Запустить тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 6: Ручная проверка**

Run: `.venv\Scripts\python -m app.main`, войти кассиром, открыть смену, нажать
«Приход товара» → выбрать позицию (напр. «Молоко»), ввести количество и сумму,
нажать «Оформить приход» — убедиться, что появилась запись в «Последние приходы» и
остаток на `/admin/stock` вырос. Проверить, что кнопки «Дашборд»/«Приход товара» на
`/admin/stock` тоже работают. Остановить сервер.

- [ ] **Step 7: Commit**

```bash
git add app/ui/purchase.py app/ui/__init__.py app/ui/cashier.py app/ui/admin_stock.py
git commit -m "feat: purchase entry screen with navigation from cashier and admin stock"
```

---

### Task 10: README и финальный регресс

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Обновить README.md**

Заменить строку:
```markdown
Разделы администратора: `/admin/menu`, `/admin/stock`, `/admin/modifiers` (только для роли admin).
```
на:
```markdown
Разделы администратора: `/admin/menu`, `/admin/stock`, `/admin/modifiers`,
`/admin/dashboard` (только для роли admin). Приход товара (`/stock/purchase`)
доступен и кассиру, и админу.

## Уведомления администратору

Бот присылает в Telegram (если задан `BOT_TOKEN`): открытие/закрытие смены,
инкассацию, возврат, падение остатка ниже порога. Уведомления идут через
внутреннюю очередь с повторной попыткой — временная недоступность Telegram их не
теряет, доставка в течение ~5 секунд после события.
```

Добавить (после раздела «Работа кассира», перед «Доступ из Telegram») новый раздел
про дашборд:
```markdown
## Дашборд администратора

`/admin/dashboard` — выручка и число чеков за сегодня, число проданных позиций,
статус текущей смены, список позиций склада с остатком ниже порога. Обновляется
автоматически каждые несколько секунд.
```

- [ ] **Step 2: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 3: Ручная сквозная проверка**

Run: `.venv\Scripts\python -m app.main`. Сценарий: войти кассиром → открыть смену →
провести продажу → зайти на `/admin/dashboard` (другой браузер/вкладка, войдя
админом) и убедиться, что выручка/чеки обновились в течение нескольких секунд →
вернуться, оформить возврат → внести приход товара на `/stock/purchase` → закрыть
смену. Если задан `BOT_TOKEN` — проверить, что все соответствующие уведомления
пришли в Telegram. Остановить сервер.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: stage-3 README updates (dashboard, notifications, purchase)"
```

---

## Самопроверка плана

- **Покрытие спецификации:** приход товара (задача 9) и его сервис (уже существующий
  `inventory_service.receive_purchase`, переиспользован без изменений); уведомления —
  очередь+сервис (задача 2), точки вызова смена/инкассация (задача 3), возврат
  (задача 4), низкий остаток с «перевзводом» (задача 5), фоновая рассылка (задача 6);
  дашборд — сервис (задача 7) и страница (задача 8) с четырьмя блоками из дизайна
  (выручка/чеки, остатки/на исходе, статус смены — все подтверждены владельцем).
- **Явно исключено (подтверждено при брейнсторминге):** ввод скидки в UI и её
  интерактивное одобрение через Telegram — не входит ни в один task этого плана.
- **Согласованность типов/сигнатур:** `notification_service.enqueue(session, *, kind, text)`
  используется одинаково в задачах 3, 4, 5; `NotificationOutbox` экспортируется из
  `app.models` до первого использования в тестах (задача 2, до задач 3-5);
  `dashboard_service.today_summary(session, *, now=None)` и `low_stock_ingredients(session)`
  — сигнатуры стабильны между задачами 7 и 8; `app.timezone.to_almaty`/`today_bounds_utc`
  созданы в задаче 1 до первого использования в задачах 3, 7, 8, 9.
- **Отклонение от буквы дизайн-документа (осознанное, к лучшему):** документ говорил
  «check_low_stock вызывается после apply_move и после receive_purchase» — реализовано
  как проверка *внутри* `apply_move` (задача 5), поскольку `receive_purchase` сам вызывает
  `apply_move` — единая точка проверки надёжнее, чем повторение вызова в каждом месте.
- **Отклонение от буквы дизайн-документа (уточнение):** документ описывал `enqueue`
  как «только add+commit»; реализовано как «add+flush, без commit» (задача 2), чтобы
  уведомление было частью той же атомарной транзакции, что и бизнес-действие — это
  соответствует явному требованию раздела 3 спецификации «если транзакция откатится,
  уведомление в очередь не попадёт», а не более ранней фразе в том же документе.
- **Найдено и исправлено по ходу ревью (не было предусмотрено планом):**
  1. `today_summary` завышала выручку при частичном возврате — `Order.total_tiyn` не
     уменьшается возвратом, реальная сумма живёт в `Refund.amount_tiyn`; исправлено
     вычитанием `Σ Refund.amount_tiyn` по заказам за период, добавлен тест через
     настоящий `sales_service.refund_sale` (не через ручную подмену поля).
  2. SQLite не сохраняет `tzinfo` для `DateTime(timezone=True)` — значения, прочитанные
     из БД в новой сессии, приходят `naive`. Ранняя защита `to_almaty` (бросать
     исключение на naive) ломала бы live-дашборд при каждом тике. Исправлено:
     `to_almaty` трактует naive как UTC (единственная точка создания времени в проекте
     — `utcnow()`, так что это безопасная и корректная семантика, не маскирующая
     реальных ошибок — проверено grep'ом по всему `app/` на `datetime.now()`).
  3. Один недостижимый админ (заблокировал бота) заставлял `notifier` бесконечно
     дублировать уведомление остальным админам — исправлено изоляцией отправки по
     каждому админу и пометкой `sent`, если доставлено хотя бы одному.
  4. Незащищённое разыменование `cashier.name` в нескольких местах (`shift_service`,
     `sales_service`, `admin_dashboard`) могло дать сырой `AttributeError` вместо
     аккуратной ошибки — добавлены проверки на `None` по образцу уже существующей в
     `sales_service.create_sale`.
- **Бэклог (не блокирует, отмечено ревью качества задачи 9):** нет единообразного
  catch-all (`except Exception`) для непойманных ошибок записи (например,
  `OperationalError` — «database is locked» при параллельной записи с одного SQLite-
  файла) на страницах `admin_menu`, `admin_modifiers`, `admin_stock`, `purchase` —
  сейчас такой fallback есть только в `cashier.py` (оформление чека). Стоит унифицировать
  отдельной задачей, не блокирует этап 3.
