# Кофейня-POS, этап 1 «Фундамент» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Каркас кассовой системы: FastAPI + NiceGUI + aiogram в одном процессе, модели БД, авторизация по Telegram + пин-коду, справочники (категории, товары, модификаторы, ингредиенты, тех-карты) со средневзвешенной себестоимостью и админ-интерфейсом.

**Architecture:** Один Python-процесс: FastAPI (ядро), NiceGUI смонтирован на него (весь UI), aiogram-бот стартует фоновой задачей (polling). SQLAlchemy 2.0, локально SQLite. Деньги — целые тиыны; количества ингредиентов — целые базовые единицы (г/мл/шт).

**Tech Stack:** Python 3.12, FastAPI, NiceGUI, aiogram 3.x, SQLAlchemy 2.x, pydantic-settings, pytest, httpx.

**Спецификация:** `docs/superpowers/specs/2026-07-19-coffee-pos-telegram-design.md`

**Этапы после этого плана (отдельные планы):** 2 — продажи/оплата/смены; 3 — склад-операции/уведомления/дашборд; 4 — отчёты/экспорт/бэкапы; 5 — Kaspi API/печать.

---

## Структура файлов

```
app/
  __init__.py
  config.py            # настройки из .env (pydantic-settings)
  db.py                # engine, session_factory, Base, init_db
  auth.py              # проверка Telegram initData, пин-коды
  models/
    __init__.py        # реэкспорт всех моделей
    users.py           # User
    catalog.py         # Category, Product, ModifierGroup, Modifier, ModifierItem, ProductModifierGroup
    inventory.py       # Ingredient, RecipeItem, StockMove
  services/
    __init__.py
    catalog_service.py # CRUD меню
    inventory_service.py # остатки, движения, приход со средневзв. себестоимостью
  ui/
    __init__.py        # регистрация всех страниц NiceGUI
    admin_menu.py      # страницы: категории и товары
    admin_stock.py     # страницы: ингредиенты и тех-карты
  bot/
    __init__.py        # создание бота, /start с кнопкой Mini App
  main.py              # сборка приложения, запуск
tests/
  conftest.py          # фикстура сессии БД (SQLite in-memory)
  test_models.py
  test_catalog_service.py
  test_inventory_service.py
  test_auth.py
  test_app.py
seed.py                # стартовые данные (пример меню кофейни)
requirements.txt
.env.example
.gitignore
README.md
```

---

### Task 1: Каркас проекта и тестовая инфраструктура

**Files:**
- Create: `requirements.txt`, `.gitignore`, `.env.example`, `app/__init__.py`, `tests/test_smoke.py`

- [ ] **Step 1: Создать requirements.txt**

```
fastapi
uvicorn[standard]
nicegui
aiogram
sqlalchemy>=2.0
pydantic-settings
httpx
pytest
```

- [ ] **Step 2: Создать .gitignore**

```
.venv/
__pycache__/
*.pyc
*.db
.env
.nicegui/
```

- [ ] **Step 3: Создать .env.example**

```
BOT_TOKEN=1234567890:PUT-REAL-TOKEN-HERE
DATABASE_URL=sqlite:///pos.db
PUBLIC_URL=https://example.trycloudflare.com
```

- [ ] **Step 4: Создать окружение и поставить зависимости**

