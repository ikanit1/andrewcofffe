# Кофейня-POS, этап 2 «Продажи и смены» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Кассир входит по пин-коду, открывает смену, пробивает чек (товары + модификаторы + скидка в пределах лимита), принимает оплату (наличные/карта/Kaspi, в т.ч. раздельно), система атомарно проводит чек со списанием ингредиентов и снимком себестоимости; поддержаны возвраты и закрытие смены со сверкой наличных.

**Architecture:** Чистый расчётный слой (`pricing`, `costing`) без БД — легко тестируется. Транзакционные сервисы (`shift_service`, `sales_service`, `modifier_service`) владеют коммитами и опираются на `inventory_service.apply_move(commit=False)` из этапа 1. Корзина живёт в памяти UI; в БД чек попадает уже оплаченным — одной транзакцией (заказ + позиции + модификаторы + оплаты + движения склада). Экраны — NiceGUI-страницы за пин-гвардом.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, FastAPI, NiceGUI 3.14, aiogram, pytest. Деньги — целые тиыны; количества ингредиентов — целые базовые единицы; себестоимость снимается в тиынах (`round`).

**Спецификация:** `docs/superpowers/specs/2026-07-19-coffee-pos-telegram-design.md`
**Фундамент (этап 1, в master):** модели `User/Category/Product/ModifierGroup/Modifier/ModifierItem/ProductModifierGroup/Ingredient/RecipeItem/StockMove`; сервисы `catalog_service`, `inventory_service` (`apply_move(commit=False)`, `receive_purchase`); `auth` (`validate_init_data`, `hash_pin`, `verify_pin`); фабрика `create_app`; страницы `/admin/menu`, `/admin/stock`; тестовая фикстура `session` (in-memory SQLite, FK включены).

## Решения этапа 2 (согласованы с владельцем)

- **Модификаторы** входят в этап 2: выбор при продаже (наценка + списание доп-ингредиентов) и маленькая админка настройки.
- **Скидки**: кассир даёт скидку в пределах `User.discount_limit_percent`; сверх — касса блокирует. Интерактивное «разрешить через Telegram» отложено на этап 3 (там появятся уведомления).
- **Возвраты**: штучные (retail) позиции возвращаются на склад; ингредиенты приготовленных напитков не восстанавливаются (спец. настройка — этап 3). Возврат считается выданным из кассы наличными (упрощение для сверки смены).
- **Сверка смены**: ожидаемая наличность = стартовая + продажи наличными − инкассации − возвраты. Разбор возвратов по способам оплаты — этап 4 (отчёты).
- **Чек атомарен**: корзина редактируется в UI; в БД заказ создаётся уже оплаченным, одной транзакцией.

---

## Структура файлов

```
app/
  models/
    shifts.py       # Shift, CashCollection
    orders.py       # Order, OrderItem, OrderItemModifier
    payments.py     # Payment, Refund, RefundItem
    __init__.py     # + реэкспорт новых моделей
  services/
    pricing.py      # чистые расчёты: цена строки, скидки, итог, сдача
    costing.py      # себестоимость единицы товара (+модификаторы) из тех-карт
    shift_service.py# открытие/инкассация/закрытие смены
    sales_service.py# атомарное проведение чека и возврат
    modifier_service.py # CRUD групп/модификаторов, привязка к товару
    user_service.py # аутентификация по пин-коду, поиск по initData
  ui/
    guard.py        # require_user(): пин-гвард для страниц
    login.py        # страница входа по пин-коду
    admin_modifiers.py # админка модификаторов
    cashier.py      # экран смены + продажи + оплаты + возврата
    __init__.py     # регистрация новых страниц, гвард на admin/*
tests/
  test_pricing.py
  test_costing.py
  test_shift_service.py
  test_sales_service.py
  test_modifier_service.py
  test_user_service.py
  test_sales_integration.py
seed.py             # + кассир с пин-кодом, пример модификаторов
README.md           # + раздел про вход и продажу
```

---

### Task 1: Модели смены

**Files:**
- Create: `app/models/shifts.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_models_stage2.py`

- [ ] **Step 1: Падающий тест**

`tests/test_models_stage2.py`:
```python
from app.models import CashCollection, Shift, User


def _cashier(session):
    u = User(telegram_id=555, name="Кассир", role="cashier")
    session.add(u)
    session.flush()
    return u


def test_shift_open_defaults(session):
    c = _cashier(session)
    sh = Shift(cashier_id=c.id, opening_cash_tiyn=500000)
    session.add(sh)
    session.commit()
    got = session.query(Shift).one()
    assert got.status == "open"
    assert got.closed_at is None
    assert got.opening_cash_tiyn == 500000
    assert got.opened_at is not None


def test_cash_collection(session):
    c = _cashier(session)
    sh = Shift(cashier_id=c.id, opening_cash_tiyn=0)
    session.add(sh)
    session.flush()
    session.add(CashCollection(shift_id=sh.id, amount_tiyn=300000, note="в сейф"))
    session.commit()
    coll = session.query(CashCollection).one()
    assert coll.amount_tiyn == 300000
    assert coll.note == "в сейф"
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_models_stage2.py -q`
Expected: FAIL — `ImportError: cannot import name 'Shift'`

- [ ] **Step 3: Реализация**

`app/models/shifts.py`:
```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inventory import utcnow


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    opening_cash_tiyn: Mapped[int] = mapped_column(default=0)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expected_cash_tiyn: Mapped[int | None] = mapped_column(default=None)
    counted_cash_tiyn: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="open")  # "open" | "closed"


class CashCollection(Base):
    """Инкассация: изъятие наличности в течение смены."""

    __tablename__ = "cash_collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    amount_tiyn: Mapped[int]
    note: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

`app/models/__init__.py` — добавить импорт и в `__all__`:
```python
from app.models.shifts import CashCollection, Shift
```
(добавить `"CashCollection"`, `"Shift"` в `__all__`, сохранив алфавитный порядок).

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/shifts.py app/models/__init__.py tests/test_models_stage2.py
git commit -m "feat: shift and cash-collection models"
```

---

### Task 2: Модели заказа

**Files:**
- Create: `app/models/orders.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_models_stage2.py`

- [ ] **Step 1: Падающий тест (добавить в tests/test_models_stage2.py)**

```python
from app.models import (
    Category,
    Order,
    OrderItem,
    OrderItemModifier,
    Product,
)


def _paid_order(session):
    c = _cashier(session)
    sh = Shift(cashier_id=c.id, opening_cash_tiyn=0)
    session.add(sh)
    session.flush()
    order = Order(
        shift_id=sh.id, number=1, status="paid",
        subtotal_tiyn=170000, discount_tiyn=0, total_tiyn=170000, cost_tiyn=40000,
    )
    session.add(order)
    session.flush()
    return order


def test_order_items_and_modifiers(session):
    order = _paid_order(session)
    item = OrderItem(
        order_id=order.id, product_id=None, name="Латте",
        unit_price_tiyn=170000, qty=1, discount_tiyn=0,
        line_total_tiyn=170000, unit_cost_tiyn=40000,
    )
    session.add(item)
    session.flush()
    session.add(OrderItemModifier(
        order_item_id=item.id, modifier_id=None, name="L", price_delta_tiyn=20000,
    ))
    session.commit()

    got = session.query(OrderItem).one()
    assert got.name == "Латте"
    assert got.refunded_qty == 0
    mod = session.query(OrderItemModifier).one()
    assert mod.name == "L"
    assert mod.price_delta_tiyn == 20000
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_models_stage2.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/models/orders.py`:
```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inventory import utcnow


class Order(Base):
    """Оплаченный чек. Корзина редактируется в UI; в БД заказ уже проведён."""

    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("shift_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    number: Mapped[int]  # порядковый номер заказа в смене
    status: Mapped[str] = mapped_column(default="paid")  # paid|refunded|partially_refunded
    subtotal_tiyn: Mapped[int]  # сумма строк после позиционных скидок, до скидки на чек
    discount_tiyn: Mapped[int] = mapped_column(default=0)  # скидка на чек
    total_tiyn: Mapped[int]  # итог к оплате
    cost_tiyn: Mapped[int] = mapped_column(default=0)  # снимок себестоимости (COGS)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), default=None)
    name: Mapped[str]  # снимок названия товара
    unit_price_tiyn: Mapped[int]  # цена товара + модификаторы, за единицу, до скидки
    qty: Mapped[int]
    discount_tiyn: Mapped[int] = mapped_column(default=0)  # позиционная скидка, сумма
    line_total_tiyn: Mapped[int]  # unit_price*qty - discount
    unit_cost_tiyn: Mapped[int] = mapped_column(default=0)  # себестоимость за единицу
    refunded_qty: Mapped[int] = mapped_column(default=0)


class OrderItemModifier(Base):
    __tablename__ = "order_item_modifiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"), index=True)
    modifier_id: Mapped[int | None] = mapped_column(ForeignKey("modifiers.id"), default=None)
    name: Mapped[str]  # снимок названия модификатора
    price_delta_tiyn: Mapped[int] = mapped_column(default=0)
```

`app/models/__init__.py` — добавить импорт `from app.models.orders import Order, OrderItem, OrderItemModifier` и три имени в `__all__`.

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/orders.py app/models/__init__.py tests/test_models_stage2.py
git commit -m "feat: order, order-item and order-item-modifier models"
```

---

### Task 3: Модели оплаты и возврата

**Files:**
- Create: `app/models/payments.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_models_stage2.py`

- [ ] **Step 1: Падающий тест (добавить в tests/test_models_stage2.py)**

```python
from app.models import Payment, Refund, RefundItem


