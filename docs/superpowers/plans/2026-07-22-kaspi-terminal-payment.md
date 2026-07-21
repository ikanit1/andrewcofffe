# Kaspi Smart POS — реальная оплата через терминал — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить ручную отметку «оплачено Kaspi QR» на реальное подтверждение оплаты через терминал Kaspi Smart POS, плюс экран настройки и проверки связи.

**Architecture:** Тонкий async HTTP-клиент терминала (`app/kaspi/client.py`) + сервис-оркестратор с опросом статуса (`app/kaspi/service.py`) + репозиторий настроек (`app/kaspi/settings.py`, модель `KaspiSettings`). Поток продажи: чек проводится только ПОСЛЕ подтверждения оплаты терминалом. Тесты — через `httpx.MockTransport` и `asyncio.run`, без реального терминала и без новых зависимостей.

**Tech Stack:** Python 3.13, httpx (async), NiceGUI, SQLAlchemy 2.x, pytest.

**Спецификация:** `docs/superpowers/specs/2026-07-22-kaspi-terminal-payment-design.md`
**API-справка:** память проекта `kaspi-smart-pos-api` + PDF `Smart+POS...pdf` в корне.

---

## Структура файлов

```
app/
  db.py                          # ИЗМЕНИТЬ: ensure_schema() — миграция колонок для живой pos.db
  models/
    payments.py                  # ИЗМЕНИТЬ: Payment + provider/terminal_method/transaction_id
    kaspi.py                     # НОВЫЙ: KaspiSettings (синглтон-строка)
    __init__.py                  # ИЗМЕНИТЬ: экспорт KaspiSettings
  services/
    pricing.py                   # ИЗМЕНИТЬ: PaymentInput + поля; validate_payments + "kaspi_terminal"
    sales_service.py             # ИЗМЕНИТЬ: create_sale прокидывает новые поля в Payment
  kaspi/
    __init__.py                  # НОВЫЙ: пустой пакет
    settings.py                  # НОВЫЙ: get_settings/save_tokens/save_config
    client.py                    # НОВЫЙ: KaspiClient (async httpx), KaspiError
    service.py                   # НОВЫЙ: amount_to_tenge, PaymentResult, pay, poll, check_connection, register_cashier, ensure_token
  ui/
    kaspi_admin.py               # НОВЫЙ: /admin/kaspi
    __init__.py                  # ИЗМЕНИТЬ: register_pages + kaspi_admin
    admin_stock.py               # ИЗМЕНИТЬ: кнопка «Kaspi терминал»
    cashier.py                   # ИЗМЕНИТЬ: способ «Kaspi (терминал)» + async-оплата
tests/
  test_kaspi_migration.py        # НОВЫЙ
  test_kaspi_settings.py         # НОВЫЙ
  test_kaspi_client.py           # НОВЫЙ
  test_kaspi_service.py          # НОВЫЙ
  test_models_stage2.py          # ИЗМЕНИТЬ: Payment новые поля (или отдельный тест)
  test_sales_service.py          # ИЗМЕНИТЬ: create_sale хранит provider/terminal_method/transaction_id
README.md                        # ИЗМЕНИТЬ: раздел про Kaspi-терминал
seed.py                          # ИЗМЕНИТЬ: создать строку KaspiSettings по умолчанию
```

---

### Task 1: Модели — KaspiSettings и новые поля Payment

**Files:**
- Create: `app/models/kaspi.py`
- Modify: `app/models/payments.py`, `app/models/__init__.py`
- Test: `tests/test_kaspi_settings.py` (модельная часть), `tests/test_models_stage2.py`

- [ ] **Step 1: Падающий тест на новые поля Payment (добавить в tests/test_models_stage2.py)**

Найти существующий тест `test_payment_and_refund` и добавить ПОСЛЕ него:
```python
def test_payment_terminal_fields_default_and_set(session):
    order = _paid_order(session)
    session.add_all([
        Payment(order_id=order.id, method="cash", amount_tiyn=100000),
        Payment(order_id=order.id, method="kaspi_terminal", amount_tiyn=70000,
                provider="terminal", terminal_method="qr", transaction_id="504711333"),
    ])
    session.commit()
    manual = session.query(Payment).filter_by(method="cash").one()
    assert manual.provider == "manual"
    assert manual.terminal_method is None
    assert manual.transaction_id is None
    term = session.query(Payment).filter_by(method="kaspi_terminal").one()
    assert term.provider == "terminal"
    assert term.terminal_method == "qr"
    assert term.transaction_id == "504711333"
```

- [ ] **Step 2: Падающий тест на KaspiSettings**

`tests/test_kaspi_settings.py`:
```python
from datetime import datetime

from app.models import KaspiSettings


def test_kaspi_settings_roundtrip(session):
    s = KaspiSettings(
        terminal_url="http://192.168.0.100:8080",
        cashier_name="Kashier1",
        access_token="a", refresh_token="r",
        token_expires_at=datetime(2026, 7, 23, 12, 0),
        terminal_id="00000000",
    )
    session.add(s)
    session.commit()
    got = session.query(KaspiSettings).one()
    assert got.terminal_url == "http://192.168.0.100:8080"
    assert got.cashier_name == "Kashier1"
    assert got.terminal_id == "00000000"


def test_kaspi_settings_defaults(session):
    s = KaspiSettings()
    session.add(s)
    session.commit()
    got = session.query(KaspiSettings).one()
    assert got.terminal_url == "http://192.168.0.100:8080"
    assert got.cashier_name == "Kashier1"
    assert got.access_token is None
    assert got.terminal_id is None
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `.venv\Scripts\python -m pytest tests/test_kaspi_settings.py tests/test_models_stage2.py -q`
Expected: FAIL — `ImportError: cannot import name 'KaspiSettings'` / у `Payment` нет `provider`.

- [ ] **Step 4: Реализация — новые поля Payment**

В `app/models/payments.py`, класс `Payment`, после строки `created_at: ...` добавить:
```python
    provider: Mapped[str] = mapped_column(default="manual")  # "manual" | "terminal"
    terminal_method: Mapped[str | None] = mapped_column(default=None)  # "qr" | "card" | "alaqan"
    transaction_id: Mapped[str | None] = mapped_column(default=None)  # orderNumber (qr/alaqan) или rrn (card)