Run (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
Expected: установка без ошибок.

- [ ] **Step 5: Пустой пакет и смоук-тест**

`app/__init__.py` — пустой файл.

`tests/test_smoke.py`:
```python
def test_smoke():
    import app  # noqa: F401
    assert True
```

- [ ] **Step 6: Запустить тест**

Run: `.venv\Scripts\python -m pytest -q`
Expected: `1 passed`

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .gitignore .env.example app tests
git commit -m "chore: project scaffold with test infra"
```

---

### Task 2: Настройки и ядро БД

**Files:**
- Create: `app/config.py`, `app/db.py`
- Test: `tests/conftest.py`, `tests/test_db.py`

- [ ] **Step 1: Написать падающий тест**

`tests/conftest.py`:
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")  # in-memory
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
```

`tests/test_db.py`:
```python
from app.config import Settings
from app.db import Base


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None, BOT_TOKEN="x")
    assert s.database_url == "sqlite:///pos.db"


def test_base_exists(session):
    assert Base.metadata is not None
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_db.py -q`
Expected: FAIL — `ModuleNotFoundError: app.config`

- [ ] **Step 3: Реализация**

`app/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = ""
    database_url: str = "sqlite:///pos.db"
    public_url: str = "http://localhost:8080"


settings = Settings()
```

`app/db.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    import app.models  # noqa: F401  (регистрирует таблицы)

    Base.metadata.create_all(engine)
```

Создать пустой `app/models/__init__.py` (наполнится в задачах 3-5).

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/db.py app/models/__init__.py tests/conftest.py tests/test_db.py
git commit -m "feat: settings and database core"
```

---

### Task 3: Модель пользователей

**Files:**
- Create: `app/models/users.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Падающий тест**

`tests/test_models.py`:
```python
from app.models import User


def test_user_roundtrip(session):
    u = User(telegram_id=111, name="Айгерим", role="cashier")
    session.add(u)
    session.commit()
    got = session.query(User).filter_by(telegram_id=111).one()
    assert got.role == "cashier"
    assert got.is_active is True
    assert got.discount_limit_percent == 10
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'User'`

- [ ] **Step 3: Реализация**

`app/models/users.py`:
```python
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    role: Mapped[str]  # "cashier" | "admin"
    pin_hash: Mapped[str | None] = mapped_column(default=None)
    discount_limit_percent: Mapped[int] = mapped_column(default=10)
    is_active: Mapped[bool] = mapped_column(default=True)
```

`app/models/__init__.py`:
```python
from app.models.users import User

__all__ = ["User"]
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/models tests/test_models.py
git commit -m "feat: user model with roles and discount limit"
```

---

### Task 4: Модели каталога (категории, товары, модификаторы)

**Files:**
- Create: `app/models/catalog.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Падающий тест (добавить в tests/test_models.py)**

```python
from app.models import (
    Category,
    Modifier,
    ModifierGroup,
    Product,
    ProductModifierGroup,
)


def test_product_with_modifiers(session):
    cat = Category(name="Кофе", sort_order=1)
    session.add(cat)
    session.flush()

    latte = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(latte)
    session.flush()

    sizes = ModifierGroup(name="Объём", is_required=True)
    session.add(sizes)
    session.flush()
    session.add_all([
        Modifier(group_id=sizes.id, name="M", price_delta_tiyn=0),
        Modifier(group_id=sizes.id, name="L", price_delta_tiyn=20000),
        ProductModifierGroup(product_id=latte.id, group_id=sizes.id),
    ])
    session.commit()

    groups = (
        session.query(ModifierGroup)
        .join(ProductModifierGroup, ProductModifierGroup.group_id == ModifierGroup.id)
        .filter(ProductModifierGroup.product_id == latte.id)
        .all()
    )
    assert [g.name for g in groups] == ["Объём"]
    mods = session.query(Modifier).filter_by(group_id=sizes.id).all()
    assert {m.name for m in mods} == {"M", "L"}
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/models/catalog.py`:
```python
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    kind: Mapped[str]  # "prepared" (по тех-карте) | "retail" (штучный)
    price_tiyn: Mapped[int]
    # для retail-товара — складская позиция, которая списывается поштучно
    ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredients.id"), default=None)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class ModifierGroup(Base):
    __tablename__ = "modifier_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    is_required: Mapped[bool] = mapped_column(default=False)


class Modifier(Base):
    __tablename__ = "modifiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id"))
    name: Mapped[str]
    price_delta_tiyn: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class ModifierItem(Base):
    """Списание ингредиентов, которое добавляет модификатор (сироп +30 мл и т.п.)."""

    __tablename__ = "modifier_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    modifier_id: Mapped[int] = mapped_column(ForeignKey("modifiers.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    qty: Mapped[int]  # в базовых единицах ингредиента (г/мл/шт)


class ProductModifierGroup(Base):
    __tablename__ = "product_modifier_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id"))
```

`app/models/__init__.py`:
```python
from app.models.catalog import (
    Category,
    Modifier,
    ModifierGroup,
    ModifierItem,
    Product,
    ProductModifierGroup,
)
from app.models.users import User

__all__ = [
    "Category",
    "Modifier",
    "ModifierGroup",
    "ModifierItem",
    "Product",
    "ProductModifierGroup",
    "User",
]
```

Примечание: таблица `ingredients` появится в задаче 5; SQLAlchemy разрешит ForeignKey по имени таблицы при создании метаданных, поэтому тесты задачи 4 должны запускаться после добавления модели `Ingredient` **или** тест из Step 1 не должен трогать `ingredient_id`/`ModifierItem` (он и не трогает). Если `create_all` ругнётся на отсутствующую таблицу — выполнить задачи 4 и 5 подряд и запустить тесты после задачи 5.

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (либо перейти к задаче 5 и убедиться там, см. примечание)

- [ ] **Step 5: Commit**

```bash
git add app/models tests/test_models.py
git commit -m "feat: catalog models (categories, products, modifiers)"
```

---

### Task 5: Модели склада (ингредиенты, тех-карты, движения)

**Files:**
- Create: `app/models/inventory.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Падающий тест (добавить в tests/test_models.py)**