def test_payment_and_refund(session):
    order = _paid_order(session)
    session.add_all([
        Payment(order_id=order.id, method="cash", amount_tiyn=100000,
                tendered_tiyn=200000, change_tiyn=100000),
        Payment(order_id=order.id, method="kaspi_qr", amount_tiyn=70000),
    ])
    session.flush()
    refund = Refund(order_id=order.id, amount_tiyn=70000, reason="брак", cashier_id=order.shift_id)
    session.add(refund)
    session.flush()
    session.add(RefundItem(refund_id=refund.id, order_item_id=None, qty=1))
    session.commit()

    pays = session.query(Payment).order_by(Payment.id).all()
    assert [p.method for p in pays] == ["cash", "kaspi_qr"]
    assert pays[0].change_tiyn == 100000
    assert pays[1].tendered_tiyn is None
    assert session.query(Refund).one().reason == "брак"
    assert session.query(RefundItem).one().qty == 1
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_models_stage2.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/models/payments.py`:
```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inventory import utcnow


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    method: Mapped[str]  # "cash" | "card" | "kaspi_qr"
    amount_tiyn: Mapped[int]  # сколько этот способ покрывает в чеке
    tendered_tiyn: Mapped[int | None] = mapped_column(default=None)  # получено (наличные)
    change_tiyn: Mapped[int | None] = mapped_column(default=None)  # сдача (наличные)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    amount_tiyn: Mapped[int]
    reason: Mapped[str]
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefundItem(Base):
    __tablename__ = "refund_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    refund_id: Mapped[int] = mapped_column(ForeignKey("refunds.id"), index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id"), default=None)
    qty: Mapped[int]
    amount_tiyn: Mapped[int | None] = mapped_column(default=None)  # сумма возврата по строке
```

`app/models/__init__.py` — добавить `from app.models.payments import Payment, Refund, RefundItem` и три имени в `__all__`.

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/payments.py app/models/__init__.py tests/test_models_stage2.py
git commit -m "feat: payment, refund and refund-item models"
```

---

### Task 4: Расчётный слой (pricing) — чистые функции

**Files:**
- Create: `app/services/pricing.py`
- Test: `tests/test_pricing.py`

- [ ] **Step 1: Падающий тест**

`tests/test_pricing.py`:
```python
import pytest

from app.services import pricing as p


def _line(**kw):
    base = dict(
        base_price_tiyn=150000, qty=1, modifier_price_deltas=[],
        discount_kind=None, discount_value=0, unit_cost_tiyn=40000,
    )
    base.update(kw)
    return p.CartLine(**base)


def test_unit_price_includes_modifiers():
    line = _line(modifier_price_deltas=[20000, 5000])
    assert p.line_unit_price_tiyn(line) == 175000


def test_line_percent_discount_floors():
    line = _line(base_price_tiyn=100000, qty=3, discount_kind="percent", discount_value=10)
    # gross 300000, 10% = 30000
    assert p.line_discount_tiyn(line) == 30000
    assert p.line_total_tiyn(line) == 270000


def test_line_amount_discount_capped_at_gross():
    line = _line(base_price_tiyn=100000, qty=1, discount_kind="amount", discount_value=150000)
    assert p.line_discount_tiyn(line) == 100000
    assert p.line_total_tiyn(line) == 0


def test_order_totals_and_order_discount():
    lines = [_line(base_price_tiyn=100000, qty=2), _line(base_price_tiyn=150000, qty=1)]
    subtotal = p.order_subtotal_tiyn(lines)  # 200000 + 150000
    assert subtotal == 350000
    disc = p.order_discount_tiyn(subtotal, "percent", 20)  # 70000
    assert disc == 70000
    assert p.order_total_tiyn(subtotal, disc) == 280000


def test_effective_discount_percent_for_limit_check():
    line = _line(base_price_tiyn=100000, qty=1, discount_kind="amount", discount_value=25000)
    assert p.effective_discount_percent(line) == 25
    line2 = _line(discount_kind="percent", discount_value=15)
    assert p.effective_discount_percent(line2) == 15
    line3 = _line()
    assert p.effective_discount_percent(line3) == 0


def test_validate_payments_must_cover_total():
    pays = [p.PaymentInput("cash", 100000, 200000), p.PaymentInput("card", 80000, None)]
    p.validate_payments(180000, pays)  # не бросает
    with pytest.raises(ValueError):
        p.validate_payments(200000, pays)  # 180000 != 200000


def test_cash_change_from_tendered():
    pays = [p.PaymentInput("cash", 100000, 200000), p.PaymentInput("kaspi_qr", 80000, None)]
    assert p.cash_change_tiyn(pays) == 100000


def test_negative_and_bad_inputs_rejected():
    with pytest.raises(ValueError):
        p.line_discount_tiyn(_line(discount_kind="percent", discount_value=150))
    with pytest.raises(ValueError):
        p.validate_payments(100000, [p.PaymentInput("cash", -1, None)])
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_pricing.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/services/pricing.py`:
```python
from dataclasses import dataclass, field


@dataclass
class CartLine:
    base_price_tiyn: int
    qty: int
    unit_cost_tiyn: int
    modifier_price_deltas: list[int] = field(default_factory=list)
    discount_kind: str | None = None  # "percent" | "amount" | None
    discount_value: int = 0  # процент 0..100 или сумма в тиынах


@dataclass
class PaymentInput:
    method: str  # "cash" | "card" | "kaspi_qr"
    amount_tiyn: int
    tendered_tiyn: int | None = None


def line_unit_price_tiyn(line: CartLine) -> int:
    return line.base_price_tiyn + sum(line.modifier_price_deltas)


def _gross_tiyn(line: CartLine) -> int:
    return line_unit_price_tiyn(line) * line.qty


def line_discount_tiyn(line: CartLine) -> int:
    gross = _gross_tiyn(line)
    if line.discount_kind is None:
        return 0
    if line.discount_kind == "percent":
        if not 0 <= line.discount_value <= 100:
            raise ValueError("Процент скидки должен быть в диапазоне 0..100")
        return gross * line.discount_value // 100
    if line.discount_kind == "amount":
        if line.discount_value < 0:
            raise ValueError("Сумма скидки не может быть отрицательной")
        return min(line.discount_value, gross)
    raise ValueError(f"Неизвестный тип скидки: {line.discount_kind}")


def line_total_tiyn(line: CartLine) -> int:
    return _gross_tiyn(line) - line_discount_tiyn(line)


def effective_discount_percent(line: CartLine) -> int:
    """Скидка позиции в процентах (для отображения; округление вниз)."""
    gross = _gross_tiyn(line)
    if gross == 0 or line.discount_kind is None:
        return 0
    return line_discount_tiyn(line) * 100 // gross


def discount_within_limit_tiyn(gross_tiyn: int, discount_tiyn: int, limit_percent: int) -> bool:
    """True, если скидка не превышает лимит. Точное сравнение без округления:
    discount/gross <= limit/100  ⇔  discount*100 <= limit*gross."""
    if gross_tiyn <= 0:
        return True
    return discount_tiyn * 100 <= limit_percent * gross_tiyn


def order_subtotal_tiyn(lines: list[CartLine]) -> int:
    return sum(line_total_tiyn(l) for l in lines)


def order_discount_tiyn(subtotal_tiyn: int, kind: str | None, value: int) -> int:
    if kind is None:
        return 0
    if kind == "percent":
        if not 0 <= value <= 100:
            raise ValueError("Процент скидки должен быть в диапазоне 0..100")
        return subtotal_tiyn * value // 100
    if kind == "amount":
        if value < 0:
            raise ValueError("Сумма скидки не может быть отрицательной")
        return min(value, subtotal_tiyn)
    raise ValueError(f"Неизвестный тип скидки: {kind}")


def order_total_tiyn(subtotal_tiyn: int, order_discount_tiyn_value: int) -> int:
    return subtotal_tiyn - order_discount_tiyn_value


def validate_payments(total_tiyn: int, payments: list[PaymentInput]) -> None:
    for pay in payments:
        if pay.amount_tiyn < 0:
            raise ValueError("Сумма оплаты не может быть отрицательной")
        if pay.method not in ("cash", "card", "kaspi_qr"):
            raise ValueError(f"Неизвестный способ оплаты: {pay.method}")
    covered = sum(pay.amount_tiyn for pay in payments)
    if covered != total_tiyn:
        raise ValueError(f"Оплата {covered} не покрывает итог {total_tiyn}")


def cash_change_tiyn(payments: list[PaymentInput]) -> int:
    change = 0
    for pay in payments:
        if pay.method == "cash" and pay.tendered_tiyn is not None:
            change += max(pay.tendered_tiyn - pay.amount_tiyn, 0)
    return change
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_pricing.py -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/pricing.py tests/test_pricing.py
git commit -m "feat: pure pricing layer (lines, discounts, totals, change)"
```

---

### Task 5: Себестоимость единицы (costing)

**Files:**
- Create: `app/services/costing.py`
- Test: `tests/test_costing.py`

- [ ] **Step 1: Падающий тест**

`tests/test_costing.py`:
```python
from app.models import (
    Category,
    Ingredient,
    Modifier,
    ModifierGroup,
    ModifierItem,
    Product,
    RecipeItem,
)
from app.services import costing


def _prepared_latte(session):
    cat = Category(name="Кофе")
    session.add(cat)
    session.flush()
    milk = Ingredient(name="Молоко", unit="мл", stock_qty=0, avg_cost_tiyn=50.0)
    beans = Ingredient(name="Кофе зерно", unit="г", stock_qty=0, avg_cost_tiyn=300.0)
    session.add_all([milk, beans])
    session.flush()
    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(latte)
    session.flush()
    session.add_all([
        RecipeItem(product_id=latte.id, ingredient_id=beans.id, qty=18),   # 18*300=5400
        RecipeItem(product_id=latte.id, ingredient_id=milk.id, qty=200),   # 200*50=10000
    ])
    session.commit()
    return latte, milk


def test_prepared_unit_cost_from_recipe(session):
    latte, _ = _prepared_latte(session)
    assert costing.unit_cost_tiyn(session, latte, []) == 15400


def test_modifier_adds_to_cost(session):
    latte, milk = _prepared_latte(session)
    grp = ModifierGroup(name="Молоко")
    session.add(grp)
    session.flush()
    extra = Modifier(group_id=grp.id, name="Двойное молоко", price_delta_tiyn=20000)
    session.add(extra)
    session.flush()
    session.add(ModifierItem(modifier_id=extra.id, ingredient_id=milk.id, qty=100))  # +100*50=5000
    session.commit()
    assert costing.unit_cost_tiyn(session, latte, [extra.id]) == 20400


def test_retail_unit_cost_from_linked_ingredient(session):
    cat = Category(name="Снеки")
    session.add(cat)
    session.flush()
    cro = Ingredient(name="Круассан", unit="шт", stock_qty=0, avg_cost_tiyn=45000.0)
    session.add(cro)
    session.flush()
    prod = Product(name="Круассан", category_id=cat.id, kind="retail",
                   price_tiyn=90000, ingredient_id=cro.id)
    session.add(prod)
    session.commit()
    assert costing.unit_cost_tiyn(session, prod, []) == 45000
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_costing.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/services/costing.py`:
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, ModifierItem, Product, RecipeItem