```

- [ ] **Step 5: Реализация — модель KaspiSettings**

`app/models/kaspi.py`:
```python
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KaspiSettings(Base):
    """Настройки интеграции с терминалом Kaspi Smart POS. Всегда одна строка (id=1)."""

    __tablename__ = "kaspi_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    terminal_url: Mapped[str] = mapped_column(default="http://192.168.0.100:8080")
    cashier_name: Mapped[str] = mapped_column(default="Kashier1")
    access_token: Mapped[str | None] = mapped_column(default=None)
    refresh_token: Mapped[str | None] = mapped_column(default=None)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    terminal_id: Mapped[str | None] = mapped_column(default=None)
```

- [ ] **Step 6: Экспорт в app/models/__init__.py**

Добавить импорт `from app.models.kaspi import KaspiSettings` и вписать `"KaspiSettings"` в `__all__` (по алфавиту — между `Ingredient` и `Modifier`).

- [ ] **Step 7: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (93 существующих + 3 новых = 96)

- [ ] **Step 8: Commit**

```bash
git add app/models/kaspi.py app/models/payments.py app/models/__init__.py tests/test_kaspi_settings.py tests/test_models_stage2.py
git commit -m "feat: KaspiSettings model and terminal payment fields on Payment"
```

---

### Task 2: PaymentInput + validate_payments + create_sale

**Files:**
- Modify: `app/services/pricing.py`, `app/services/sales_service.py`
- Test: `tests/test_sales_service.py`

- [ ] **Step 1: Падающий тест (добавить в tests/test_sales_service.py)**

```python
def test_create_sale_stores_terminal_payment_fields(session):
    cashier, latte, milk, beans, shift = _setup(session)
    order = sales.create_sale(
        session, cashier_id=cashier.id, lines=[_line(latte.id)],
        payments=[PaymentInput("kaspi_terminal", 150000, None,
                               provider="terminal", terminal_method="qr",
                               transaction_id="504711333")],
    )
    from app.models import Payment
    pay = session.query(Payment).filter_by(order_id=order.id).one()
    assert pay.method == "kaspi_terminal"
    assert pay.provider == "terminal"
    assert pay.terminal_method == "qr"
    assert pay.transaction_id == "504711333"
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_sales_service.py::test_create_sale_stores_terminal_payment_fields -q`
Expected: FAIL — `PaymentInput.__init__() got an unexpected keyword argument 'provider'`

- [ ] **Step 3: Реализация — PaymentInput**

В `app/services/pricing.py` заменить датакласс `PaymentInput`:
```python
@dataclass
class PaymentInput:
    method: str  # "cash" | "card" | "kaspi_qr" | "kaspi_terminal"
    amount_tiyn: int
    tendered_tiyn: int | None = None
    provider: str = "manual"  # "manual" | "terminal"
    terminal_method: str | None = None  # "qr" | "card" | "alaqan"
    transaction_id: str | None = None
```

И в `validate_payments` расширить набор допустимых способов:
```python
        if pay.method not in ("cash", "card", "kaspi_qr", "kaspi_terminal"):
            raise ValueError(f"Неизвестный способ оплаты: {pay.method}")
```

- [ ] **Step 4: Реализация — create_sale прокидывает поля**

В `app/services/sales_service.py`, в цикле `for pay in payments:` заменить создание `Payment` на:
```python
        for pay in payments:
            change = None
            if pay.method == "cash" and pay.tendered_tiyn is not None:
                change = max(pay.tendered_tiyn - pay.amount_tiyn, 0)
            session.add(Payment(
                order_id=order.id, method=pay.method, amount_tiyn=pay.amount_tiyn,
                tendered_tiyn=pay.tendered_tiyn, change_tiyn=change,
                provider=pay.provider, terminal_method=pay.terminal_method,
                transaction_id=pay.transaction_id,
            ))
```

- [ ] **Step 5: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/pricing.py app/services/sales_service.py tests/test_sales_service.py
git commit -m "feat: PaymentInput terminal fields threaded into create_sale"
```

---

### Task 3: Идемпотентная миграция схемы для живой pos.db

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_kaspi_migration.py`

Существующая боевая `pos.db` уже содержит таблицу `payments` БЕЗ новых колонок; `Base.metadata.create_all` их не добавляет. Нужна маленькая идемпотентная миграция (у проекта нет Alembic).

- [ ] **Step 1: Падающий тест**

`tests/test_kaspi_migration.py`:
```python
from sqlalchemy import create_engine, text

from app.db import ensure_schema