```python
from app.models import Ingredient, RecipeItem, StockMove


def test_recipe_and_stock(session):
    milk = Ingredient(name="Молоко", unit="мл", low_stock_threshold=2000)
    coffee = Ingredient(name="Кофе зерно", unit="г", low_stock_threshold=500)
    session.add_all([milk, coffee])
    session.flush()

    cat = Category(name="Кофе2")
    session.add(cat)
    session.flush()
    latte = Product(name="Латте2", category_id=cat.id, kind="prepared", price_tiyn=150000)
    session.add(latte)
    session.flush()

    session.add_all([
        RecipeItem(product_id=latte.id, ingredient_id=coffee.id, qty=18),
        RecipeItem(product_id=latte.id, ingredient_id=milk.id, qty=200),
        StockMove(ingredient_id=milk.id, qty_delta=10000, kind="purchase"),
    ])
    session.commit()

    items = session.query(RecipeItem).filter_by(product_id=latte.id).all()
    assert {(i.ingredient_id, i.qty) for i in items} == {(coffee.id, 18), (milk.id, 200)}
    assert milk.stock_qty == 0  # кэш остатка меняет только сервис (задача 7)
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/models/inventory.py`:
```python
from datetime import datetime, timezone

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Ingredient(Base):
    """Складская позиция: ингредиент (г/мл) или штучный товар (шт)."""

    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    unit: Mapped[str]  # "г" | "мл" | "шт"
    stock_qty: Mapped[int] = mapped_column(default=0)  # кэш остатка в базовых единицах
    avg_cost_tiyn: Mapped[float] = mapped_column(default=0.0)  # тиын за базовую единицу
    low_stock_threshold: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class RecipeItem(Base):
    """Строка тех-карты: сколько ингредиента уходит на 1 порцию товара."""

    __tablename__ = "recipe_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    qty: Mapped[int]  # базовые единицы ингредиента


class StockMove(Base):
    """Журнал движений склада. Остаток = сумма qty_delta (кэшируется в Ingredient)."""

    __tablename__ = "stock_moves"

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    qty_delta: Mapped[int]  # + приход, − списание
    kind: Mapped[str]  # "purchase" | "sale" | "refund" | "adjustment"
    ref_type: Mapped[str | None] = mapped_column(default=None)  # напр. "order"
    ref_id: Mapped[int | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

`app/models/__init__.py` — добавить импорты:
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
from app.models.users import User

__all__ = [
    "Category",
    "Ingredient",
    "Modifier",
    "ModifierGroup",
    "ModifierItem",
    "Product",
    "ProductModifierGroup",
    "RecipeItem",
    "StockMove",
    "User",
]
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (включая задачу 4)

- [ ] **Step 5: Commit**

```bash
git add app/models tests/test_models.py
git commit -m "feat: inventory models (ingredients, recipes, stock moves)"
```

---

### Task 6: Сервис каталога

**Files:**
- Create: `app/services/__init__.py` (пустой), `app/services/catalog_service.py`
- Test: `tests/test_catalog_service.py`

- [ ] **Step 1: Падающий тест**

`tests/test_catalog_service.py`:
```python
import pytest

from app.models import Category, Product
from app.services import catalog_service as cs


def test_create_and_list_menu(session):
    cat = cs.create_category(session, "Чай")
    p = cs.create_product(session, name="Пуэр", category_id=cat.id, kind="prepared", price_tiyn=120000)
    menu = cs.list_menu(session)
    assert menu == [(cat, [p])]


def test_update_price(session):
    cat = cs.create_category(session, "Снеки")
    p = cs.create_product(session, name="Круассан", category_id=cat.id, kind="retail", price_tiyn=90000)
    cs.update_product(session, p.id, price_tiyn=95000)
    assert session.get(Product, p.id).price_tiyn == 95000


def test_retail_requires_positive_price(session):
    cat = cs.create_category(session, "Банки")
    with pytest.raises(ValueError):
        cs.create_product(session, name="Кола", category_id=cat.id, kind="retail", price_tiyn=0)