def unit_cost_tiyn(session: Session, product: Product, modifier_ids: list[int]) -> int:
    """Себестоимость одной единицы товара с учётом выбранных модификаторов (в тиынах).

    prepared — по тех-карте; retail — по привязанной складской позиции.
    Плюс списания выбранных модификаторов (ModifierItem).
    """
    cost = 0.0
    if product.kind == "prepared":
        rows = session.scalars(
            select(RecipeItem).where(RecipeItem.product_id == product.id)
        ).all()
        for r in rows:
            ing = session.get(Ingredient, r.ingredient_id)
            cost += r.qty * ing.avg_cost_tiyn
    elif product.kind == "retail":
        if product.ingredient_id is not None:
            ing = session.get(Ingredient, product.ingredient_id)
            cost += ing.avg_cost_tiyn  # 1 единица на порцию

    if modifier_ids:
        items = session.scalars(
            select(ModifierItem).where(ModifierItem.modifier_id.in_(modifier_ids))
        ).all()
        for mi in items:
            ing = session.get(Ingredient, mi.ingredient_id)
            cost += mi.qty * ing.avg_cost_tiyn

    return round(cost)
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_costing.py -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/costing.py tests/test_costing.py
git commit -m "feat: unit cost calculation from recipes and modifiers"
```

---

### Task 6: Сервис смен

**Files:**
- Create: `app/services/shift_service.py`
- Test: `tests/test_shift_service.py`

- [ ] **Step 1: Падающий тест**

`tests/test_shift_service.py`:
```python
import pytest

from app.models import Order, Payment, Refund, Shift, User
from app.services import shift_service as ss


def _cashier(session):
    u = User(telegram_id=555, name="Кассир", role="cashier")
    session.add(u)
    session.commit()
    return u


def test_open_shift(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=500000)
    assert sh.status == "open"
    assert ss.current_open_shift(session) is not None


def test_cannot_open_two_shifts(session):
    c = _cashier(session)
    ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=0)
    with pytest.raises(ValueError):
        ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=0)


def test_collection_reduces_expected_cash(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=500000)
    ss.add_collection(session, shift_id=sh.id, amount_tiyn=200000, note="в сейф")
    assert ss.expected_cash_tiyn(session, sh.id) == 300000


def test_expected_cash_counts_only_cash_sales(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    order = Order(shift_id=sh.id, number=1, status="paid",
                  subtotal_tiyn=170000, total_tiyn=170000)
    session.add(order)
    session.flush()
    session.add_all([
        Payment(order_id=order.id, method="cash", amount_tiyn=100000),
        Payment(order_id=order.id, method="kaspi_qr", amount_tiyn=70000),
    ])
    session.commit()
    # 100000 старт + 100000 наличными = 200000
    assert ss.expected_cash_tiyn(session, sh.id) == 200000


def test_refund_reduces_expected_cash(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    order = Order(shift_id=sh.id, number=1, status="paid",
                  subtotal_tiyn=50000, total_tiyn=50000)
    session.add(order)
    session.flush()
    session.add(Payment(order_id=order.id, method="cash", amount_tiyn=50000))
    session.add(Refund(order_id=order.id, amount_tiyn=50000, reason="брак", cashier_id=c.id))
    session.commit()
    # 100000 + 50000 продажа - 50000 возврат
    assert ss.expected_cash_tiyn(session, sh.id) == 100000


def test_close_shift_records_discrepancy(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=100000)
    closed = ss.close_shift(session, shift_id=sh.id, counted_cash_tiyn=95000)
    assert closed.status == "closed"
    assert closed.closed_at is not None
    assert closed.expected_cash_tiyn == 100000
    assert closed.counted_cash_tiyn == 95000
    assert ss.current_open_shift(session) is None


def test_cannot_close_twice(session):
    c = _cashier(session)
    sh = ss.open_shift(session, cashier_id=c.id, opening_cash_tiyn=0)
    ss.close_shift(session, shift_id=sh.id, counted_cash_tiyn=0)
    with pytest.raises(ValueError):
        ss.close_shift(session, shift_id=sh.id, counted_cash_tiyn=0)
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_shift_service.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/services/shift_service.py`:
```python
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CashCollection, Order, Payment, Refund, Shift
from app.models.inventory import utcnow


def current_open_shift(session: Session) -> Shift | None:
    return session.scalars(select(Shift).where(Shift.status == "open")).first()


def open_shift(session: Session, *, cashier_id: int, opening_cash_tiyn: int) -> Shift:
    if current_open_shift(session) is not None:
        raise ValueError("Уже есть открытая смена")
    if opening_cash_tiyn < 0:
        raise ValueError("Стартовая наличность не может быть отрицательной")
    sh = Shift(cashier_id=cashier_id, opening_cash_tiyn=opening_cash_tiyn, status="open")
    session.add(sh)
    session.commit()
    return sh


def add_collection(session: Session, *, shift_id: int, amount_tiyn: int, note: str | None = None) -> CashCollection:
    if amount_tiyn <= 0:
        raise ValueError("Сумма инкассации должна быть больше нуля")
    coll = CashCollection(shift_id=shift_id, amount_tiyn=amount_tiyn, note=note)
    session.add(coll)
    session.commit()
    return coll


def _sum(session: Session, stmt) -> int:
    return session.scalar(stmt) or 0


def expected_cash_tiyn(session: Session, shift_id: int) -> int:
    """Ожидаемая наличность = старт + продажи наличными − инкассации − возвраты."""
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
    refunds = _sum(
        session,
        select(func.sum(Refund.amount_tiyn))
        .join(Order, Order.id == Refund.order_id)
        .where(Order.shift_id == shift_id),
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
    session.commit()
    return sh
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_shift_service.py -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/shift_service.py tests/test_shift_service.py
git commit -m "feat: shift service (open, collection, expected cash, close)"
```

---

### Task 7: Сервис продаж — атомарное проведение чека

**Files:**
- Create: `app/services/sales_service.py`
- Test: `tests/test_sales_service.py`

- [ ] **Step 1: Падающий тест**

`tests/test_sales_service.py`:
```python
import pytest

from app.models import (
    Category,
    Ingredient,
    Order,
    OrderItem,
    Payment,
    Product,
    RecipeItem,
    StockMove,
    User,
)
from app.services import sales_service as sales
from app.services import shift_service as ss
from app.services.pricing import PaymentInput


def _setup(session):
    cashier = User(telegram_id=1, name="Кассир", role="cashier", discount_limit_percent=10)
    session.add(cashier)
    cat = Category(name="Кофе")
    session.add(cat)
    session.flush()
    milk = Ingredient(name="Молоко", unit="мл", stock_qty=1000, avg_cost_tiyn=50.0)
    beans = Ingredient(name="Кофе зерно", unit="г", stock_qty=100, avg_cost_tiyn=300.0)
    session.add_all([milk, beans])
    session.flush()
    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(latte)
    session.flush()
    session.add_all([
        RecipeItem(product_id=latte.id, ingredient_id=beans.id, qty=18),
        RecipeItem(product_id=latte.id, ingredient_id=milk.id, qty=200),
    ])
    session.commit()
    shift = ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=0)
    return cashier, latte, milk, beans, shift


def _line(product_id, qty=1, modifier_ids=None, discount_kind=None, discount_value=0):
    return sales.SaleLineInput(
        product_id=product_id, qty=qty, modifier_ids=modifier_ids or [],
        discount_kind=discount_kind, discount_value=discount_value,
    )


def test_sale_persists_order_and_deducts_stock(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session,
        cashier_id=cashier.id,
        lines=[_line(latte.id, qty=2)],
        payments=[PaymentInput("cash", 300000, 300000)],
    )
    assert order.total_tiyn == 300000
    assert order.cost_tiyn == 2 * 15400
    assert order.number == 1
    # склад списан: молоко 1000-400=600, зерно 100-36=64
    assert session.get(Ingredient, milk.id).stock_qty == 600
    assert session.get(Ingredient, beans.id).stock_qty == 64
    moves = session.query(StockMove).filter_by(kind="sale").all()
    assert {m.ref_type for m in moves} == {"order"}
    assert all(m.ref_id == order.id for m in moves)


def test_order_numbers_increment_per_shift(session):
    cashier, latte, milk, beans, shift = _setup(session)
    o1 = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                           payments=[PaymentInput("cash", 150000, 150000)])
    o2 = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                           payments=[PaymentInput("cash", 150000, 150000)])
    assert (o1.number, o2.number) == (1, 2)


def test_split_payment_and_change(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("cash", 50000, 100000), PaymentInput("kaspi_qr", 100000)],
    )
    pays = session.query(Payment).filter_by(order_id=order.id).order_by(Payment.id).all()
    assert pays[0].change_tiyn == 50000
    assert pays[1].method == "kaspi_qr"


def test_payment_must_match_total(session):
    cashier, latte, milk, beans, shift = _setup(session)
    with pytest.raises(ValueError):
        sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                          payments=[PaymentInput("cash", 100000, 100000)])
    # заказ не создан, склад не тронут
    assert session.query(Order).count() == 0
    assert session.get(Ingredient, milk.id).stock_qty == 1000


def test_discount_within_limit_ok(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id,
        lines=[_line(latte.id, discount_kind="percent", discount_value=10)],
        payments=[PaymentInput("cash", 135000, 135000)],
    )
    assert order.total_tiyn == 135000


def test_discount_over_limit_blocked(session):
    cashier, latte, milk, beans, shift = _setup(session)
    with pytest.raises(PermissionError):
        sales.create_sale(
            session, cashier_id=cashier.id,
            lines=[_line(latte.id, discount_kind="percent", discount_value=20)],
            payments=[PaymentInput("cash", 120000, 120000)],
        )
    assert session.query(Order).count() == 0


