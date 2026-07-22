# Продакшн-обвязка и установщик — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Автобэкапы БД с копией в Telegram + автозапуск на моноблоке + установщик `install.ps1`, оформленные в репозитории.

**Architecture:** Ядро бэкапа — сервис на `sqlite3.Connection.backup()` (онлайн-снимок, безопасно при WAL) с ротацией; отправка файла админам через aiogram; расписание — asyncio-задача в `lifespan`. Ops-часть — PowerShell-скрипты автозапуска (Планировщик + kiosk-браузер) и единый `install.ps1`.

**Tech Stack:** Python 3.13, SQLAlchemy, aiogram, sqlite3 backup API, PowerShell, schtasks, winget.

**Спека:** `docs/superpowers/specs/2026-07-22-deploy-installer-design.md`

**Соглашение по тестам:** Python-части покрываются pytest (без новых зависимостей). PowerShell-скрипты (`deploy/*.ps1`, `install.ps1`, `update.ps1`) — проверяются вручную, в CI не гоняются. После Python-задач полный `pytest` должен остаться зелёным (ориентир 122 + новые).

---

## File Structure

- **Create** `app/services/backup_service.py` — снимок БД, ротация, отправка админам, `run_backup_once`, `BackupResult`.
- **Create** `app/services/backup_scheduler.py` — `seconds_until` + цикл расписания.
- **Modify** `app/services/user_service.py` — `admin_telegram_ids`.
- **Modify** `app/config.py` — поля бэкапа.
- **Modify** `app/main.py` — запуск планировщика в `lifespan`.
- **Modify** `app/ui/admin_dashboard.py` — кнопка «Сделать бэкап сейчас».
- **Create** `deploy/run-server.ps1`, `deploy/run-kiosk.ps1`, `install.ps1`, `update.ps1`, `.env.example`.
- **Modify** `.gitignore`, `README.md`.
- **Create tests** `tests/test_backup_service.py`, `tests/test_backup_scheduler.py`; **modify** `tests/test_user_service.py`.

---

### Task 1: Поля конфига + .gitignore

**Files:**
- Modify: `app/config.py`
- Modify: `.gitignore`

- [ ] **Step 1: Добавить поля в `app/config.py`**

Заменить тело класса `Settings` (после `storage_secret`) — добавить строки:
```python
    bot_token: str = ""
    database_url: str = "sqlite:///pos.db"
    public_url: str = "http://localhost:8080"
    storage_secret: str = "change-me-in-env"
    backup_enabled: bool = True
    backup_time: str = "03:00"          # Asia/Almaty
    backup_keep_days: int = 14
    backups_dir: str = "backups"
```

- [ ] **Step 2: Добавить пути в `.gitignore`**

В конец `.gitignore` добавить:
```
backups/
logs/
```

- [ ] **Step 3: Проверить импорт**

Run: `python -c "from app.config import settings; print(settings.backup_time, settings.backup_keep_days)"`
Expected: `03:00 14`

- [ ] **Step 4: Commit**

```bash
git add app/config.py .gitignore
git commit -m "chore: backup config fields and gitignore backups/logs"
```

---

### Task 2: `make_local_backup` + ротация

**Files:**
- Create: `app/services/backup_service.py`
- Test: `tests/test_backup_service.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_backup_service.py`:
```python
import os
import sqlite3
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from app.services import backup_service as bs


def _file_engine(tmp_path):
    db = tmp_path / "source.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
        conn.execute(text("INSERT INTO t (v) VALUES ('alpha'), ('beta')"))
    return engine


def test_make_local_backup_copies_data(tmp_path):
    engine = _file_engine(tmp_path)
    dest_dir = tmp_path / "backups"
    path = bs.make_local_backup(engine=engine, backups_dir=dest_dir, keep_days=14)
    assert path.exists()
    con = sqlite3.connect(path)
    rows = con.execute("SELECT v FROM t ORDER BY id").fetchall()
    con.close()
    assert [r[0] for r in rows] == ["alpha", "beta"]


def test_make_local_backup_rotation(tmp_path):
    engine = _file_engine(tmp_path)
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    old = dest_dir / "pos-20000101-000000.db"
    old.write_bytes(b"old")
    old_time = time.time() - 40 * 86400
    os.utime(old, (old_time, old_time))
    bs.make_local_backup(engine=engine, backups_dir=dest_dir, keep_days=14)
    assert not old.exists()               # старше keep_days — удалён
    assert list(dest_dir.glob("pos-*.db"))  # свежий снимок остался
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_backup_service.py -q`
Expected: FAIL (`module app.services.backup_service has no attribute make_local_backup` / ImportError)