def test_deactivate_hides_from_menu(session):
    cat = cs.create_category(session, "Кофе")
    p = cs.create_product(session, name="Раф", category_id=cat.id, kind="prepared", price_tiyn=160000)
    cs.update_product(session, p.id, is_active=False)
    assert cs.list_menu(session) == [(cat, [])]
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_catalog_service.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/services/catalog_service.py`:
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Product


def create_category(session: Session, name: str, sort_order: int = 0) -> Category:
    cat = Category(name=name, sort_order=sort_order)
    session.add(cat)
    session.commit()
    return cat


def create_product(
    session: Session,
    *,
    name: str,
    category_id: int,
    kind: str,
    price_tiyn: int,
    ingredient_id: int | None = None,
    sort_order: int = 0,
) -> Product:
    if kind not in ("prepared", "retail"):
        raise ValueError(f"Неизвестный тип товара: {kind}")
    if price_tiyn <= 0:
        raise ValueError("Цена должна быть больше нуля")
    p = Product(
        name=name,
        category_id=category_id,
        kind=kind,
        price_tiyn=price_tiyn,
        ingredient_id=ingredient_id,
        sort_order=sort_order,
    )
    session.add(p)
    session.commit()
    return p


def update_product(session: Session, product_id: int, **fields) -> Product:
    p = session.get(Product, product_id)
    if p is None:
        raise ValueError(f"Товар {product_id} не найден")
    if "price_tiyn" in fields and fields["price_tiyn"] <= 0:
        raise ValueError("Цена должна быть больше нуля")
    for k, v in fields.items():
        if not hasattr(p, k):
            raise ValueError(f"Нет поля {k}")
        setattr(p, k, v)
    session.commit()
    return p


def list_menu(session: Session) -> list[tuple[Category, list[Product]]]:
    """Активные категории с активными товарами, в порядке sort_order."""
    cats = session.scalars(
        select(Category).where(Category.is_active).order_by(Category.sort_order, Category.name)
    ).all()
    result = []
    for cat in cats:
        prods = session.scalars(
            select(Product)
            .where(Product.category_id == cat.id, Product.is_active)
            .order_by(Product.sort_order, Product.name)
        ).all()
        result.append((cat, list(prods)))
    return result
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services tests/test_catalog_service.py
git commit -m "feat: catalog service (menu CRUD)"
```

---

### Task 7: Сервис склада — движения и средневзвешенная себестоимость

**Files:**
- Create: `app/services/inventory_service.py`
- Test: `tests/test_inventory_service.py`

- [ ] **Step 1: Падающий тест**

`tests/test_inventory_service.py`:
```python
import pytest

from app.models import Ingredient, StockMove
from app.services import inventory_service as inv


def _milk(session):
    m = Ingredient(name="Молоко", unit="мл", low_stock_threshold=2000)
    session.add(m)
    session.commit()
    return m


def test_purchase_increases_stock_and_sets_cost(session):
    milk = _milk(session)
    # 10 л молока за 5000 тг = 10000 мл за 500000 тиын → 50 тиын/мл
    inv.receive_purchase(session, milk.id, qty=10000, total_cost_tiyn=500000)
    assert milk.stock_qty == 10000
    assert milk.avg_cost_tiyn == pytest.approx(50.0)


def test_weighted_average_cost(session):
    milk = _milk(session)
    inv.receive_purchase(session, milk.id, qty=10000, total_cost_tiyn=500000)  # 50/мл
    inv.receive_purchase(session, milk.id, qty=10000, total_cost_tiyn=700000)  # 70/мл
    assert milk.stock_qty == 20000
    assert milk.avg_cost_tiyn == pytest.approx(60.0)


def test_apply_move_writes_journal_and_cache(session):
    milk = _milk(session)
    inv.receive_purchase(session, milk.id, qty=10000, total_cost_tiyn=500000)
    inv.apply_move(session, milk.id, qty_delta=-200, kind="sale", ref_type="order", ref_id=1)
    assert milk.stock_qty == 9800
    moves = session.query(StockMove).filter_by(ingredient_id=milk.id).all()
    assert [m.kind for m in moves] == ["purchase", "sale"]


def test_purchase_rejects_bad_input(session):
    milk = _milk(session)
    with pytest.raises(ValueError):
        inv.receive_purchase(session, milk.id, qty=0, total_cost_tiyn=100)
    with pytest.raises(ValueError):
        inv.receive_purchase(session, milk.id, qty=100, total_cost_tiyn=-1)
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_inventory_service.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/services/inventory_service.py`:
```python
from sqlalchemy.orm import Session

from app.models import Ingredient, StockMove


def apply_move(
    session: Session,
    ingredient_id: int,
    *,
    qty_delta: int,
    kind: str,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
    commit: bool = True,
) -> StockMove:
    """Единственная точка изменения остатка: журнал + кэш в одной транзакции."""
    ing = session.get(Ingredient, ingredient_id)
    if ing is None:
        raise ValueError(f"Позиция склада {ingredient_id} не найдена")
    move = StockMove(
        ingredient_id=ingredient_id,
        qty_delta=qty_delta,
        kind=kind,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )
    ing.stock_qty += qty_delta
    session.add(move)
    if commit:
        session.commit()
    return move


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
        note=f"total_cost_tiyn={total_cost_tiyn}",
        commit=False,
    )
    session.commit()
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/inventory_service.py tests/test_inventory_service.py
git commit -m "feat: inventory service with weighted-average cost"
```