def test_sale_requires_open_shift(session):
    cashier, latte, milk, beans, shift = _setup(session)
    ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=0)
    with pytest.raises(ValueError):
        sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id)],
                          payments=[PaymentInput("cash", 150000, 150000)])
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_sales_service.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/services/sales_service.py`:
```python
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Ingredient,
    Modifier,
    ModifierItem,
    Order,
    OrderItem,
    OrderItemModifier,
    Payment,
    Product,
    RecipeItem,
    User,
)
from app.services import costing, pricing
from app.services.inventory_service import apply_move
from app.services.pricing import CartLine, PaymentInput
from app.services.shift_service import current_open_shift


@dataclass
class SaleLineInput:
    product_id: int
    qty: int = 1
    modifier_ids: list[int] = field(default_factory=list)
    discount_kind: str | None = None
    discount_value: int = 0


def _next_order_number(session: Session, shift_id: int) -> int:
    last = session.scalar(
        select(func.max(Order.number)).where(Order.shift_id == shift_id)
    )
    return (last or 0) + 1


def create_sale(
    session: Session,
    *,
    cashier_id: int,
    lines: list[SaleLineInput],
    payments: list[PaymentInput],
    order_discount_kind: str | None = None,
    order_discount_value: int = 0,
) -> Order:
    """Атомарно проводит чек: заказ + позиции + модификаторы + оплаты + списание склада.

    Всё в одной транзакции — при любой ошибке откат, склад и заказ не меняются.
    """
    if not lines:
        raise ValueError("Чек не может быть пустым")
    shift = current_open_shift(session)
    if shift is None:
        raise ValueError("Нет открытой смены")
    cashier = session.get(User, cashier_id)
    if cashier is None:
        raise ValueError(f"Кассир {cashier_id} не найден")
    limit = cashier.discount_limit_percent

    # 1. Собираем модель корзины для расчётов и одновременно валидируем товары
    resolved = []  # (SaleLineInput, Product, [Modifier], CartLine)
    for li in lines:
        if li.qty <= 0:
            raise ValueError("Количество должно быть больше нуля")
        product = session.get(Product, li.product_id)
        if product is None or not product.is_active:
            raise ValueError(f"Товар {li.product_id} недоступен")
        mods = []
        for mid in li.modifier_ids:
            m = session.get(Modifier, mid)
            if m is None or not m.is_active:
                raise ValueError(f"Модификатор {mid} недоступен")
            mods.append(m)
        cart_line = CartLine(
            base_price_tiyn=product.price_tiyn,
            qty=li.qty,
            unit_cost_tiyn=costing.unit_cost_tiyn(session, product, li.modifier_ids),
            modifier_price_deltas=[m.price_delta_tiyn for m in mods],
            discount_kind=li.discount_kind,
            discount_value=li.discount_value,
        )
        # проверка лимита скидки кассира (позиция) — точное сравнение без округления
        line_gross = pricing.line_unit_price_tiyn(cart_line) * cart_line.qty
        if not pricing.discount_within_limit_tiyn(
            line_gross, pricing.line_discount_tiyn(cart_line), limit
        ):
            raise PermissionError("Скидка превышает лимит кассира")
        resolved.append((li, product, mods, cart_line))

    cart_lines = [r[3] for r in resolved]
    subtotal = pricing.order_subtotal_tiyn(cart_lines)
    order_disc = pricing.order_discount_tiyn(subtotal, order_discount_kind, order_discount_value)
    if not pricing.discount_within_limit_tiyn(subtotal, order_disc, limit):
        raise PermissionError("Скидка на чек превышает лимит кассира")
    total = pricing.order_total_tiyn(subtotal, order_disc)

    # 2. Проверяем оплату до записи
    pricing.validate_payments(total, payments)

    # 3. Пишем заказ и всё зависимое
    order = Order(
        shift_id=shift.id,
        number=_next_order_number(session, shift.id),
        status="paid",
        subtotal_tiyn=subtotal,
        discount_tiyn=order_disc,
        total_tiyn=total,
        cost_tiyn=sum(cl.unit_cost_tiyn * cl.qty for cl in cart_lines),
    )
    session.add(order)
    session.flush()

    for li, product, mods, cart_line in resolved:
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            name=product.name,
            unit_price_tiyn=pricing.line_unit_price_tiyn(cart_line),
            qty=li.qty,
            discount_tiyn=pricing.line_discount_tiyn(cart_line),
            line_total_tiyn=pricing.line_total_tiyn(cart_line),
            unit_cost_tiyn=cart_line.unit_cost_tiyn,
        )
        session.add(item)
        session.flush()
        for m in mods:
            session.add(OrderItemModifier(
                order_item_id=item.id, modifier_id=m.id,
                name=m.name, price_delta_tiyn=m.price_delta_tiyn,
            ))
        _deduct_stock(session, product, mods, li.qty, order.id)

    for pay in payments:
        change = None
        if pay.method == "cash" and pay.tendered_tiyn is not None:
            change = max(pay.tendered_tiyn - pay.amount_tiyn, 0)
        session.add(Payment(
            order_id=order.id, method=pay.method, amount_tiyn=pay.amount_tiyn,
            tendered_tiyn=pay.tendered_tiyn, change_tiyn=change,
        ))

    session.commit()
    return order


def _deduct_stock(session: Session, product: Product, mods, qty: int, order_id: int) -> None:
    """Списание по тех-карте (prepared) или по привязке (retail) + модификаторы."""
    def move(ingredient_id: int, per_unit_qty: int) -> None:
        ing = session.get(Ingredient, ingredient_id)
        total_qty = per_unit_qty * qty
        apply_move(
            session, ingredient_id,
            qty_delta=-total_qty, kind="sale",
            cost_tiyn=round(ing.avg_cost_tiyn * total_qty),
            ref_type="order", ref_id=order_id, commit=False,
        )

    if product.kind == "prepared":
        for r in session.scalars(select(RecipeItem).where(RecipeItem.product_id == product.id)).all():
            move(r.ingredient_id, r.qty)
    elif product.kind == "retail" and product.ingredient_id is not None:
        move(product.ingredient_id, 1)

    for m in mods:
        from app.models import ModifierItem
        for mi in session.scalars(select(ModifierItem).where(ModifierItem.modifier_id == m.id)).all():
            move(mi.ingredient_id, mi.qty)
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_sales_service.py -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/sales_service.py tests/test_sales_service.py
git commit -m "feat: atomic sale (order, items, modifiers, payments, stock)"
```

---

### Task 8: Сервис продаж — возврат

**Files:**
- Modify: `app/services/sales_service.py`
- Test: `tests/test_sales_service.py`

- [ ] **Step 1: Падающий тест (добавить в tests/test_sales_service.py)**

```python
from app.models import Refund, RefundItem


def test_full_refund_marks_order_and_restocks_retail(session):
    cashier = User(telegram_id=2, name="Кассир", role="cashier")
    session.add(cashier)
    cat = Category(name="Снеки")
    session.add(cat)
    session.flush()
    cro = Ingredient(name="Круассан", unit="шт", stock_qty=10, avg_cost_tiyn=45000.0)
    session.add(cro)
    session.flush()
    prod = Product(name="Круассан", category_id=cat.id, kind="retail",
                   price_tiyn=90000, ingredient_id=cro.id)
    session.add(prod)
    session.commit()
    ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=0)
    order = sales.create_sale(session, cashier_id=cashier.id,
                              lines=[_line(prod.id, qty=2)],
                              payments=[PaymentInput("cash", 180000, 180000)])
    assert session.get(Ingredient, cro.id).stock_qty == 8

    refund = sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                               reason="передумал", item_qty=None)
    assert refund.amount_tiyn == 180000
    assert session.get(Order, order.id).status == "refunded"
    # штучный товар вернулся на склад
    assert session.get(Ingredient, cro.id).stock_qty == 10


def test_partial_refund_sets_partial_status(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id, qty=3)],
                              payments=[PaymentInput("cash", 450000, 450000)])
    item = session.query(OrderItem).filter_by(order_id=order.id).one()
    refund = sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                               reason="одну убрать", item_qty={item.id: 1})
    assert refund.amount_tiyn == 150000
    assert session.get(Order, order.id).status == "partially_refunded"
    assert session.get(OrderItem, item.id).refunded_qty == 1
    # приготовленный напиток НЕ восстанавливает ингредиенты
    assert session.get(Ingredient, milk.id).stock_qty == 1000 - 600


def test_cannot_refund_more_than_bought(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(session, cashier_id=cashier.id, lines=[_line(latte.id, qty=1)],
                              payments=[PaymentInput("cash", 150000, 150000)])
    item = session.query(OrderItem).filter_by(order_id=order.id).one()
    with pytest.raises(ValueError):
        sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                          reason="слишком много", item_qty={item.id: 5})
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_sales_service.py -q`
Expected: FAIL — `AttributeError: module 'app.services.sales_service' has no attribute 'refund_sale'`

- [ ] **Step 3: Реализация (добавить в app/services/sales_service.py)**

```python
from app.models import Refund, RefundItem