- [ ] **Step 3: Реализовать `make_local_backup`**

Создать `app/services/backup_service.py`:
```python
import logging
import sqlite3
import time
from pathlib import Path

from app.db import engine as default_engine
from app.models.inventory import utcnow
from app.timezone import to_almaty

logger = logging.getLogger(__name__)


def _rotate(backups_dir: Path, keep_days: int) -> None:
    cutoff = time.time() - keep_days * 86400
    for f in backups_dir.glob("pos-*.db"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            logger.warning("Не удалось удалить старый бэкап %s", f)


def make_local_backup(*, engine=None, backups_dir=None, keep_days=None, now=None) -> Path:
    """Онлайн-снимок SQLite через sqlite3.backup() (безопасно при WAL) + ротация."""
    from app.config import settings
    engine = engine if engine is not None else default_engine
    backups_dir = Path(backups_dir) if backups_dir is not None else Path(settings.backups_dir)
    keep_days = keep_days if keep_days is not None else settings.backup_keep_days
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = to_almaty(now or utcnow()).strftime("%Y%m%d-%H%M%S")
    dest_path = backups_dir / f"pos-{stamp}.db"
    raw = engine.raw_connection()
    try:
        src = raw.driver_connection
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        raw.close()
    _rotate(backups_dir, keep_days)
    return dest_path
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_backup_service.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/backup_service.py tests/test_backup_service.py
git commit -m "feat(backup): online sqlite snapshot with rotation"
```

---

### Task 3: `admin_telegram_ids` в user_service

**Files:**
- Modify: `app/services/user_service.py`
- Test: `tests/test_user_service.py`

- [ ] **Step 1: Написать падающий тест**

В конец `tests/test_user_service.py` добавить:
```python
def test_admin_telegram_ids_only_active_admins(session):
    _user(session, tid=10, role="admin", active=True)
    _user(session, tid=11, role="admin", active=False)
    _user(session, tid=12, role="cashier", active=True)
    assert us.admin_telegram_ids(session) == [10]
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_user_service.py::test_admin_telegram_ids_only_active_admins -q`
Expected: FAIL (`module ... has no attribute admin_telegram_ids`)

- [ ] **Step 3: Реализовать**

В `app/services/user_service.py` добавить функцию (рядом с `active_users`; убедиться, что импортированы `select` и `User` — они уже используются в модуле):
```python
def admin_telegram_ids(session: Session) -> list[int]:
    """Telegram ID активных админов — получатели уведомлений и бэкапов."""
    return list(session.scalars(
        select(User.telegram_id).where(User.role == "admin", User.is_active)
    ).all())
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_user_service.py -q`
Expected: PASS (все тесты модуля)

- [ ] **Step 5: Commit**

```bash
git add app/services/user_service.py tests/test_user_service.py
git commit -m "feat(users): admin_telegram_ids helper"
```

---

### Task 4: `send_backup_to_admins`, `BackupResult`, `run_backup_once`

**Files:**
- Modify: `app/services/backup_service.py`
- Test: `tests/test_backup_service.py`

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_backup_service.py` добавить (вверху дополнить импорты):
```python
import asyncio

from sqlalchemy.orm import sessionmaker

from app.models import User
from app.auth import hash_pin


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_document(self, chat_id, document, caption=None):
        self.sent.append((chat_id, caption))


def _seed_admins(engine, ids):
    from app.db import Base
    Base.metadata.create_all(engine)
    Sm = sessionmaker(bind=engine)
    with Sm() as s:
        for tid in ids:
            s.add(User(telegram_id=tid, name=f"A{tid}", role="admin",
                       is_active=True, pin_hash=hash_pin("1234")))
        s.commit()
    return Sm


def test_send_backup_to_admins_counts_deliveries(tmp_path):
    engine = _file_engine(tmp_path)
    Sm = _seed_admins(engine, [10, 20])
    bot = _FakeBot()
    f = tmp_path / "pos-x.db"
    f.write_bytes(b"db")
    with Sm() as s:
        n = asyncio.run(bs.send_backup_to_admins(bot, f, s, caption="c"))
    assert n == 2
    assert {c for c, _ in bot.sent} == {10, 20}