---

### Task 8: Авторизация — Telegram initData и пин-код

**Files:**
- Create: `app/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Падающий тест**

`tests/test_auth.py`:
```python
import hashlib
import hmac
from urllib.parse import urlencode

from app.auth import hash_pin, validate_init_data, verify_pin

TOKEN = "1234567890:TEST-TOKEN"


def _make_init_data(params: dict, token: str) -> str:
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": h})


def test_valid_init_data_accepted():
    init = _make_init_data({"auth_date": "1752900000", "user": '{"id":111}'}, TOKEN)
    data = validate_init_data(init, TOKEN)
    assert data is not None
    assert data["auth_date"] == "1752900000"


def test_tampered_init_data_rejected():
    init = _make_init_data({"auth_date": "1752900000", "user": '{"id":111}'}, TOKEN)
    tampered = init.replace("111", "222")
    assert validate_init_data(tampered, TOKEN) is None


def test_wrong_token_rejected():
    init = _make_init_data({"auth_date": "1752900000"}, TOKEN)
    assert validate_init_data(init, "другой:токен") is None


def test_pin_hash_roundtrip():
    h = hash_pin("4821")
    assert verify_pin("4821", h)
    assert not verify_pin("0000", h)
    assert h != "4821"
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_auth.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/auth.py`:
```python
import hashlib
import hmac
import os
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Проверка подписи Telegram Mini App initData. None — подпись неверна."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None
    return pairs


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    return salt.hex() + ":" + digest.hex()


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 100_000)
    return hmac.compare_digest(digest.hex(), digest_hex)
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_auth.py
git commit -m "feat: telegram initData validation and pin hashing"
```

---

### Task 9: Сборка приложения — FastAPI + NiceGUI

**Files:**
- Create: `app/main.py`, `app/ui/__init__.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: Падающий тест**

`tests/test_app.py`:
```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_health():
    app = create_app(start_bot=False)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Убедиться, что падает**

Run: `.venv\Scripts\python -m pytest tests/test_app.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Реализация**

`app/ui/__init__.py`:
```python
def register_pages() -> None:
    """Импортирует модули страниц NiceGUI (каждый регистрирует свои @ui.page)."""
    from app.ui import admin_menu, admin_stock  # noqa: F401
```

Пока страницы не созданы (задачи 11-12) — создать заглушки-файлы `app/ui/admin_menu.py` и `app/ui/admin_stock.py` с одной строкой `# страницы добавит задача 11/12`, чтобы импорт работал.

`app/main.py`:
```python
import asyncio

from fastapi import FastAPI
from nicegui import ui

from app.config import settings
from app.db import init_db


def create_app(start_bot: bool = True) -> FastAPI:
    app = FastAPI(title="Coffee POS")
    init_db()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    if start_bot and settings.bot_token:
        @app.on_event("startup")
        async def _start_bot():
            from app.bot import run_bot

            asyncio.create_task(run_bot())

    from app.ui import register_pages

    register_pages()
    ui.run_with(app, storage_secret="coffee-pos-local", title="Касса")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080)
```

Для теста нужен модуль бота хотя бы пустой: создать `app/bot/__init__.py`:
```python
async def run_bot() -> None:  # реализация в задаче 10
    pass
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Ручная проверка запуска**

Run: `.venv\Scripts\python -m app.main`
Expected: uvicorn слушает :8080, `http://localhost:8080/health` отвечает `{"status":"ok"}`. Остановить Ctrl+C.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/ui app/bot tests/test_app.py
git commit -m "feat: app assembly (fastapi + nicegui mount, health)"
```

---

### Task 10: Бот — /start с кнопкой открытия кассы

**Files:**
- Modify: `app/bot/__init__.py`

Логика бота почти без ветвлений — проверяется вручную; юнит-тесты бота появятся на этапе уведомлений (план 3).

- [ ] **Step 1: Реализация**

`app/bot/__init__.py`:
```python
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.config import settings
from app.db import SessionLocal
from app.models import User

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    with SessionLocal() as session:
        user = (
            session.query(User)
            .filter_by(telegram_id=message.from_user.id, is_active=True)
            .one_or_none()
        )
    if user is None:
        await message.answer(
            "Доступ не настроен. Попросите администратора добавить ваш Telegram ID: "
            f"{message.from_user.id}"
        )
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Открыть кассу",
                web_app=WebAppInfo(url=settings.public_url),
            )
        ]]
    )
    await message.answer(f"Здравствуйте, {user.name}! Роль: {user.role}.", reply_markup=kb)


async def run_bot() -> None:
    if not settings.bot_token:
        return
    bot = Bot(settings.bot_token)
    await dp.start_polling(bot, handle_signals=False)