def refund_sale(
    session: Session,
    *,
    order_id: int,
    cashier_id: int,
    reason: str,
    item_qty: dict[int, int] | None = None,
) -> Refund:
    """Возврат. item_qty=None — полный возврат всех оставшихся позиций.

    Штучные (retail) позиции возвращаются на склад; приготовленные — нет.
    """
    if not reason or not reason.strip():
        raise ValueError("Причина возврата обязательна")
    order = session.get(Order, order_id)
    if order is None:
        raise ValueError(f"Заказ {order_id} не найден")
    if order.status == "refunded":
        raise ValueError("Заказ уже полностью возвращён")

    items = session.scalars(select(OrderItem).where(OrderItem.order_id == order_id)).all()
    by_id = {it.id: it for it in items}

    if item_qty is None:
        plan = {it.id: it.qty - it.refunded_qty for it in items if it.qty - it.refunded_qty > 0}
    else:
        plan = {}
        for item_id, q in item_qty.items():
            it = by_id.get(item_id)
            if it is None:
                raise ValueError(f"Позиция {item_id} не в этом заказе")
            if q <= 0 or q > it.qty - it.refunded_qty:
                raise ValueError("Некорректное количество возврата")
            plan[item_id] = q

    if not plan:
        raise ValueError("Нечего возвращать")

    refund = Refund(order_id=order_id, amount_tiyn=0, reason=reason.strip(), cashier_id=cashier_id)
    session.add(refund)
    session.flush()

    refunded_amount = 0
    for item_id, q in plan.items():
        it = by_id[item_id]
        unit_net = it.line_total_tiyn // it.qty  # цена единицы после позиционной скидки
        item_amount = unit_net * q
        refunded_amount += item_amount
        it.refunded_qty += q
        session.add(RefundItem(refund_id=refund.id, order_item_id=item_id, qty=q,
                               amount_tiyn=item_amount))
        # возврат штучного товара на склад
        product = session.get(Product, it.product_id) if it.product_id else None
        if product is not None and product.kind == "retail" and product.ingredient_id is not None:
            apply_move(
                session, product.ingredient_id,
                qty_delta=q, kind="refund",
                ref_type="order", ref_id=order_id, commit=False,
            )

    refund.amount_tiyn = refunded_amount
    all_refunded = all(it.refunded_qty >= it.qty for it in items)
    order.status = "refunded" if all_refunded else "partially_refunded"
    session.commit()
    return refund
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_sales_service.py -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/sales_service.py tests/test_sales_service.py
git commit -m "feat: full and partial refunds with retail restock"
```

---

### Task 9: Сервис модификаторов (CRUD + привязка)

**Files:**
- Create: `app/services/modifier_service.py`
- Test: `tests/test_modifier_service.py`

- [ ] **Step 1: Падающий тест**

`tests/test_modifier_service.py`:
```python
import pytest

from app.models import Category, Modifier, ModifierItem, Product, ProductModifierGroup
from app.services import modifier_service as ms


def _product(session):
    cat = Category(name="Кофе")
    session.add(cat)
    session.flush()
    p = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(p)
    session.commit()
    return p


def test_create_group_and_modifier(session):
    grp = ms.create_group(session, "Объём", is_required=True)
    m = ms.add_modifier(session, group_id=grp.id, name="L", price_delta_tiyn=20000)
    assert m.group_id == grp.id
    groups = ms.groups_for_product(session, _product(session).id)
    assert groups == []  # ещё не привязана


def test_attach_group_to_product(session):
    p = _product(session)
    grp = ms.create_group(session, "Объём")
    ms.add_modifier(session, group_id=grp.id, name="M", price_delta_tiyn=0)
    ms.attach_group(session, product_id=p.id, group_id=grp.id)
    groups = ms.groups_for_product(session, p.id)
    assert len(groups) == 1
    g, mods = groups[0]
    assert g.name == "Объём"
    assert [m.name for m in mods] == ["M"]


def test_attach_is_idempotent(session):
    p = _product(session)
    grp = ms.create_group(session, "Молоко")
    ms.attach_group(session, product_id=p.id, group_id=grp.id)
    ms.attach_group(session, product_id=p.id, group_id=grp.id)  # повтор не дублирует
    assert session.query(ProductModifierGroup).count() == 1


def test_modifier_ingredient_link(session):
    from app.models import Ingredient
    milk = Ingredient(name="Молоко", unit="мл")
    session.add(milk)
    session.flush()
    grp = ms.create_group(session, "Молоко")
    m = ms.add_modifier(session, group_id=grp.id, name="Овсяное +50мл", price_delta_tiyn=15000)
    ms.set_modifier_item(session, modifier_id=m.id, ingredient_id=milk.id, qty=50)
    item = session.query(ModifierItem).one()
    assert item.qty == 50
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_modifier_service.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/services/modifier_service.py`:
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Modifier,
    ModifierGroup,
    ModifierItem,
    ProductModifierGroup,
)


def create_group(session: Session, name: str, is_required: bool = False) -> ModifierGroup:
    grp = ModifierGroup(name=name, is_required=is_required)
    session.add(grp)
    session.commit()
    return grp


def add_modifier(session: Session, *, group_id: int, name: str, price_delta_tiyn: int = 0) -> Modifier:
    m = Modifier(group_id=group_id, name=name, price_delta_tiyn=price_delta_tiyn)
    session.add(m)
    session.commit()
    return m


def attach_group(session: Session, *, product_id: int, group_id: int) -> None:
    exists = session.scalar(
        select(ProductModifierGroup).where(
            ProductModifierGroup.product_id == product_id,
            ProductModifierGroup.group_id == group_id,
        )
    )
    if exists is not None:
        return
    session.add(ProductModifierGroup(product_id=product_id, group_id=group_id))
    session.commit()


def set_modifier_item(session: Session, *, modifier_id: int, ingredient_id: int, qty: int) -> ModifierItem:
    if qty <= 0:
        raise ValueError("Количество списания должно быть больше нуля")
    existing = session.scalar(
        select(ModifierItem).where(ModifierItem.modifier_id == modifier_id)
    )
    if existing is not None:
        existing.ingredient_id = ingredient_id
        existing.qty = qty
        session.commit()
        return existing
    item = ModifierItem(modifier_id=modifier_id, ingredient_id=ingredient_id, qty=qty)
    session.add(item)
    session.commit()
    return item


def groups_for_product(session: Session, product_id: int) -> list[tuple[ModifierGroup, list[Modifier]]]:
    groups = session.scalars(
        select(ModifierGroup)
        .join(ProductModifierGroup, ProductModifierGroup.group_id == ModifierGroup.id)
        .where(ProductModifierGroup.product_id == product_id)
    ).all()
    result = []
    for g in groups:
        mods = session.scalars(
            select(Modifier).where(Modifier.group_id == g.id, Modifier.is_active)
        ).all()
        result.append((g, list(mods)))
    return result
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_modifier_service.py -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/modifier_service.py tests/test_modifier_service.py
git commit -m "feat: modifier service (groups, modifiers, attach, deduction)"
```

---

### Task 10: Сервис пользователей — аутентификация

**Files:**
- Create: `app/services/user_service.py`
- Test: `tests/test_user_service.py`

- [ ] **Step 1: Падающий тест**

`tests/test_user_service.py`:
```python
import pytest

from app.auth import hash_pin
from app.models import User
from app.services import user_service as us


def _user(session, tid=42, pin="1234", role="cashier", active=True):
    u = User(telegram_id=tid, name="Кассир", role=role, is_active=active, pin_hash=hash_pin(pin))
    session.add(u)
    session.commit()
    return u


def test_active_users_for_login(session):
    _user(session, tid=1, role="cashier")
    _user(session, tid=2, role="admin")
    _user(session, tid=3, active=False)
    users = us.active_users(session)
    assert {u.telegram_id for u in users} == {1, 2}


def test_authenticate_pin_ok(session):
    u = _user(session, pin="4821")
    got = us.authenticate(session, user_id=u.id, pin="4821")
    assert got is not None
    assert got.id == u.id


def test_authenticate_wrong_pin(session):
    u = _user(session, pin="4821")
    assert us.authenticate(session, user_id=u.id, pin="0000") is None


def test_authenticate_inactive_rejected(session):
    u = _user(session, pin="1111", active=False)
    assert us.authenticate(session, user_id=u.id, pin="1111") is None


def test_authenticate_no_pin_set(session):
    u = User(telegram_id=9, name="Без пина", role="cashier", is_active=True)
    session.add(u)
    session.commit()
    assert us.authenticate(session, user_id=u.id, pin="1234") is None


def test_user_from_init_data_valid(session):
    import hashlib
    import hmac
    from urllib.parse import urlencode
    token = "1234567890:TEST-TOKEN"
    u = _user(session, tid=777)
    params = {"auth_date": "1752900000", "user": '{"id":777}'}
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    init = urlencode({**params, "hash": h})
    got = us.user_from_init_data(session, init, token)
    assert got is not None and got.telegram_id == 777


def test_user_from_init_data_bad_signature(session):
    _user(session, tid=777)
    assert us.user_from_init_data(session, "auth_date=1&user=%7B%22id%22%3A777%7D&hash=deadbeef", "tok") is None
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_user_service.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/services/user_service.py`:
```python
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import validate_init_data, verify_pin
from app.models import User


def active_users(session: Session) -> list[User]:
    return list(session.scalars(
        select(User).where(User.is_active).order_by(User.name)
    ).all())


def authenticate(session: Session, *, user_id: int, pin: str) -> User | None:
    user = session.get(User, user_id)
    if user is None or not user.is_active or not user.pin_hash:
        return None
    if not verify_pin(pin, user.pin_hash):
        return None
    return user


def user_from_init_data(session: Session, init_data: str, bot_token: str) -> User | None:
    data = validate_init_data(init_data, bot_token)
    if data is None:
        return None
    raw_user = data.get("user")
    if not raw_user:
        return None
    try:
        telegram_id = int(json.loads(raw_user)["id"])
    except (ValueError, KeyError, TypeError):
        return None
    return session.scalars(
        select(User).where(User.telegram_id == telegram_id, User.is_active)
    ).first()
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_user_service.py -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/user_service.py tests/test_user_service.py
git commit -m "feat: user service (pin auth, initData lookup)"
```

---

### Task 11: Пин-гвард и страница входа

**Files:**
- Create: `app/ui/guard.py`, `app/ui/login.py`
- Modify: `app/ui/__init__.py`
- Test: `tests/test_guard.py`

Логика гварда покрывается юнит-тестом; страница входа проверяется вручную.

- [ ] **Step 1: Падающий тест**

`tests/test_guard.py`:
```python
from app.ui.guard import current_user_id, is_admin


class _FakeStorage:
    def __init__(self, data):
        self.user = data


def test_current_user_id_reads_storage():
    assert current_user_id(_FakeStorage({"user_id": 7})) == 7
    assert current_user_id(_FakeStorage({})) is None


def test_is_admin_flag():
    assert is_admin(_FakeStorage({"role": "admin"})) is True
    assert is_admin(_FakeStorage({"role": "cashier"})) is False
    assert is_admin(_FakeStorage({})) is False
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_guard.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/ui/guard.py`:
```python
from nicegui import app, ui


def current_user_id(storage=None) -> int | None:
    store = storage if storage is not None else app.storage
    return store.user.get("user_id")


def is_admin(storage=None) -> bool:
    store = storage if storage is not None else app.storage
    return store.user.get("role") == "admin"


def require_user() -> bool:
    """Вызывать в начале страницы. False + редирект на /login, если не авторизован."""
    if current_user_id() is None:
        ui.navigate.to("/login")
        return False
    return True


def require_admin() -> bool:
    if not require_user():
        return False
    if not is_admin():
        ui.label("Доступ только для администратора").classes("text-red-600 text-xl")
        return False
    return True


def login_user(user) -> None:
    app.storage.user["user_id"] = user.id
    app.storage.user["role"] = user.role
    app.storage.user["name"] = user.name


def logout() -> None:
    app.storage.user.clear()
```