def test_run_backup_once_with_bot(tmp_path):
    engine = _file_engine(tmp_path)
    Sm = _seed_admins(engine, [10, 20])
    bot = _FakeBot()
    result = asyncio.run(bs.run_backup_once(
        engine=engine, backups_dir=tmp_path / "backups",
        session_factory=Sm, bot=bot))
    assert result.path.exists()
    assert result.delivered_count == 2
    assert result.error is None
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_backup_service.py -q`
Expected: FAIL (нет `send_backup_to_admins`/`run_backup_once`)

- [ ] **Step 3: Реализовать в `app/services/backup_service.py`**

Дополнить импорты вверху файла:
```python
from dataclasses import dataclass
```
Добавить в конец файла:
```python
@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    delivered_count: int
    error: str | None = None


async def send_backup_to_admins(bot, path: Path, session, *, caption: str) -> int:
    """Шлёт файл бэкапа каждому активному админу. Возвращает число доставок."""
    from aiogram.types import FSInputFile
    from app.services.user_service import admin_telegram_ids

    delivered = 0
    for tg_id in admin_telegram_ids(session):
        try:
            await bot.send_document(tg_id, FSInputFile(str(path)), caption=caption)
            delivered += 1
        except Exception:
            logger.exception("Не удалось отправить бэкап админу %s", tg_id)
    return delivered


async def run_backup_once(*, engine=None, backups_dir=None, session_factory=None,
                          bot=None, now=None) -> BackupResult:
    """Локальный снимок (всегда) + отправка админам (если есть бот/токен)."""
    from app.config import settings
    from app.db import SessionLocal

    session_factory = session_factory or SessionLocal
    path = make_local_backup(engine=engine, backups_dir=backups_dir, now=now)
    size = path.stat().st_size
    error = "Файл больше 50 МБ — Telegram может отклонить" if size > 50 * 1024 * 1024 else None

    owns_bot = False
    if bot is None and settings.bot_token:
        from aiogram import Bot
        bot = Bot(settings.bot_token)
        owns_bot = True

    delivered = 0
    if bot is not None:
        try:
            with session_factory() as session:
                stamp = to_almaty(now or utcnow()).strftime("%d.%m %H:%M")
                caption = f"Бэкап {stamp} ({size / 1024 / 1024:.1f} МБ)"
                delivered = await send_backup_to_admins(bot, path, session, caption=caption)
        except Exception as e:
            error = f"{error + '; ' if error else ''}отправка не удалась: {e}"
        finally:
            if owns_bot:
                await bot.session.close()

    return BackupResult(path=path, size_bytes=size, delivered_count=delivered, error=error)
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_backup_service.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/backup_service.py tests/test_backup_service.py
git commit -m "feat(backup): send to admins and run_backup_once orchestration"
```

---

### Task 5: Планировщик + интеграция в main

**Files:**
- Create: `app/services/backup_scheduler.py`
- Modify: `app/main.py`
- Test: `tests/test_backup_scheduler.py`

- [ ] **Step 1: Написать падающий тест `seconds_until`**

Создать `tests/test_backup_scheduler.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.backup_scheduler import seconds_until

TZ = ZoneInfo("Asia/Almaty")


def test_seconds_until_later_today():
    now = datetime(2026, 7, 22, 1, 0, tzinfo=TZ)
    assert seconds_until("03:00", now) == 2 * 3600


def test_seconds_until_wraps_to_tomorrow():
    now = datetime(2026, 7, 22, 4, 0, tzinfo=TZ)
    assert seconds_until("03:00", now) == 23 * 3600


def test_seconds_until_exact_now_is_next_day():
    now = datetime(2026, 7, 22, 3, 0, tzinfo=TZ)
    assert seconds_until("03:00", now) == 24 * 3600
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_backup_scheduler.py -q`
Expected: FAIL (нет модуля/функции)

- [ ] **Step 3: Реализовать `app/services/backup_scheduler.py`**

```python
import asyncio
import logging
from datetime import datetime, timedelta

from app.models.inventory import utcnow
from app.timezone import to_almaty

logger = logging.getLogger(__name__)