def test_ensure_schema_adds_missing_payment_columns():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        # старая схема payments — без новых колонок
        conn.execute(text(
            "CREATE TABLE payments (id INTEGER PRIMARY KEY, method VARCHAR, amount_tiyn INTEGER)"
        ))
        conn.execute(text("INSERT INTO payments (method, amount_tiyn) VALUES ('cash', 100)"))

    ensure_schema(engine)

    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(payments)"))}
        assert {"provider", "terminal_method", "transaction_id"} <= cols
        # существующая строка получила provider='manual'
        val = conn.execute(text("SELECT provider FROM payments WHERE method='cash'")).scalar()
        assert val == "manual"


def test_ensure_schema_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE payments (id INTEGER PRIMARY KEY, method VARCHAR, amount_tiyn INTEGER)"
        ))
    ensure_schema(engine)
    ensure_schema(engine)  # повторный вызов не должен падать
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(payments)"))}
        assert "provider" in cols


def test_ensure_schema_skips_when_no_payments_table():
    engine = create_engine("sqlite://")
    ensure_schema(engine)  # нет таблицы payments — не должно падать
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_kaspi_migration.py -q`
Expected: FAIL — `ImportError: cannot import name 'ensure_schema'`

- [ ] **Step 3: Реализация**

В `app/db.py` добавить функцию (после `enable_sqlite_fk`) и вызвать её из `init_db`:
```python
def ensure_schema(engine: Engine) -> None:
    """Идемпотентно добавляет недостающие колонки в существующие таблицы SQLite.

    У проекта нет Alembic; Base.metadata.create_all создаёт новые таблицы, но не
    изменяет уже существующие. Здесь добавляем колонки, появившиеся после того, как
    боевая pos.db была создана.
    """
    if engine.dialect.name != "sqlite":
        return
    from sqlalchemy import text

    wanted = {
        "payments": {
            "provider": "VARCHAR NOT NULL DEFAULT 'manual'",
            "terminal_method": "VARCHAR",
            "transaction_id": "VARCHAR",
        },
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            present = conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")).fetchone()
            if present is None:
                continue
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col, ddl in columns.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
```

И в `init_db` добавить вызов после `create_all`:
```python
def init_db() -> None:
    import app.models  # noqa: F401  (регистрирует таблицы)

    Base.metadata.create_all(engine)
    ensure_schema(engine)
```

Примечание: `Engine` уже импортирован в `app/db.py` (`from sqlalchemy.engine import Engine`). Если нет — добавить импорт.

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Применить миграцию к реальной pos.db и проверить**

Run:
```powershell
.venv\Scripts\python -c "from app.db import engine, init_db; init_db(); print('schema ensured')"
.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('pos.db'); print([r[1] for r in c.execute('pragma table_info(payments)')]); print('kaspi_settings:', bool(c.execute(\"select name from sqlite_master where name='kaspi_settings'\").fetchall()))"
```
Expected: в списке колонок payments есть `provider`, `terminal_method`, `transaction_id`; `kaspi_settings: True`.

- [ ] **Step 6: Commit**

```bash
git add app/db.py tests/test_kaspi_migration.py
git commit -m "feat: idempotent sqlite schema migration for payment terminal columns"
```

---

### Task 4: Репозиторий настроек Kaspi

**Files:**
- Create: `app/kaspi/__init__.py` (пустой), `app/kaspi/settings.py`
- Test: `tests/test_kaspi_settings.py`

- [ ] **Step 1: Падающий тест (добавить в tests/test_kaspi_settings.py)**

```python
from datetime import datetime, timezone

from app.kaspi import settings as ksettings


def test_get_settings_creates_singleton(session):
    s1 = ksettings.get_settings(session)
    assert s1.id == 1
    assert s1.terminal_url == "http://192.168.0.100:8080"
    s2 = ksettings.get_settings(session)
    assert s2.id == 1  # та же строка, не создаёт вторую
    assert session.query(KaspiSettings).count() == 1


def test_save_config_updates_url_and_name(session):
    ksettings.get_settings(session)
    ksettings.save_config(session, terminal_url="https://10.0.0.5:8080", cashier_name="Bar1")
    s = ksettings.get_settings(session)
    assert s.terminal_url == "https://10.0.0.5:8080"
    assert s.cashier_name == "Bar1"


def test_save_tokens_and_terminal_id(session):
    ksettings.get_settings(session)
    exp = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    ksettings.save_tokens(session, access_token="acc", refresh_token="ref", expires_at=exp)
    ksettings.save_terminal_id(session, terminal_id="00000000")
    s = ksettings.get_settings(session)
    assert s.access_token == "acc"
    assert s.refresh_token == "ref"
    assert s.terminal_id == "00000000"
```

(Импорт `KaspiSettings` уже есть в шапке файла из Task 1.)

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_kaspi_settings.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kaspi'`

- [ ] **Step 3: Реализация**

Создать пустой `app/kaspi/__init__.py`.

`app/kaspi/settings.py`:
```python
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import KaspiSettings


def get_settings(session: Session) -> KaspiSettings:
    """Возвращает единственную строку настроек, создавая её при первом обращении."""
    s = session.get(KaspiSettings, 1)
    if s is None:
        s = KaspiSettings(id=1)
        session.add(s)
        session.commit()
    return s


def save_config(session: Session, *, terminal_url: str, cashier_name: str) -> None:
    s = get_settings(session)
    s.terminal_url = terminal_url
    s.cashier_name = cashier_name
    session.commit()


def save_tokens(session: Session, *, access_token: str, refresh_token: str,
                expires_at: datetime | None) -> None:
    s = get_settings(session)
    s.access_token = access_token
    s.refresh_token = refresh_token
    s.token_expires_at = expires_at
    session.commit()


def save_terminal_id(session: Session, *, terminal_id: str) -> None:
    s = get_settings(session)
    s.terminal_id = terminal_id
    session.commit()
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 5: Commit**

```bash
git add app/kaspi/__init__.py app/kaspi/settings.py tests/test_kaspi_settings.py
git commit -m "feat: kaspi settings repository (singleton row)"
```

---

### Task 5: HTTP-клиент терминала

**Files:**
- Create: `app/kaspi/client.py`
- Test: `tests/test_kaspi_client.py`

- [ ] **Step 1: Падающий тест**

`tests/test_kaspi_client.py`:
```python
import asyncio

import httpx
import pytest

from app.kaspi.client import KaspiClient, KaspiError


def _client(handler, **kw):
    return KaspiClient("http://term:8080", transport=httpx.MockTransport(handler), **kw)


def test_deviceinfo_ok():
    def handler(request):
        assert request.url.path == "/v2/deviceinfo"
        return httpx.Response(200, json={
            "data": {"posNum": "0", "serialNum": "ND000000000", "terminalId": "00000000"},
            "statusCode": 0,
        })
    data = asyncio.run(_client(handler).deviceinfo())
    assert data["serialNum"] == "ND000000000"
    assert data["terminalId"] == "00000000"


def test_register_sends_name_no_token():
    def handler(request):
        assert request.url.path == "/v2/register"
        assert request.url.params.get("name") == "Kashier1"
        assert "accesstoken" not in request.headers
        return httpx.Response(200, json={
            "data": {"accessToken": "acc", "refreshToken": "ref",
                     "expirationDate": "2026-07-23 12:00:00"},
            "statusCode": 0,
        })
    data = asyncio.run(_client(handler).register("Kashier1"))
    assert data["accessToken"] == "acc"
    assert data["expirationDate"] == "2026-07-23 12:00:00"


def test_payment_sends_amount_and_token():
    def handler(request):
        assert request.url.path == "/v2/payment"
        assert request.url.params.get("amount") == "1500"
        assert request.url.params.get("owncheque") == "false"
        assert request.headers.get("accesstoken") == "acc"
        return httpx.Response(200, json={
            "data": {"processId": "p1", "status": "wait"}, "statusCode": 0,
        })
    data = asyncio.run(_client(handler, access_token="acc").payment(1500, owncheque=False))
    assert data["processId"] == "p1"


def test_status_sends_process_and_terminal_id():
    def handler(request):
        assert request.url.path == "/v2/status"
        assert request.url.params.get("processId") == "p1"
        assert request.headers.get("accesstoken") == "acc"
        assert request.headers.get("terminalId") == "00000000"
        return httpx.Response(200, json={
            "data": {"processId": "p1", "status": "success", "transactionId": "504711333",
                     "chequeInfo": {"method": "qr"}},
            "statusCode": 0,
        })
    data = asyncio.run(_client(handler, access_token="acc", terminal_id="00000000").status("p1"))
    assert data["status"] == "success"
    assert data["transactionId"] == "504711333"


def test_business_error_raises_kaspi_error():
    def handler(request):
        return httpx.Response(200, json={"errorText": "Process not found", "statusCode": 101})
    with pytest.raises(KaspiError) as exc:
        asyncio.run(_client(handler, access_token="acc").status("nope"))
    assert exc.value.status_code == 101
    assert "Process not found" in str(exc.value)


def test_http_error_raises_kaspi_error():
    def handler(request):
        return httpx.Response(403, text="Forbidden")
    with pytest.raises(KaspiError) as exc:
        asyncio.run(_client(handler, access_token="bad").deviceinfo())
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_kaspi_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kaspi.client'`

- [ ] **Step 3: Реализация**

`app/kaspi/client.py`:
```python
import httpx


class KaspiError(Exception):
    """Ошибка терминала Kaspi: HTTP-ошибка или statusCode != 0."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


class KaspiClient:
    """Async HTTP-клиент терминала Smart POS. Только ввод-вывод.

    verify=False: сертификат терминала выписан на *.kaspipos.kz, а мы ходим по IP —
    проверка по имени невозможна (документация это допускает, уровень защиты тот же).
    """

    def __init__(self, base_url: str, *, access_token: str | None = None,
                 terminal_id: str | None = None, transport: httpx.BaseTransport | None = None,
                 timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._terminal_id = terminal_id
        self._transport = transport
        self._timeout = timeout

    async def _get(self, path: str, *, params: dict | None = None,
                   headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url, verify=False,
                                     transport=self._transport, timeout=self._timeout) as c:
            resp = await c.get(path, params=params or {}, headers=headers or {})
        if resp.status_code >= 400:
            raise KaspiError(resp.status_code, resp.text or f"HTTP {resp.status_code}")
        body = resp.json()
        if body.get("statusCode", 0) != 0:
            msg = body.get("errorText") or (body.get("data") or {}).get("message") or "Ошибка терминала"
            raise KaspiError(body.get("statusCode", -1), msg)
        return body.get("data", {})

    def _auth_headers(self) -> dict:
        return {"accesstoken": self._access_token} if self._access_token else {}

    async def register(self, name: str) -> dict:
        return await self._get("/v2/register", params={"name": name})

    async def revoke(self, name: str, refresh_token: str) -> dict:
        return await self._get("/v2/revoke", params={"name": name, "refreshToken": refresh_token})

    async def deviceinfo(self) -> dict:
        return await self._get("/v2/deviceinfo", headers=self._auth_headers())

    async def payment(self, amount: int, *, owncheque: bool = False) -> dict:
        return await self._get(
            "/v2/payment",
            params={"amount": amount, "owncheque": str(owncheque).lower()},
            headers=self._auth_headers(),
        )

    async def status(self, process_id: str) -> dict:
        headers = self._auth_headers()
        if self._terminal_id:
            headers["terminalId"] = self._terminal_id
        return await self._get("/v2/status", params={"processId": process_id}, headers=headers)

    async def actualize(self, process_id: str) -> dict:
        return await self._get("/v2/actualize", params={"processId": process_id},
                               headers=self._auth_headers())
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_kaspi_client.py -q`
Expected: `6 passed`

- [ ] **Step 5: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 6: Commit**

```bash
git add app/kaspi/client.py tests/test_kaspi_client.py
git commit -m "feat: async Kaspi terminal HTTP client"
```

---

### Task 6: Сервис-оркестратор оплаты

**Files:**
- Create: `app/kaspi/service.py`
- Test: `tests/test_kaspi_service.py`

- [ ] **Step 1: Падающий тест**

`tests/test_kaspi_service.py`:
```python
import asyncio

import pytest

from app.kaspi import service as ks


def test_amount_to_tenge_whole():
    assert ks.amount_to_tenge(150000) == 1500


def test_amount_to_tenge_rejects_fraction():
    with pytest.raises(ValueError):
        ks.amount_to_tenge(150050)


class _FakeClient:
    """Фейковый клиент: отдаёт заранее заготовленные ответы status по очереди."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.payment_calls = []

    async def payment(self, amount, *, owncheque=False):
        self.payment_calls.append(amount)
        return {"processId": "p1", "status": "wait"}

    async def status(self, process_id):
        return self._statuses.pop(0)

    async def actualize(self, process_id):
        return {"status": "fail", "message": "Операция отменена"}


def test_poll_returns_success():
    fake = _FakeClient([
        {"status": "wait"},
        {"status": "wait"},
        {"status": "success", "transactionId": "504711333", "chequeInfo": {"method": "qr"}},
    ])
    data = asyncio.run(ks._poll_until_final(fake, "p1", poll_interval=0, max_polls=10))
    assert data["status"] == "success"
    assert data["transactionId"] == "504711333"


def test_poll_returns_fail():
    fake = _FakeClient([{"status": "wait"}, {"status": "fail", "message": "Отмена"}])
    data = asyncio.run(ks._poll_until_final(fake, "p1", poll_interval=0, max_polls=10))
    assert data["status"] == "fail"


def test_poll_timeout_returns_unknown():
    fake = _FakeClient([{"status": "wait"}, {"status": "wait"}, {"status": "wait"}])
    data = asyncio.run(ks._poll_until_final(fake, "p1", poll_interval=0, max_polls=3))
    assert data["status"] == "unknown"


def test_run_payment_success_maps_result():
    fake = _FakeClient([
        {"status": "wait"},
        {"status": "success", "transactionId": "R123", "chequeInfo": {"method": "card"}},
    ])
    result = asyncio.run(ks.run_payment(fake, 150000, poll_interval=0, max_polls=10))
    assert result.status == "success"
    assert result.terminal_method == "card"
    assert result.transaction_id == "R123"
    assert fake.payment_calls == [1500]


def test_run_payment_fraction_rejected():
    fake = _FakeClient([])
    with pytest.raises(ValueError):
        asyncio.run(ks.run_payment(fake, 150050, poll_interval=0, max_polls=10))


def test_run_payment_fail_maps_message():
    fake = _FakeClient([{"status": "fail", "message": "Покупатель отменил"}])
    result = asyncio.run(ks.run_payment(fake, 150000, poll_interval=0, max_polls=10))
    assert result.status == "fail"
    assert "отменил" in result.message


def test_run_payment_unknown_calls_actualize():
    fake = _FakeClient([{"status": "wait"}, {"status": "wait"}])  # таймаут → unknown → actualize→fail
    result = asyncio.run(ks.run_payment(fake, 150000, poll_interval=0, max_polls=2))
    assert result.status == "fail"  # actualize вернул fail
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv\Scripts\python -m pytest tests/test_kaspi_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kaspi.service'`

- [ ] **Step 3: Реализация**

`app/kaspi/service.py`:
```python
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.kaspi import settings as ksettings
from app.kaspi.client import KaspiClient, KaspiError

logger = logging.getLogger(__name__)

_EXPIRATION_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class PaymentResult:
    status: str  # "success" | "fail" | "unknown"
    terminal_method: str | None = None  # "qr" | "card" | "alaqan"
    transaction_id: str | None = None
    message: str | None = None


def amount_to_tenge(total_tiyn: int) -> int:
    """Конвертирует тиыны в целые тенге. Терминал не принимает дробные тенге."""
    if total_tiyn % 100 != 0:
        raise ValueError("Kaspi принимает только целые тенге")
    return total_tiyn // 100


async def _poll_until_final(client, process_id: str, *, poll_interval: float, max_polls: int) -> dict:
    """Опрашивает статус до финального состояния. По исчерпании попыток — unknown."""
    for _ in range(max_polls):
        data = await client.status(process_id)
        if data.get("status") != "wait":
            return data
        await asyncio.sleep(poll_interval)
    return {"status": "unknown", "message": "Таймаут ожидания оплаты"}


def _map_result(data: dict) -> PaymentResult:
    status = data.get("status", "unknown")
    if status == "success":
        return PaymentResult(
            status="success",
            terminal_method=(data.get("chequeInfo") or {}).get("method"),
            transaction_id=data.get("transactionId"),
        )
    return PaymentResult(status=status, message=data.get("message"))


async def run_payment(client, total_tiyn: int, *, poll_interval: float = 1.0,
                      max_polls: int = 180) -> PaymentResult:
    """Полный цикл оплаты на уже сконфигурированном клиенте (без БД).

    Проверяет сумму, запускает payment, опрашивает статус; при unknown пробует actualize.
    """
    amount = amount_to_tenge(total_tiyn)
    pay_data = await client.payment(amount, owncheque=False)
    process_id = pay_data["processId"]
    data = await _poll_until_final(client, process_id, poll_interval=poll_interval, max_polls=max_polls)
    if data.get("status") == "unknown":
        try:
            data = await client.actualize(process_id)
        except KaspiError:
            logger.exception("actualize не удался для %s", process_id)
    return _map_result(data)


def _parse_expiration(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, _EXPIRATION_FMT)
    except ValueError:
        return None


def _build_client(s) -> KaspiClient:
    return KaspiClient(s.terminal_url, access_token=s.access_token, terminal_id=s.terminal_id)


async def check_connection(session: Session) -> dict:
    """Проверка связи: deviceinfo. Работает и без токена."""
    s = ksettings.get_settings(session)
    client = _build_client(s)
    data = await client.deviceinfo()
    if data.get("terminalId"):
        ksettings.save_terminal_id(session, terminal_id=data["terminalId"])
    return data


async def register_cashier(session: Session) -> None:
    """Регистрация кассы: register → сохраняем токены; затем deviceinfo → terminalId."""
    s = ksettings.get_settings(session)
    client = KaspiClient(s.terminal_url)  # register без токена
    data = await client.register(s.cashier_name)
    ksettings.save_tokens(
        session,
        access_token=data["accessToken"],
        refresh_token=data["refreshToken"],
        expires_at=_parse_expiration(data.get("expirationDate")),
    )
    info = await _build_client(ksettings.get_settings(session)).deviceinfo()
    if info.get("terminalId"):
        ksettings.save_terminal_id(session, terminal_id=info["terminalId"])


async def pay(session: Session, total_tiyn: int, *, poll_interval: float = 1.0,
              max_polls: int = 180) -> PaymentResult:
    """Оплата с настройками из БД. Требует зарегистрированной кассы (есть access_token)."""
    s = ksettings.get_settings(session)
    if not s.access_token:
        raise ValueError("Касса не зарегистрирована на терминале (см. /admin/kaspi)")
    client = _build_client(s)
    return await run_payment(client, total_tiyn, poll_interval=poll_interval, max_polls=max_polls)
```

Примечание: `ensure_token` (проактивное обновление токена) сознательно НЕ реализуется в этом этапе — токен живёт 24 часа, а обновление добавило бы заметную сложность (сравнение времени, повтор при 403). Если токен истёк, `pay`/`check_connection` получат `KaspiError(403)`, и кассир/админ повторно нажмёт «Зарегистрировать кассу». Это зафиксировано в бэклоге плана.

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python -m pytest tests/test_kaspi_service.py -q`
Expected: все PASS

- [ ] **Step 5: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS

- [ ] **Step 6: Commit**

```bash
git add app/kaspi/service.py tests/test_kaspi_service.py
git commit -m "feat: kaspi payment orchestration (poll, actualize, register)"
```

---

### Task 7: Экран настройки /admin/kaspi

**Files:**
- Create: `app/ui/kaspi_admin.py`
- Modify: `app/ui/__init__.py`, `app/ui/admin_stock.py`

UI-обвязка вокруг протестированного сервиса; проверяется импортом + ручным рендером.

- [ ] **Step 1: Реализация страницы**

`app/ui/kaspi_admin.py`:
```python
from nicegui import ui

from app.db import SessionLocal
from app.kaspi import service as kaspi_service
from app.kaspi import settings as ksettings
from app.kaspi.client import KaspiError
from app.ui.guard import require_admin


@ui.page("/admin/kaspi")
def kaspi_admin_page() -> None:
    if not require_admin():
        return

    ui.label("Настройка терминала Kaspi").classes("text-2xl font-bold")

    with SessionLocal() as session:
        s = ksettings.get_settings(session)
        url_value = s.terminal_url
        name_value = s.cashier_name
        has_token = s.access_token is not None
        term_id = s.terminal_id

    url_in = ui.input("Адрес терминала", value=url_value).classes("w-full max-w-md")
    name_in = ui.input("Имя кассы", value=name_value).classes("w-full max-w-md")
    status_box = ui.column().classes("gap-1 mt-2")

    with status_box:
        ui.label(f"Токен: {'получен' if has_token else 'не получен'}").classes(
            "text-green-700" if has_token else "text-gray-500")
        if term_id:
            ui.label(f"ID терминала: {term_id}")

    def save_config() -> None:
        with SessionLocal() as session:
            ksettings.save_config(session, terminal_url=url_in.value.strip(),
                                  cashier_name=name_in.value.strip())
        ui.notify("Настройки сохранены", color="green")

    async def check() -> None:
        save_config()
        try:
            with SessionLocal() as session:
                data = await kaspi_service.check_connection(session)
        except (KaspiError, Exception) as e:
            ui.notify(f"Нет связи с терминалом: {e}", color="red")
            return
        ui.notify(
            f"Терминал на связи. Серийный: {data.get('serialNum')}, ID: {data.get('terminalId')}",
            color="green",
        )

    async def register() -> None:
        save_config()
        ui.notify("Подтвердите доступ на экране терминала…", color="blue")
        try:
            with SessionLocal() as session:
                await kaspi_service.register_cashier(session)
        except (KaspiError, Exception) as e:
            ui.notify(f"Регистрация не удалась: {e}", color="red")
            return
        ui.notify("Касса зарегистрирована, токен получен", color="green")

    with ui.row().classes("gap-2 mt-2"):
        ui.button("Сохранить", on_click=save_config)
        ui.button("Проверить связь", on_click=check)
        ui.button("Зарегистрировать кассу", on_click=register, color="green")
```

- [ ] **Step 2: Зарегистрировать страницу**

`app/ui/__init__.py` — добавить `kaspi_admin` в список импорта `register_pages` (по алфавиту после `cashier`):
```python
def register_pages() -> None:
    """Импортирует модули страниц NiceGUI (каждый регистрирует свои @ui.page)."""
    from app.ui import (  # noqa: F401
        admin_dashboard,
        admin_menu,
        admin_modifiers,
        admin_stock,
        cashier,
        kaspi_admin,
        login,
        purchase,
    )
```

- [ ] **Step 3: Кнопка навигации в admin_stock**

В `app/ui/admin_stock.py`, в блоке `with ui.row().classes("gap-2"):` (сразу после заголовка, добавлен на этапе 3) добавить третью кнопку:
```python
    with ui.row().classes("gap-2"):
        ui.button("Дашборд", on_click=lambda: ui.navigate.to("/admin/dashboard"))
        ui.button("Приход товара", on_click=lambda: ui.navigate.to("/stock/purchase"))
        ui.button("Kaspi терминал", on_click=lambda: ui.navigate.to("/admin/kaspi"))
```

- [ ] **Step 4: Регресс + smoke-импорт**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (импорт `kaspi_admin` через `register_pages` косвенно проверяется `tests/test_app.py::test_health`).

Run: `.venv\Scripts\python -c "from app.main import create_app; create_app(start_bot=False); print('ok')"`
Expected: `ok`. Удалить созданный при этом `pos.db`, если он не существовал (он в `.gitignore`).

- [ ] **Step 5: Commit**

```bash
git add app/ui/kaspi_admin.py app/ui/__init__.py app/ui/admin_stock.py
git commit -m "feat: /admin/kaspi settings and connection-check screen"
```

---

### Task 8: Поток оплаты — способ «Kaspi (терминал)»

**Files:**
- Modify: `app/ui/cashier.py` (функция `open_payment` внутри `sale_page`)

- [ ] **Step 1: Добавить способ и async-обработку**

В `app/ui/cashier.py` добавить импорты в шапку (рядом с существующими):
```python
from app.kaspi import service as kaspi_service
from app.kaspi.client import KaspiError
```

В `open_payment`, в НЕ-split селекте способа (`single_col`) заменить список способов, добавив «Kaspi (терминал)»:
```python
                method = ui.select({"cash": "Наличные", "card": "Карта",
                                    "kaspi_qr": "Kaspi QR (вручную)",
                                    "kaspi_terminal": "Kaspi (терминал)"},
                                   label="Способ", value="cash")
```

Сделать `confirm_payment` асинхронной и добавить терминальную ветку ПЕРВОЙ (до обычной логики). Заменить сигнатуру `def confirm_payment() -> None:` на `async def confirm_payment() -> None:` и в самое начало её тела (после строки `def confirm_payment`... — то есть первым делом внутри) добавить:
```python
            async def confirm_payment() -> None:
                # Терминальная Kaspi-оплата: только как единственный способ (не в split)
                if not split.value and method.value == "kaspi_terminal":
                    try:
                        amount_ok = (total % 100 == 0)
                    except Exception:
                        amount_ok = False
                    if not amount_ok:
                        ui.notify("Kaspi принимает только целые тенге", color="red")
                        return
                    ui.notify("Ожидание оплаты на терминале… клиент сканирует QR или прикладывает карту",
                              color="blue")
                    try:
                        with SessionLocal() as s:
                            result = await kaspi_service.pay(s, total)
                    except (ValueError, KaspiError) as e:
                        ui.notify(str(e), color="red")
                        return
                    except Exception:
                        ui.notify("Ошибка связи с терминалом. Чек не проведён.", color="red")
                        return
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
                    except (ValueError, PermissionError) as e:
                        ui.notify(f"Оплата прошла, но чек не сохранён: {e}", color="red")
                        return
                    dialog.close()
                    cart.clear()
                    render_cart()
                    ui.notify(f"Заказ №{num} оплачен через Kaspi ({result.terminal_method}).", color="green")
                    return
                # --- дальше прежняя (синхронная) логика для остальных способов ---
```
Остальное тело `confirm_payment` (split-ветка и обычная не-split логика с наличными/картой/ручным Kaspi) оставить БЕЗ изменений — оно уже корректно и просто идёт после терминальной ветки.

Важно: `on_click=confirm_payment` в `ui.button("Провести", ...)` уже принимает корутину — NiceGUI поддерживает async-обработчики, менять регистрацию кнопки не нужно.

- [ ] **Step 2: Регресс + smoke-импорт**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS (UI-поток тестами не покрывается; логика оплаты уже покрыта в `test_kaspi_service.py` и `test_sales_service.py`).

Run: `.venv\Scripts\python -c "import app.ui.cashier; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Ручная проверка потока без терминала**

Поскольку без включённой «Защиты интеграции» и токена реальная оплата не пройдёт, проверить, что ветка корректно ведёт себя при отсутствии регистрации:
1. Убедиться, что в `pos.db` есть строка `kaspi_settings` без токена (создаётся при первом заходе на `/admin/kaspi` или `get_settings`).
2. Прямой вызов логики (без UI), эмулирующий нажатие «Провести» с Kaspi-терминалом на незарегистрированной кассе:
```powershell
.venv\Scripts\python -c "import asyncio; from app.db import SessionLocal, init_db; from app.kaspi import service as ks; init_db();
async def go():
    with SessionLocal() as s:
        try:
            await ks.pay(s, 150000)
        except ValueError as e:
            print('OK, ожидаемая ошибка:', e)
asyncio.run(go())"
```
Expected: `OK, ожидаемая ошибка: Касса не зарегистрирована на терминале (см. /admin/kaspi)`. Это подтверждает, что при отсутствии регистрации чек не проводится и кассиру покажется понятная ошибка (можно выбрать ручной способ-запас).

- [ ] **Step 4: Commit**

```bash
git add app/ui/cashier.py
git commit -m "feat: real Kaspi terminal payment option in sale screen"
```

---

### Task 9: Seed, README и финальная проверка

**Files:**
- Modify: `seed.py`, `README.md`

- [ ] **Step 1: Создавать строку KaspiSettings в seed**

В `seed.py` добавить импорт `KaspiSettings` в блок `from app.models import (...)` (по алфавиту), и перед финальным `s.commit()` в функции `seed` добавить:
```python
        s.add(KaspiSettings(id=1))
```

- [ ] **Step 2: Обновить README.md**

Добавить новый раздел после «Дашборд администратора» (перед «Доступ из Telegram»):
```markdown
## Оплата через терминал Kaspi

`/admin/kaspi` (только админ) — адрес терминала, «Проверить связь», «Зарегистрировать
кассу». Порядок первого подключения:

1. На самом терминале Smart POS включить «Защита интеграции» (панель администратора).
2. В `/admin/kaspi` указать адрес (`https://<ip-терминала>:8080` при включённой защите) и
   имя кассы, нажать «Зарегистрировать кассу» и подтвердить доступ на экране терминала.
3. На экране продажи выбрать способ «Kaspi (терминал)» — терминал сам покажет QR/примет
   карту, чек проведётся только после подтверждения оплаты. Чек печатает сам терминал.

Если терминал недоступен, остаётся запасной способ «Kaspi QR (вручную)» — оплата
отмечается кассиром вручную (в отчётах помечена как ручная).
```

- [ ] **Step 3: Полный регресс**

Run: `.venv\Scripts\python -m pytest -q`
Expected: все PASS.

- [ ] **Step 4: Проверить seed на свежей БД**

Run:
```powershell
Remove-Item seedcheck.db -ErrorAction SilentlyContinue
$env:DATABASE_URL = "sqlite:///seedcheck.db"
.venv\Scripts\python seed.py 100000001
.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('seedcheck.db'); print('kaspi_settings rows:', c.execute('select count(*) from kaspi_settings').fetchone()[0])"
Remove-Item seedcheck.db -ErrorAction SilentlyContinue
Remove-Item Env:\DATABASE_URL
```
Expected: `kaspi_settings rows: 1`.

- [ ] **Step 5: Commit**

```bash
git add seed.py README.md
git commit -m "docs: seed default Kaspi settings row and README for terminal payment"
```

---

## Самопроверка плана

- **Покрытие спецификации:** модель `KaspiSettings` + поля `Payment` — задача 1;
  `PaymentInput`/`validate_payments`/`create_sale` — задача 2; миграция живой БД —
  задача 3 (не было в спеке явно, но необходимо: боевая `pos.db` не имеет новых колонок);
  репозиторий настроек — задача 4; HTTP-клиент (`register`/`revoke`/`deviceinfo`/`payment`/
  `status`/`actualize`) — задача 5; оркестрация с опросом статуса, `amount_to_tenge`,
  `actualize` при `unknown` — задача 6; экран `/admin/kaspi` (проверка связи, регистрация)
  — задача 7; поток оплаты «Kaspi (терминал)» с проведением чека только после подтверждения
  — задача 8; seed + README — задача 9.
- **Осознанное упрощение против спеки:** проактивное обновление токена (`ensure_token`)
  не реализуется — вместо этого при истечении токена (`403`) админ повторно регистрирует
  кассу. Зафиксировано ниже в бэклоге. Всё остальное из разделов 1-7 спеки покрыто.
- **Согласованность типов/сигнатур:** `PaymentInput(method, amount_tiyn, tendered_tiyn=None,
  provider="manual", terminal_method=None, transaction_id=None)` — единый конструктор в
  задачах 2 и 8; `KaspiClient(base_url, *, access_token, terminal_id, transport, timeout)` —
  задачи 5, 6; `run_payment(client, total_tiyn, *, poll_interval, max_polls) -> PaymentResult`
  и `pay(session, total_tiyn, ...)` — задачи 6, 8; `PaymentResult(status, terminal_method,
  transaction_id, message)` — задачи 6, 8; `ksettings.get_settings/save_config/save_tokens/
  save_terminal_id` — задачи 4, 6, 7; `ensure_schema(engine)` — задача 3.
- **Заглушек нет** — весь код каждой задачи приведён полностью.
- **Бэклог (не блокирует этап):**
  - Проактивное обновление токена (сейчас — повторная регистрация при `403`).
  - Возврат через терминал (`/v2/refund` с сохранённым `transaction_id`+`terminal_method`).
  - Единый catch-all по `OperationalError` на страницах записи (общий пункт из этапа 3).
  - Разделённая оплата с Kaspi-терминалом как одной ногой.