`app/ui/login.py`:
```python
from nicegui import ui

from app.db import SessionLocal
from app.services import user_service as us
from app.ui.guard import login_user

# простой лимит попыток пин-кода на вкладку (сбрасывается перезагрузкой)
_MAX_ATTEMPTS = 5


@ui.page("/login")
def login_page() -> None:
    ui.label("Вход").classes("text-2xl font-bold")
    with SessionLocal() as session:
        users = {u.id: f"{u.name} ({u.role})" for u in us.active_users(session)}

    if not users:
        ui.label("Нет пользователей. Запустите seed.py").classes("text-red-600")
        return

    state = {"attempts": 0}
    user_sel = ui.select(users, label="Пользователь")
    pin_in = ui.input("Пин-код", password=True).props("inputmode=numeric")

    def do_login() -> None:
        if state["attempts"] >= _MAX_ATTEMPTS:
            ui.notify("Слишком много попыток. Перезагрузите страницу.", color="red")
            return
        if not user_sel.value or not pin_in.value:
            ui.notify("Выберите пользователя и введите пин", color="red")
            return
        with SessionLocal() as session:
            user = us.authenticate(session, user_id=user_sel.value, pin=pin_in.value)
        if user is None:
            state["attempts"] += 1
            pin_in.value = ""
            ui.notify("Неверный пин-код", color="red")
            return
        login_user(user)
        ui.navigate.to("/cashier")

    pin_in.on("keydown.enter", lambda _: do_login())
    ui.button("Войти", on_click=do_login)
```

`app/ui/__init__.py` — обновить `register_pages` (импортировать новые страницы) и добавить гвард в admin-страницы. Заменить содержимое на:
```python
def register_pages() -> None:
    """Импортирует модули страниц NiceGUI (каждый регистрирует свои @ui.page)."""
    from app.ui import (  # noqa: F401
        admin_menu,
        admin_modifiers,
        admin_stock,
        cashier,
        login,
    )
```

- [ ] **Step 4: Добавить гвард в существующие admin-страницы**

В начале функций `admin_menu_page` (`app/ui/admin_menu.py`) и `admin_stock_page` (`app/ui/admin_stock.py`) добавить первой строкой тела:
```python
    from app.ui.guard import require_admin
    if not require_admin():
        return
```

- [ ] **Step 5: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_guard.py -q`
Expected: PASS (полный прогон отложить до задачи 12 — `register_pages` импортирует ещё не созданный `admin_modifiers`/`cashier`; если запускаете полный набор сейчас, ожидается ImportError на этих модулях — это нормально, закрывается в задачах 12-13).

- [ ] **Step 6: Commit**

```bash
git add app/ui/guard.py app/ui/login.py app/ui/__init__.py app/ui/admin_menu.py app/ui/admin_stock.py tests/test_guard.py
git commit -m "feat: pin login page and page guards"
```

---

### Task 12: Админка модификаторов

**Files:**
- Create: `app/ui/admin_modifiers.py`

Логика в `modifier_service` уже покрыта тестами; здесь связка UI и ручная проверка.

- [ ] **Step 1: Реализация**

`app/ui/admin_modifiers.py`:
```python
from nicegui import ui
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Ingredient, Modifier, ModifierGroup, Product
from app.services import modifier_service as ms


@ui.page("/admin/modifiers")
def admin_modifiers_page() -> None:
    from app.ui.guard import require_admin
    if not require_admin():
        return

    ui.label("Модификаторы").classes("text-2xl font-bold")

    groups_box = ui.column().classes("w-full max-w-3xl gap-2")

    def refresh() -> None:
        groups_box.clear()
        with groups_box, SessionLocal() as session:
            groups = session.scalars(select(ModifierGroup)).all()
            ing_options = {
                i.id: f"{i.name} ({i.unit})"
                for i in session.scalars(select(Ingredient).where(Ingredient.is_active)).all()
            }
            for g in groups:
                req = "обязательная" if g.is_required else "необязательная"
                ui.label(f"{g.name} — {req}").classes("text-xl mt-4")
                mods = session.scalars(select(Modifier).where(Modifier.group_id == g.id)).all()
                for m in mods:
                    ui.label(f"  {m.name}: +{m.price_delta_tiyn / 100:.0f} тг").classes("text-gray-600")
                with ui.row().classes("items-end gap-2"):
                    mn = ui.input("Новый модификатор")
                    mp = ui.number("Наценка, тг", value=0, min=0, format="%.0f")
                    mi = ui.select(ing_options, label="Списывать ингредиент (необяз.)")
                    mq = ui.number("Кол-во", value=0, min=0, format="%.0f")

                    def add_mod(gid=g.id, name=mn, price=mp, ing=mi, qty=mq) -> None:
                        if not name.value:
                            ui.notify("Введите название", color="red")
                            return
                        try:
                            with SessionLocal() as s:
                                mod = ms.add_modifier(s, group_id=gid, name=name.value,
                                                      price_delta_tiyn=round((price.value or 0) * 100))
                                if ing.value and qty.value:
                                    ms.set_modifier_item(s, modifier_id=mod.id,
                                                         ingredient_id=ing.value, qty=round(qty.value))
                        except (ValueError, IntegrityError) as e:
                            ui.notify(str(e), color="red")
                            return
                        refresh()

                    ui.button("Добавить", on_click=add_mod)

    with ui.expansion("Добавить группу").classes("w-full max-w-3xl"):
        gn = ui.input("Название группы (напр. Объём)")
        gr = ui.checkbox("Обязательная")

        def add_group() -> None:
            if not gn.value:
                return
            try:
                with SessionLocal() as s:
                    ms.create_group(s, gn.value, is_required=gr.value)
            except (ValueError, IntegrityError) as e:
                ui.notify(str(e), color="red")
                return
            gn.value = ""
            refresh()

        ui.button("Создать группу", on_click=add_group)

    with ui.expansion("Привязать группу к товару").classes("w-full max-w-3xl"):
        with SessionLocal() as session:
            prod_opts = {
                p.id: p.name
                for p in session.scalars(
                    select(Product).where(Product.kind == "prepared", Product.is_active)
                ).all()
            }
            grp_opts = {g.id: g.name for g in session.scalars(select(ModifierGroup)).all()}
        ps = ui.select(prod_opts, label="Товар")
        gs = ui.select(grp_opts, label="Группа")

        def do_attach() -> None:
            if not (ps.value and gs.value):
                ui.notify("Выберите товар и группу", color="red")
                return
            with SessionLocal() as s:
                ms.attach_group(s, product_id=ps.value, group_id=gs.value)
            ui.notify("Привязано")

        ui.button("Привязать", on_click=do_attach)

    refresh()
```

- [ ] **Step 2: Запустить тесты (полный набор)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (кроме случая, если ещё не создан `cashier` — тогда см. задачу 13; выполняйте 12 и 13 подряд).

- [ ] **Step 3: Ручная проверка**

Запустить приложение (`.venv\Scripts\python -m app.main`), войти на `/login`, открыть `/admin/modifiers`: создать группу «Объём», добавить модификаторы «M» (0) и «L» (200 тг), привязать к «Латте». Остановить сервер.

- [ ] **Step 4: Commit**

```bash
git add app/ui/admin_modifiers.py
git commit -m "feat: admin ui for modifiers"
```

---

### Task 13: Экран кассира — смена

**Files:**
- Create: `app/ui/cashier.py`

- [ ] **Step 1: Реализация (страница смены; продажа добавится в задаче 14)**

`app/ui/cashier.py`:
```python
from nicegui import ui

from app.db import SessionLocal
from app.services import shift_service as ss
from app.ui.guard import current_user_id, require_user


@ui.page("/cashier")
def cashier_page() -> None:
    if not require_user():
        return
    uid = current_user_id()

    with SessionLocal() as session:
        shift = ss.current_open_shift(session)

    ui.label("Касса").classes("text-2xl font-bold")

    if shift is None:
        ui.label("Смена не открыта").classes("text-lg")
        cash = ui.number("Стартовая наличность, тг", value=0, min=0, format="%.0f")

        def do_open() -> None:
            with SessionLocal() as s:
                ss.open_shift(s, cashier_id=uid, opening_cash_tiyn=round((cash.value or 0) * 100))
            ui.navigate.to("/cashier")

        ui.button("Открыть смену", on_click=do_open)
        return

    ui.label(f"Смена открыта (№{shift.id})").classes("text-lg text-green-700")
    ui.button("Экран продажи", on_click=lambda: ui.navigate.to("/cashier/sale"))

    with ui.expansion("Инкассация").classes("w-full max-w-md"):
        amt = ui.number("Сумма изъятия, тг", value=0, min=0, format="%.0f")
        note = ui.input("Примечание")

        def do_collect() -> None:
            try:
                with SessionLocal() as s:
                    ss.add_collection(s, shift_id=shift.id,
                                      amount_tiyn=round((amt.value or 0) * 100), note=note.value or None)
            except ValueError as e:
                ui.notify(str(e), color="red")
                return
            ui.notify("Инкассация записана")
            amt.value = 0

        ui.button("Изъять", on_click=do_collect)

    with ui.expansion("Закрыть смену").classes("w-full max-w-md"):
        with SessionLocal() as s:
            expected = ss.expected_cash_tiyn(s, shift.id)
        ui.label(f"Ожидается в кассе: {expected / 100:.0f} тг")
        counted = ui.number("Фактически в кассе, тг", value=expected / 100, min=0, format="%.0f")

        def do_close() -> None:
            with SessionLocal() as s:
                closed = ss.close_shift(s, shift_id=shift.id,
                                        counted_cash_tiyn=round((counted.value or 0) * 100))
            diff = (closed.counted_cash_tiyn - closed.expected_cash_tiyn) / 100
            ui.notify(f"Смена закрыта. Расхождение: {diff:+.0f} тг")
            ui.navigate.to("/cashier")

        ui.button("Закрыть смену", on_click=do_close, color="red")