```

- [ ] **Step 2: Запустить все тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 3: Ручная проверка**

1. Создать бота у @BotFather, получить токен, записать в `.env` (`BOT_TOKEN=...`).
2. Run: `.venv\Scripts\python -m app.main`
3. В Telegram отправить боту `/start` — должен ответить «Доступ не настроен…» с вашим ID (пользователей в БД ещё нет — это правильное поведение).

- [ ] **Step 4: Commit**

```bash
git add app/bot/__init__.py
git commit -m "feat: bot /start with mini-app button and whitelist check"
```

---

### Task 11: Админ-UI — категории и товары

**Files:**
- Modify: `app/ui/admin_menu.py`

Логика уже покрыта тестами сервиса (задача 6); здесь — только связка UI → сервис и ручная проверка.

- [ ] **Step 1: Реализация**

`app/ui/admin_menu.py`:
```python
from nicegui import ui

from app.db import SessionLocal
from app.services import catalog_service as cs

KIND_LABELS = {"prepared": "Приготовленный", "retail": "Штучный"}


@ui.page("/admin/menu")
def admin_menu_page() -> None:
    ui.label("Меню и цены").classes("text-2xl font-bold")

    container = ui.column().classes("w-full max-w-3xl gap-2")

    def refresh() -> None:
        container.clear()
        with container, SessionLocal() as session:
            for cat, products in cs.list_menu(session):
                ui.label(cat.name).classes("text-xl mt-4")
                for p in products:
                    with ui.row().classes("items-center gap-4"):
                        ui.label(p.name).classes("w-48")
                        ui.label(KIND_LABELS[p.kind]).classes("text-gray-500 w-36")
                        price = ui.number(
                            label="Цена, тг", value=p.price_tiyn / 100, min=1, format="%.0f"
                        )

                        def save(pid=p.id, field=price) -> None:
                            with SessionLocal() as s:
                                cs.update_product(s, pid, price_tiyn=int(field.value * 100))
                            ui.notify("Цена сохранена")

                        ui.button("Сохранить", on_click=save)

                        def deactivate(pid=p.id) -> None:
                            with SessionLocal() as s:
                                cs.update_product(s, pid, is_active=False)
                            refresh()

                        ui.button("Убрать", on_click=deactivate, color="red")

    with ui.expansion("Добавить категорию").classes("w-full max-w-3xl"):
        cat_name = ui.input("Название категории")

        def add_category() -> None:
            if not cat_name.value:
                return
            with SessionLocal() as s:
                cs.create_category(s, cat_name.value)
            cat_name.value = ""
            refresh()

        ui.button("Добавить", on_click=add_category)

    with ui.expansion("Добавить товар").classes("w-full max-w-3xl"):
        with SessionLocal() as session:
            cat_options = {c.id: c.name for c, _ in cs.list_menu(session)}
        p_name = ui.input("Название")
        p_cat = ui.select(cat_options, label="Категория")
        p_kind = ui.select(KIND_LABELS, label="Тип", value="prepared")
        p_price = ui.number(label="Цена, тг", value=0, min=1, format="%.0f")

        def add_product() -> None:
            if not (p_name.value and p_cat.value and p_price.value):
                ui.notify("Заполните все поля", color="red")
                return
            with SessionLocal() as s:
                cs.create_product(
                    s,
                    name=p_name.value,
                    category_id=p_cat.value,
                    kind=p_kind.value,
                    price_tiyn=int(p_price.value * 100),
                )
            p_name.value = ""
            refresh()

        ui.button("Добавить товар", on_click=add_product)

    refresh()
```

- [ ] **Step 2: Запустить тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 3: Ручная проверка**

Run: `.venv\Scripts\python -m app.main`, открыть `http://localhost:8080/admin/menu`:
добавить категорию «Кофе», товар «Латте» 1500 тг, изменить цену, убрать товар. Всё должно отражаться сразу.

- [ ] **Step 4: Commit**

```bash
git add app/ui/admin_menu.py
git commit -m "feat: admin ui for categories and products"
```

---

### Task 12: Админ-UI — ингредиенты и тех-карты

**Files:**
- Modify: `app/ui/admin_stock.py`

- [ ] **Step 1: Реализация**