def seconds_until(target_hhmm: str, now: datetime) -> float:
    """Секунды от now до ближайшего наступления HH:MM (в той же таймзоне, что и now)."""
    hh, mm = (int(x) for x in target_hhmm.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_backup_scheduler(*, engine=None) -> None:
    """Раз в сутки в settings.backup_time делает бэкап. Ошибки не убивают цикл."""
    from app.config import settings
    from app.services.backup_service import run_backup_once

    while True:
        delay = seconds_until(settings.backup_time, to_almaty(utcnow()))
        await asyncio.sleep(delay)
        try:
            result = await run_backup_once(engine=engine)
            logger.info("Бэкап: %s (%d Б, доставлено %d)%s",
                        result.path, result.size_bytes, result.delivered_count,
                        f", ошибка: {result.error}" if result.error else "")
        except Exception:
            logger.exception("Плановый бэкап не удался")
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_backup_scheduler.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Подключить планировщик в `app/main.py`**

Добавить общий логгер-хелпер и запуск задачи. Заменить блок `lifespan` и добавить `_log_task_exit`:
```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bot_task = None
        if start_bot and settings.bot_token:
            from app.bot import run_bot

            bot_task = asyncio.create_task(run_bot())
            bot_task.add_done_callback(_log_bot_exit)
        backup_task = None
        if settings.backup_enabled:
            from app.services.backup_scheduler import run_backup_scheduler

            backup_task = asyncio.create_task(run_backup_scheduler())
            backup_task.add_done_callback(_log_task_exit)
        yield
        if bot_task is not None:
            bot_task.cancel()
        if backup_task is not None:
            backup_task.cancel()
```
И добавить рядом с `_log_bot_exit`:
```python
def _log_task_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Фоновая задача упала: %r", exc)
```

- [ ] **Step 6: import-smoke + регресс**

Run: `python -c "from app.main import create_app; create_app(start_bot=False); print('OK')"`
Expected: `OK`
Run: `python -m pytest -q`
Expected: все тесты зелёные.

- [ ] **Step 7: Commit**

```bash
git add app/services/backup_scheduler.py app/main.py tests/test_backup_scheduler.py
git commit -m "feat(backup): nightly scheduler wired into app lifespan"
```

---

### Task 6: Кнопка «Сделать бэкап сейчас» в админ-дашборде

**Files:**
- Modify: `app/ui/admin_dashboard.py`

- [ ] **Step 1: Добавить кнопку**

В `admin_dashboard_page`, сразу после `ui.label("Дашборд")...` и перед `box = ui.column(...)`, вставить:
```python
    async def do_backup() -> None:
        from app.services.backup_service import run_backup_once
        ui.notify("Делаю бэкап…")
        result = await run_backup_once()
        if result.error:
            ui.notify(f"Бэкап {result.path.name} сделан, но: {result.error}", color="orange")
        else:
            ui.notify(
                f"Бэкап готов: {result.path.name} "
                f"({result.size_bytes / 1024 / 1024:.1f} МБ), "
                f"в Telegram доставлено: {result.delivered_count}",
                color="green",
            )

    ui.button("Сделать бэкап сейчас", icon="backup", on_click=do_backup)
```

- [ ] **Step 2: import-smoke**

Run: `python -c "import app.ui.admin_dashboard; from app.main import create_app; create_app(start_bot=False); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/ui/admin_dashboard.py
git commit -m "feat(admin): manual backup button on dashboard"
```

---

### Task 7: Скрипты автозапуска (сервер + киоск)

**Files:**
- Create: `deploy/run-server.ps1`
- Create: `deploy/run-kiosk.ps1`

- [ ] **Step 1: Создать `deploy/run-server.ps1`**

```powershell
# Запуск POS-сервера из venv с авто-перезапуском при падении; лог в logs/server.log
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "server.log"
while ($true) {
    "[{0}] запуск сервера" -f (Get-Date) | Add-Content $log
    & $py -m app.main *>> $log
    "[{0}] сервер завершился, перезапуск через 3с" -f (Get-Date) | Add-Content $log
    Start-Sleep -Seconds 3
}
```

- [ ] **Step 2: Создать `deploy/run-kiosk.ps1`**

```powershell
# Ждём готовности сервера и открываем кассу в браузере (kiosk); фолбэк — обычное окно
$ErrorActionPreference = "SilentlyContinue"
$url = "http://localhost:8080"
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing "$url/health" -TimeoutSec 2
        if ($r.StatusCode -eq 200) { break }
    } catch {}
    Start-Sleep -Seconds 1
}
$edge = Join-Path ${Env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) {
    $edge = Join-Path $Env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"
}
if (Test-Path $edge) {
    & $edge --kiosk $url --edge-kiosk-type=fullscreen --no-first-run --disable-features=TranslateUI
} else {
    Start-Process $url
}
```

- [ ] **Step 3: Commit**

```bash
git add deploy/run-server.ps1 deploy/run-kiosk.ps1
git commit -m "feat(deploy): autostart scripts for server and kiosk browser"
```

---

### Task 8: `install.ps1`

**Files:**
- Create: `install.ps1`

- [ ] **Step 1: Создать `install.ps1`**

```powershell
# Установщик Coffee POS для Windows. Запуск: правой кнопкой -> Run with PowerShell
$ErrorActionPreference = "Stop"

# 1. Самоподнятие до администратора (нужно для schtasks/winget)
$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell "-ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

$root = $PSScriptRoot
Set-Location $root
Write-Host "=== Установка Coffee POS ===" -ForegroundColor Cyan

# 2. Python 3.13
$py = "py -3.13"
& py -3.13 --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.13 не найден — ставлю через winget..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
}

# 3. venv + зависимости
if (-not (Test-Path (Join-Path $root ".venv"))) {
    & py -3.13 -m venv .venv
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt

# 4. .env (если нет)
$envPath = Join-Path $root ".env"
if (-not (Test-Path $envPath)) {
    $secret = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $token = Read-Host "Токен Telegram-бота (Enter — пропустить, бэкапы будут только локально)"
    @(
        "BOT_TOKEN=$token"
        "STORAGE_SECRET=$secret"
        "PUBLIC_URL=http://localhost:8080"
        "DATABASE_URL=sqlite:///pos.db"
        "BACKUP_ENABLED=true"
        "BACKUP_TIME=03:00"
        "BACKUP_KEEP_DAYS=14"
        "BACKUPS_DIR=backups"
    ) | Set-Content -Path $envPath -Encoding UTF8
    Write-Host ".env создан (секрет сгенерирован)." -ForegroundColor Green
}

# 5. Заполнить базу, если пустая
$count = & $venvPy -c "from app.db import SessionLocal; from app.models import User; s=SessionLocal(); print(s.query(User).count()); s.close()"
if ($count.Trim() -eq "0") {
    $ownerId = Read-Host "Telegram ID владельца (для входа и бэкапов)"
    & $venvPy seed.py $ownerId
    Write-Host "Создан владелец (PIN 9999) и кассир (PIN 1234) — смените PIN после входа." -ForegroundColor Yellow
}

# 6. Задачи автозапуска (при входе в систему)
$srv = "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\deploy\run-server.ps1`""
$ksk = "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\deploy\run-kiosk.ps1`""
schtasks /Create /TN "CoffeePOS-Server" /TR $srv /SC ONLOGON /RL HIGHEST /F
schtasks /Create /TN "CoffeePOS-Kiosk"  /TR $ksk /SC ONLOGON /F

# 7. Стартуем сейчас и открываем кассу
Start-Process powershell "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\deploy\run-server.ps1`""
for ($i = 0; $i -lt 60; $i++) {
    try { if ((Invoke-WebRequest -UseBasicParsing "http://localhost:8080/health" -TimeoutSec 2).StatusCode -eq 200) { break } } catch {}
    Start-Sleep -Seconds 1
}
Start-Process "http://localhost:8080"

Write-Host ""
Write-Host "Готово. Дальше:" -ForegroundColor Cyan
Write-Host " • Смените PIN владельца/кассира." 
Write-Host " • Зарегистрируйте Kaspi-терминал: http://localhost:8080/admin/kaspi"
Write-Host " • Проверьте бэкап кнопкой «Сделать бэкап сейчас» в дашборде."
```

- [ ] **Step 2: Синтаксическая проверка скрипта (без выполнения)**

Run:
```
powershell -NoProfile -Command "$null=[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw install.ps1),[ref]$null); 'PARSE OK'"
```
Expected: `PARSE OK`

- [ ] **Step 3: Commit**

```bash
git add install.ps1
git commit -m "feat(deploy): one-shot install.ps1 (python, venv, .env, seed, autostart)"
```

---

### Task 9: `update.ps1` + `.env.example` + README + финальный регресс

**Files:**
- Create: `update.ps1`
- Create: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Создать `update.ps1`**

```powershell
# Обновление Coffee POS: тянем код, ставим зависимости, перезапускаем сервер
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
git pull
& (Join-Path $root ".venv\Scripts\python.exe") -m pip install -r requirements.txt
schtasks /End /TN "CoffeePOS-Server" 2>$null
Start-Sleep -Seconds 2
schtasks /Run /TN "CoffeePOS-Server"
Write-Host "Обновлено и перезапущено." -ForegroundColor Green
```

- [ ] **Step 2: Создать `.env.example`**

```
# Токен Telegram-бота (@BotFather). Пусто = без Telegram (бэкапы только локально).
BOT_TOKEN=
# Секрет подписи сессий. install.ps1 генерирует случайный; в проде не оставлять дефолт.
STORAGE_SECRET=change-me-in-env
# Адрес, который открывается в кассе и в кнопке бота
PUBLIC_URL=http://localhost:8080
# Подключение к БД
DATABASE_URL=sqlite:///pos.db
# Бэкапы
BACKUP_ENABLED=true
BACKUP_TIME=03:00
BACKUP_KEEP_DAYS=14
BACKUPS_DIR=backups
```

- [ ] **Step 3: Дописать в `README.md` раздел развёртывания**

Добавить в конец `README.md`:
```markdown
## Развёртывание в кофейне (Windows-моноблок)

### Установка в 3 шага
1. Скачайте проект (зелёная кнопка **Code → Download ZIP**) и распакуйте, или
   `git clone <repo>`.
2. Правой кнопкой по `install.ps1` → **Run with PowerShell** (согласитесь на права
   администратора).
3. Введите токен Telegram-бота и Telegram ID владельца по запросу. Касса откроется сама.

После установки приложение запускается автоматически при включении моноблока (сервер +
браузер в режиме киоска).

### Бэкапы
- Каждую ночь (по умолчанию 03:00) создаётся снимок БД в папке `backups/` и отправляется
  файлом владельцу в Telegram.
- Проверить вручную: в дашборде — кнопка **«Сделать бэкап сейчас»**.
- Настройки — в `.env`: `BACKUP_TIME`, `BACKUP_KEEP_DAYS`, `BACKUP_ENABLED`.

### Восстановление из бэкапа
1. Остановите сервер: `schtasks /End /TN CoffeePOS-Server`.
2. Замените файл `pos.db` в корне проекта на присланный в Telegram (переименуйте в
   `pos.db`); удалите `pos.db-wal` и `pos.db-shm`, если есть.
3. Запустите сервер: `schtasks /Run /TN CoffeePOS-Server`.

### Обновление
Правой кнопкой по `update.ps1` → **Run with PowerShell**.

### Kaspi-терминал
Один раз после установки зарегистрируйте терминал на `http://localhost:8080/admin/kaspi`.
```

- [ ] **Step 4: Финальный регресс**

Run: `python -m pytest -q`
Expected: все тесты зелёные (122 прежних + новые из backup).

- [ ] **Step 5: Commit**

```bash
git add update.ps1 .env.example README.md
git commit -m "docs(deploy): update.ps1, .env.example and deployment README"
```

---

## Self-Review

**Spec coverage:**
- backup_service (снимок + ротация) → Task 2 ✓
- send_backup_to_admins + BackupResult + run_backup_once → Task 4 ✓
- admin_telegram_ids → Task 3 ✓
- scheduler seconds_until + цикл + main.lifespan → Task 5 ✓
- config-поля + .gitignore → Task 1 ✓
- кнопка «Сделать бэкап сейчас» → Task 6 ✓
- deploy/run-server + run-kiosk → Task 7 ✓
- install.ps1 → Task 8 ✓
- update.ps1 + README + .env.example → Task 9 ✓

**Placeholder scan:** плейсхолдеров нет; весь код и все скрипты приведены целиком.

**Type consistency:** `make_local_backup(*, engine, backups_dir, keep_days, now)` — вызывается так же в `run_backup_once` и тестах. `BackupResult(path, size_bytes, delivered_count, error)` — используется в кнопке (Task 6) и планировщике (Task 5) с этими полями. `run_backup_once(*, engine, backups_dir, session_factory, bot, now)` — тест передаёт `engine/backups_dir/session_factory/bot`, планировщик и кнопка зовут без аргументов (дефолты). `admin_telegram_ids(session)` определён в Task 3, используется в `send_backup_to_admins` (Task 4). `seconds_until(target_hhmm, now)` — Task 5.

**Заметки по окружению:** тесты бэкапа используют файловую temp-БД (не in-memory фикстуру `session`), т.к. снимок делается с реального файла/соединения. `run_backup_once` в тесте получает `bot` и `session_factory` явно, поэтому реальный Telegram/`SessionLocal` не задействуются.
```