```

- [ ] **Step 2: Запустить тесты (полный набор)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (теперь `register_pages` находит все модули).

- [ ] **Step 3: Ручная проверка**

Запустить приложение, войти, открыть смену (стартовая 5000 тг), проверить инкассацию, увидеть ожидаемую сумму, закрыть смену с расхождением. Остановить сервер.

- [ ] **Step 4: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat: cashier shift screen (open, collection, close)"
```

---

### Task 14: Экран продажи и оплаты

**Files:**
- Modify: `app/ui/cashier.py`

Экран продажи собирает корзину в памяти, показывает модификаторы, скидку, оплату (наличные/карта/Kaspi, раздельно) и проводит чек через `sales_service.create_sale`.

- [ ] **Step 1: Реализация (добавить в app/ui/cashier.py)**

```python
from app.services import modifier_service as ms
from app.services import sales_service as sales
from app.services.catalog_service import list_menu
from app.services.pricing import PaymentInput


@ui.page("/cashier/sale")
def sale_page() -> None:
    if not require_user():
        return
    uid = current_user_id()

    with SessionLocal() as session:
        if ss.current_open_shift(session) is None:
            ui.label("Смена не открыта").classes("text-red-600 text-xl")
            ui.button("К смене", on_click=lambda: ui.navigate.to("/cashier"))
            return
        menu = list_menu(session)

    # корзина: список dict(product_id, name, base_price_tiyn, qty, modifier_ids, mod_labels)
    cart: list[dict] = []

    ui.label("Экран продажи").classes("text-2xl font-bold")
    with ui.row().classes("w-full gap-4"):
        products_col = ui.column().classes("flex-1")
        cart_col = ui.column().classes("w-96")

    def add_to_cart(product) -> None:
        with SessionLocal() as session:
            groups = ms.groups_for_product(session, product.id)
        if not groups:
            cart.append({"product_id": product.id, "name": product.name,
                         "base_price_tiyn": product.price_tiyn, "qty": 1,
                         "modifier_ids": [], "mod_labels": []})
            render_cart()
            return
        _open_modifier_dialog(product, groups)

    def _open_modifier_dialog(product, groups) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(product.name).classes("text-xl")
            selectors = []
            for g, mods in groups:
                opts = {m.id: f"{m.name} (+{m.price_delta_tiyn/100:.0f})" for m in mods}
                sel = ui.select(opts, label=g.name)
                selectors.append((g, sel, {m.id: m for m in mods}))

            def confirm() -> None:
                chosen_ids, labels = [], []
                for g, sel, by_id in selectors:
                    if sel.value:
                        chosen_ids.append(sel.value)
                        labels.append(by_id[sel.value].name)
                    elif g.is_required:
                        ui.notify(f"Выберите: {g.name}", color="red")
                        return
                cart.append({"product_id": product.id, "name": product.name,
                             "base_price_tiyn": product.price_tiyn, "qty": 1,
                             "modifier_ids": chosen_ids, "mod_labels": labels})
                dialog.close()
                render_cart()

            ui.button("Добавить", on_click=confirm)
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    with products_col:
        for cat, products in menu:
            ui.label(cat.name).classes("text-xl mt-2")
            with ui.row().classes("flex-wrap gap-2"):
                for p in products:
                    ui.button(f"{p.name}\n{p.price_tiyn/100:.0f} тг",
                              on_click=lambda p=p: add_to_cart(p)).classes("w-40 h-20")

    def cart_total_tiyn() -> int:
        total = 0
        for c in cart:
            total += (c["base_price_tiyn"]) * c["qty"]
            with SessionLocal() as s:
                for mid in c["modifier_ids"]:
                    from app.models import Modifier
                    m = s.get(Modifier, mid)
                    total += (m.price_delta_tiyn if m else 0) * c["qty"]
        return total

    def render_cart() -> None:
        cart_col.clear()
        with cart_col:
            ui.label("Чек").classes("text-xl")
            if not cart:
                ui.label("Пусто").classes("text-gray-500")
            for idx, c in enumerate(cart):
                label = c["name"] + (f" [{', '.join(c['mod_labels'])}]" if c["mod_labels"] else "")
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{label} ×{c['qty']}").classes("flex-1")

                    def inc(i=idx) -> None:
                        cart[i]["qty"] += 1
                        render_cart()

                    def dec(i=idx) -> None:
                        cart[i]["qty"] -= 1
                        if cart[i]["qty"] <= 0:
                            cart.pop(i)
                        render_cart()

                    ui.button("−", on_click=dec)
                    ui.button("+", on_click=inc)
            ui.separator()
            ui.label(f"Итого: {cart_total_tiyn()/100:.0f} тг").classes("text-lg font-bold")
            if cart:
                ui.button("Оплата", on_click=open_payment).classes("w-full")

    def open_payment() -> None:
        total = cart_total_tiyn()
        with ui.dialog() as dialog, ui.card():
            ui.label(f"К оплате: {total/100:.0f} тг").classes("text-xl")
            method = ui.select({"cash": "Наличные", "card": "Карта", "kaspi_qr": "Kaspi QR"},
                               label="Способ", value="cash")
            tendered = ui.number("Получено (наличные), тг", value=total / 100, format="%.0f")

            def confirm_payment() -> None:
                pay_method = method.value
                if pay_method == "cash":
                    tnd = round((tendered.value or 0) * 100)
                    if tnd < total:
                        ui.notify("Получено меньше суммы чека", color="red")
                        return
                    payments = [PaymentInput("cash", total, tnd)]
                else:
                    payments = [PaymentInput(pay_method, total, None)]
                try:
                    with SessionLocal() as s:
                        lines = [sales.SaleLineInput(product_id=c["product_id"], qty=c["qty"],
                                                     modifier_ids=c["modifier_ids"]) for c in cart]
                        order = sales.create_sale(s, cashier_id=uid, lines=lines, payments=payments)
                        num = order.number
                        change = payments[0].tendered_tiyn - total if pay_method == "cash" else 0
                except (ValueError, PermissionError) as e:
                    ui.notify(str(e), color="red")
                    return
                dialog.close()
                cart.clear()
                render_cart()
                msg = f"Заказ №{num} проведён."
                if change:
                    msg += f" Сдача: {change/100:.0f} тг"
                ui.notify(msg, color="green")

            ui.button("Провести", on_click=confirm_payment)
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    ui.button("← К смене", on_click=lambda: ui.navigate.to("/cashier"))
    render_cart()
```

- [ ] **Step 2: Запустить тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 3: Ручная проверка**

Войти, открыть смену, на экране продажи: добавить «Латте» (выбрать объём), увеличить количество, добавить штучный товар, нажать «Оплата», провести наличными со сдачей и отдельно — Kaspi. Проверить на `/admin/stock`, что остатки уменьшились. Остановить сервер.

- [ ] **Step 4: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat: sale screen with modifiers, cart and payment"
```

---

### Task 15: Экран возврата

**Files:**
- Modify: `app/ui/cashier.py`

- [ ] **Step 1: Реализация (добавить в app/ui/cashier.py)**

```python
from app.models import Order, OrderItem


@ui.page("/cashier/refunds")
def refunds_page() -> None:
    if not require_user():
        return
    uid = current_user_id()

    ui.label("Возвраты").classes("text-2xl font-bold")
    box = ui.column().classes("w-full max-w-2xl gap-2")

    def refresh() -> None:
        box.clear()
        with box, SessionLocal() as session:
            shift = ss.current_open_shift(session)
            if shift is None:
                ui.label("Смена не открыта").classes("text-red-600")
                return
            orders = session.query(Order).filter(
                Order.shift_id == shift.id,
                Order.status.in_(["paid", "partially_refunded"]),
            ).order_by(Order.number.desc()).all()
            if not orders:
                ui.label("Нет заказов для возврата").classes("text-gray-500")
            for o in orders:
                items = session.query(OrderItem).filter_by(order_id=o.id).all()
                names = ", ".join(f"{it.name}×{it.qty - it.refunded_qty}"
                                  for it in items if it.qty - it.refunded_qty > 0)
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"№{o.number}: {names} — {o.total_tiyn/100:.0f} тг").classes("flex-1")
                    ui.button("Вернуть полностью",
                              on_click=lambda oid=o.id: _do_full_refund(oid))

    def _do_full_refund(order_id: int) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label("Причина возврата").classes("text-lg")
            reason = ui.input("Причина")

            def confirm() -> None:
                if not reason.value or not reason.value.strip():
                    ui.notify("Укажите причину", color="red")
                    return
                try:
                    with SessionLocal() as s:
                        sales.refund_sale(s, order_id=order_id, cashier_id=uid,
                                          reason=reason.value, item_qty=None)
                except ValueError as e:
                    ui.notify(str(e), color="red")
                    return
                dialog.close()
                ui.notify("Возврат оформлен", color="green")
                refresh()

            ui.button("Подтвердить возврат", on_click=confirm, color="red")
            ui.button("Отмена", on_click=dialog.close)
        dialog.open()

    refresh()
```

Также добавить кнопку перехода на возвраты в `cashier_page` (после «Экран продажи»):
```python
    ui.button("Возвраты", on_click=lambda: ui.navigate.to("/cashier/refunds"))
```

- [ ] **Step 2: Запустить тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 3: Ручная проверка**

Провести заказ, открыть «Возвраты», вернуть его полностью с причиной, убедиться, что он пропал из списка и (для штучного товара) остаток вырос. Остановить сервер.

- [ ] **Step 4: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat: refund screen (full refund with reason)"
```

---

### Task 16: Сид, интеграционный тест и README

**Files:**
- Modify: `seed.py`, `README.md`
- Create: `tests/test_sales_integration.py`

- [ ] **Step 1: Интеграционный тест сквозного сценария**