`app/ui/admin_stock.py`:
```python
from nicegui import ui
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Ingredient, Product, RecipeItem


@ui.page("/admin/stock")
def admin_stock_page() -> None:
    ui.label("Склад: позиции и тех-карты").classes("text-2xl font-bold")

    ing_container = ui.column().classes("w-full max-w-3xl gap-1")

    def refresh_ingredients() -> None:
        ing_container.clear()
        with ing_container, SessionLocal() as session:
            rows = session.scalars(
                select(Ingredient).where(Ingredient.is_active).order_by(Ingredient.name)
            ).all()
            columns = [
                {"name": "name", "label": "Название", "field": "name"},
                {"name": "stock", "label": "Остаток", "field": "stock"},
                {"name": "threshold", "label": "Порог", "field": "threshold"},
            ]
            data = [
                {
                    "name": f"{i.name} ({i.unit})",
                    "stock": i.stock_qty,
                    "threshold": i.low_stock_threshold,
                }
                for i in rows
            ]
            ui.table(columns=columns, rows=data).classes("w-full")

    with ui.expansion("Добавить позицию склада").classes("w-full max-w-3xl"):
        n = ui.input("Название (напр. Молоко)")
        u = ui.select({"г": "граммы", "мл": "миллилитры", "шт": "штуки"}, label="Единица", value="мл")
        t = ui.number(label="Порог низкого остатка", value=0, min=0, format="%.0f")

        def add_ing() -> None:
            if not n.value:
                return
            with SessionLocal() as s:
                s.add(Ingredient(name=n.value, unit=u.value, low_stock_threshold=int(t.value or 0)))
                s.commit()
            n.value = ""
            refresh_ingredients()

        ui.button("Добавить", on_click=add_ing)

    ui.separator()
    ui.label("Тех-карта товара").classes("text-xl")
    recipe_container = ui.column().classes("w-full max-w-3xl gap-1")

    with SessionLocal() as session:
        prod_options = {
            p.id: p.name
            for p in session.scalars(select(Product).where(Product.kind == "prepared")).all()
        }
        ing_options = {
            i.id: f"{i.name} ({i.unit})"
            for i in session.scalars(select(Ingredient).where(Ingredient.is_active)).all()
        }

    sel_product = ui.select(prod_options, label="Товар", on_change=lambda e: refresh_recipe())

    def refresh_recipe() -> None:
        recipe_container.clear()
        if not sel_product.value:
            return
        with recipe_container, SessionLocal() as session:
            items = session.scalars(
                select(RecipeItem).where(RecipeItem.product_id == sel_product.value)
            ).all()
            for it in items:
                ing = session.get(Ingredient, it.ingredient_id)
                with ui.row().classes("items-center gap-4"):
                    ui.label(f"{ing.name}: {it.qty} {ing.unit}")

                    def remove(item_id=it.id) -> None:
                        with SessionLocal() as s:
                            obj = s.get(RecipeItem, item_id)
                            if obj:
                                s.delete(obj)
                                s.commit()
                        refresh_recipe()

                    ui.button("Удалить", on_click=remove, color="red")

    with ui.row().classes("items-end gap-4"):
        sel_ing = ui.select(ing_options, label="Ингредиент")
        qty = ui.number(label="Кол-во на порцию", value=0, min=1, format="%.0f")

        def add_line() -> None:
            if not (sel_product.value and sel_ing.value and qty.value):
                ui.notify("Выберите товар, ингредиент и количество", color="red")
                return
            with SessionLocal() as s:
                s.add(
                    RecipeItem(
                        product_id=sel_product.value,
                        ingredient_id=sel_ing.value,
                        qty=int(qty.value),
                    )
                )
                s.commit()
            refresh_recipe()

        ui.button("Добавить в тех-карту", on_click=add_line)

    refresh_ingredients()
```

- [ ] **Step 2: Запустить тесты (регресс)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 3: Ручная проверка**

Run: `.venv\Scripts\python -m app.main`, открыть `http://localhost:8080/admin/stock`:
добавить «Молоко (мл)» и «Кофе зерно (г)», выбрать товар «Латте», добавить строки тех-карты 200 мл молока и 18 г кофе, удалить и снова добавить строку.

- [ ] **Step 4: Commit**

```bash
git add app/ui/admin_stock.py
git commit -m "feat: admin ui for ingredients and recipes"
```

---

### Task 13: Сид-данные и README

**Files:**
- Create: `seed.py`, `README.md`

- [ ] **Step 1: Написать seed.py**

```python
"""Стартовые данные: админ + пример меню. Запуск: python seed.py <telegram_id_админа>"""
import sys

from app.db import SessionLocal, init_db
from app.models import Category, Ingredient, Product, RecipeItem, User


def seed(admin_telegram_id: int) -> None:
    init_db()
    with SessionLocal() as s:
        if s.query(User).count() > 0:
            print("БД уже содержит данные — сид пропущен")
            return
        s.add(User(telegram_id=admin_telegram_id, name="Владелец", role="admin"))

        coffee = Category(name="Кофе", sort_order=1)
        snacks = Category(name="Снеки", sort_order=2)
        s.add_all([coffee, snacks])
        s.flush()

        milk = Ingredient(name="Молоко", unit="мл", low_stock_threshold=2000)
        beans = Ingredient(name="Кофе зерно", unit="г", low_stock_threshold=500)
        croissant = Ingredient(name="Круассан", unit="шт", low_stock_threshold=5)
        s.add_all([milk, beans, croissant])
        s.flush()

        latte = Product(name="Латте", category_id=coffee.id, kind="prepared", price_tiyn=150000)
        s.add(latte)
        s.flush()
        s.add_all([
            RecipeItem(product_id=latte.id, ingredient_id=beans.id, qty=18),
            RecipeItem(product_id=latte.id, ingredient_id=milk.id, qty=200),
            Product(
                name="Круассан",
                category_id=snacks.id,
                kind="retail",
                price_tiyn=90000,
                ingredient_id=croissant.id,
            ),
        ])
        s.commit()
        print("Готово: админ и пример меню созданы")


if __name__ == "__main__":
    seed(int(sys.argv[1]))
```

- [ ] **Step 2: Проверить сид**

Run:
```powershell
Remove-Item pos.db -ErrorAction SilentlyContinue
.venv\Scripts\python seed.py 123456789
```
Expected: `Готово: админ и пример меню созданы`; повторный запуск печатает «сид пропущен».

- [ ] **Step 3: Написать README.md**

````markdown
# Coffee POS — касса кофейни в Telegram

Один Python-процесс: FastAPI + NiceGUI (интерфейс) + aiogram (бот). БД — SQLite.

## Первый запуск

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env   # вписать BOT_TOKEN от @BotFather
.venv\Scripts\python seed.py <ваш_telegram_id>   # id узнать: отправить /start боту
.venv\Scripts\python -m app.main
```

- Касса/админка: http://localhost:8080 (разделы /admin/menu, /admin/stock)
- Проверка: http://localhost:8080/health

## Доступ из Telegram (Mini App)

Telegram открывает Mini App только по публичному HTTPS. Локально — туннель:

```powershell
winget install Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8080
```

Выданный адрес `https://...trycloudflare.com` вписать в `.env` → `PUBLIC_URL`
и перезапустить приложение. Кнопка «Открыть кассу» в боте начнёт работать.

## Тесты

```powershell
.venv\Scripts\python -m pytest -q
```
````

- [ ] **Step 4: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add seed.py README.md
git commit -m "feat: seed data and README"
```

---

## Бэклог для плана этапа 2 (из ревью этапа 1)

Этап 1 выполнен и слит в master (43e3e7c). Финальное ревью — «готово к merge»; следующие
непроблокирующие замечания обязан учесть план этапа 2:

1. Изоляция тестов приложения от боевой БД: `create_app`/тесты не должны трогать `pos.db`
   (переопределяемый `database_url` или передача engine в фабрику).
2. Auth-guard на все страницы: вход по Telegram initData (+ проверка свежести `auth_date`,
   1-2 часа) и пин-код с rate-limit/lockout — TODO уже стоит в `app/auth.py`.
3. `create_product`: для `kind="retail"` требовать `ingredient_id` (иначе продажа штучного
   товара не сможет списать остаток); в UI добавления товара — выбор складской позиции.
4. UI: человекочитаемые сообщения вместо сырого `str(IntegrityError)`; реактивация скрытых
   товаров; общий layout/навигация между страницами.
5. Бот: закрывать aiohttp-сессию `Bot` при остановке; выносить запросы к БД из async-хендлеров
   (`asyncio.to_thread`) по мере роста числа хендлеров.
6. Предупреждение в лог при дефолтном `storage_secret="change-me-in-env"`.
7. Помнить контракт: `apply_move(commit=False)` по умолчанию — транзакцией продажи владеет
   вызывающий (`sales_service`), интеграционный тест на атомарность чека обязателен.

## Самопроверка плана

- **Покрытие этапа 1 по спецификации:** каркас (разд. 3 спеки) — задачи 1, 2, 9; авторизация (разд. 3) — задача 8 (интеграция в UI-вход — этап 2, вместе с пин-экраном смены); справочники и тех-карты (разд. 4, 5) — задачи 3-7, 11, 12; бот и Mini App-кнопка — задача 10; себестоимость средневзвешенная (разд. 5) — задача 7.
- **Сознательно отложено на следующие планы:** смены/продажи/оплаты (план 2), приход через UI, пороги-уведомления, дашборд (план 3), отчёты (план 4), Kaspi/печать (план 5). Модели заложены так, чтобы эти планы их не переделывали.
- **Типы согласованы:** деньги везде `*_tiyn: int`; количества ингредиентов `qty: int` в базовых единицах; `kind` товара — `"prepared" | "retail"`; сервисные функции, используемые в UI (`list_menu`, `create_product`, `update_product`, `create_category`), определены в задаче 6.