`tests/test_sales_integration.py`:
```python
from app.auth import hash_pin
from app.models import Category, Ingredient, Product, RecipeItem, User
from app.services import sales_service as sales
from app.services import shift_service as ss
from app.services import user_service as us
from app.services.pricing import PaymentInput


def test_end_to_end_login_shift_sale_refund_close(session):
    # пользователь и меню
    cashier = User(telegram_id=100, name="Кассир", role="cashier",
                   discount_limit_percent=10, pin_hash=hash_pin("4821"))
    session.add(cashier)
    cat = Category(name="Кофе")
    session.add(cat)
    session.flush()
    milk = Ingredient(name="Молоко", unit="мл", stock_qty=1000, avg_cost_tiyn=50.0)
    beans = Ingredient(name="Кофе зерно", unit="г", stock_qty=100, avg_cost_tiyn=300.0)
    session.add_all([milk, beans])
    session.flush()
    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(latte)
    session.flush()
    session.add_all([
        RecipeItem(product_id=latte.id, ingredient_id=beans.id, qty=18),
        RecipeItem(product_id=latte.id, ingredient_id=milk.id, qty=200),
    ])
    session.commit()

    # вход по пину
    assert us.authenticate(session, user_id=cashier.id, pin="4821") is not None

    # смена
    shift = ss.open_shift(session, cashier_id=cashier.id, opening_cash_tiyn=500000)

    # продажа
    order = sales.create_sale(
        session, cashier_id=cashier.id,
        lines=[sales.SaleLineInput(product_id=latte.id, qty=2)],
        payments=[PaymentInput("cash", 300000, 300000)],
    )
    assert order.total_tiyn == 300000
    assert session.get(Ingredient, milk.id).stock_qty == 600

    # частичный возврат одной порции — приготовленный напиток склад не возвращает
    from app.models import OrderItem
    oi = session.query(OrderItem).filter_by(order_id=order.id).one()
    sales.refund_sale(session, order_id=order.id, cashier_id=cashier.id,
                      reason="одну убрать", item_qty={oi.id: 1})

    # ожидаемая наличность: 500000 старт + 300000 продажа - 150000 возврат
    assert ss.expected_cash_tiyn(session, shift.id) == 650000

    # закрытие смены
    closed = ss.close_shift(session, shift_id=shift.id, counted_cash_tiyn=650000)
    assert closed.status == "closed"
    assert closed.expected_cash_tiyn == 650000
```

- [ ] **Step 2: Запустить интеграционный тест**

Run: `.venv\Scripts\python -m pytest tests/test_sales_integration.py -q`
Expected: все PASS

- [ ] **Step 3: Расширить seed.py**

В `seed.py` в функции `seed`, после создания админа и до `s.commit()`, добавить кассира с пин-кодом и объёмы для латте. Заменить блок создания пользователя и добавить импорт:

В начало файла добавить:
```python
from app.auth import hash_pin
from app.models import Modifier, ModifierGroup, ProductModifierGroup
```

После строки `s.add(User(telegram_id=admin_telegram_id, name="Владелец", role="admin"))` добавить:
```python
        s.add(User(telegram_id=admin_telegram_id + 1, name="Кассир", role="cashier",
                   discount_limit_percent=10, pin_hash=hash_pin("1234")))
```

После создания `latte` и его тех-карты (перед финальным `s.commit()`), добавить группу объёма и привязать:
```python
        size = ModifierGroup(name="Объём", is_required=True)
        s.add(size)
        s.flush()
        s.add_all([
            Modifier(group_id=size.id, name="M", price_delta_tiyn=0),
            Modifier(group_id=size.id, name="L", price_delta_tiyn=20000),
            ProductModifierGroup(product_id=latte.id, group_id=size.id),
        ])
```

- [ ] **Step 4: Проверить seed**

Run:
```powershell
Remove-Item pos.db -ErrorAction SilentlyContinue
.venv\Scripts\python seed.py 123456789
```
Expected: «Готово: админ и пример меню созданы». Кассир входит пином `1234`.

- [ ] **Step 5: Дополнить README.md**

Добавить в `README.md` после раздела про первый запуск новый раздел:
````markdown
## Работа кассира

1. Открыть Mini App в Telegram (или локально `http://localhost:8080/login`).
2. Войти: выбрать пользователя, ввести пин-код (в seed кассир — пин `1234`).
3. Открыть смену, указав стартовую наличность.
4. Экран продажи: категория → товар → (модификаторы) → корзина → «Оплата»
   (наличные со сдачей, карта или Kaspi QR).
5. Возвраты — на отдельном экране, с указанием причины.
6. В конце — закрыть смену: система покажет ожидаемую наличность, кассир вводит фактическую.

Разделы администратора: `/admin/menu`, `/admin/stock`, `/admin/modifiers` (только для роли admin).
````

- [ ] **Step 6: Полный прогон и ручная проверка**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS.
Затем прогнать полный сценарий из README вручную (вход → смена → продажа с модификатором → возврат → закрытие). Остановить сервер.

- [ ] **Step 7: Commit**

```bash
git add seed.py README.md tests/test_sales_integration.py
git commit -m "feat: seed cashier and modifiers, end-to-end test, README"
```

---

## Самопроверка плана

- **Покрытие спецификации (разделы 4.1-4.6):**
  - Продажа/чек, несколько позиций, изменение количества, удаление до оплаты — задачи 7, 14 (корзина в памяти).
  - Модификаторы с наценкой и списанием — задачи 5, 9, 12, 14.
  - Скидка на позицию/чек с лимитом кассира — задачи 4, 7 (интерактивное одобрение админом отложено на этап 3, зафиксировано в «Решениях»).
  - Возврат полный/частичный с причиной — задача 8, 15.
  - Оплата наличные/карта/Kaspi (ручная) + разделение + сдача — задачи 4, 7, 14.
  - Меню/товары приготовленные/штучные, автосписание — задачи 5, 7.
  - Смены: открытие, инкассация, закрытие со сверкой — задачи 1, 6, 13.
  - Атомарность чека и списания — задача 7 (одна транзакция) + интеграционный тест задача 16.
- **Бэклог этапа 1 закрыт:** пин-гвард на страницах и вход (задача 11), проверка `apply_move(commit=False)` в транзакции продажи с интеграционным тестом (задачи 7, 16). Остаток бэклога (свежесть `auth_date`, закрытие aiohttp-сессии бота, `ingredient_id` обязателен для retail в UI создания, человекочитаемые ошибки) — не входит в сквозной сценарий продаж; переносится в бэклог этапа 3 (уведомления/дашборд) и отмечен ниже.
- **Отложено в бэклог этапа 3:** проверка свежести `auth_date` при входе через initData; требование `ingredient_id` для retail в форме создания товара; закрытие сессии `Bot` при остановке; уведомления админу (открытие/закрытие смены, крупный возврат, низкий остаток); интерактивное одобрение скидки.
- **Отложено в бэклог этапа 4 (отчёты/сверка) — из ревью ядра этапа 2:**
  - Возврат привязан к смене продажи (`Refund` через `Order.shift_id`), а не к смене, из чьей кассы выданы деньги. Для «одна точка, один кассир» возврат почти всегда в ту же смену; при возврате в другой смене сверка займётся не той кассой. Решение: добавить `Refund.shift_id` (текущая открытая смена на момент возврата) и считать `expected_cash` по нему.
  - COGS-снимок заказа (`order.cost_tiyn = Σ round(unit_cost)·qty`) и сумма `cost_tiyn` складских движений (`round(avg·qty_total)` по каждому) могут расходиться на единицы тиын из-за раздельного округления — выбрать один источник истины при сверке себестоимости.
- **Из финального кросс-каттинг ревью ветки этапа 2 (перед merge):**
  - **Исправлено немедленно:** `expected_cash_tiyn` вычитал все возвраты независимо от способа исходной оплаты — возврат Kaspi/карты давал фантомный излишек наличности при закрытии смены. Починено: возврат учитывается только для заказов, где все оплаты — наличные.
  - **Принятый риск (не блокирует merge):** fail-fast на дефолтном `storage_secret` срабатывает только для `python -m app.main` (единственный задокументированный способ запуска, см. README). Прямой запуск через `uvicorn app.main:create_app --factory` в обход `__main__` дефолтный секрет не поймает. Не чиним сейчас: правильное решение (разделить create_app для тестов и продакшена) непропорционально риску для однопроцессной локальной кассы с одним задокументированным входом.
  - Брутфорс PIN: лимит попыток только на вкладку, без серверного локаута (уже TODO в `app/auth.py`) — закрыть при подключении к реальной кассе или при выходе в сеть за пределами локальной.
  - Гонка на номере заказа (`_next_order_number` = max+1) — при однопроцессном NiceGUI неопасно; учесть при переходе на многоворкерный запуск.
  - UI не выводит то, что уже умеет сервис: частичный возврат по позициям (только «вернуть полностью»), скидка на экране продажи (лимит кассира в сервисе есть, ввода скидки в UI нет). Кандидаты на отдельные задачи следующего этапа UI, если понадобятся раньше отчётов.
  - `create_product`/продажа не проверяют `Category.is_active` — товар в скрытой категории всё ещё продаётся.
- **Из ревью UI-фазы (этап 2):**
  - Развёртывание: `STORAGE_SECRET` обязателен в `.env` — при дефолте cookie сессии с `role=admin` подделывается, серверный гвард обесценивается (реальный запуск теперь падает fail-fast). Отразить в README (задача 16).
  - Rate-limit пин-кода — только UX-барьер на вкладку, без серверной блокировки/задержки; усилить, если терминал станет доступен из сети.
  - Гвард `require_user`/`require_admin` покрыт только ручной проверкой (нужен контекст NiceGUI storage) — держать в уме при будущих изменениях гварда.
- **Согласованность типов/сигнатур:** деньги везде `*_tiyn: int`; `CartLine`/`PaymentInput`/`SaleLineInput` — единые dataclass'ы из `pricing`/`sales_service`; `apply_move(..., commit=False)` из этапа 1 используется без изменений; `current_open_shift`, `create_sale`, `refund_sale`, `open_shift`, `close_shift`, `expected_cash_tiyn`, `authenticate`, `groups_for_product` — имена стабильны между задачами и тестами.
