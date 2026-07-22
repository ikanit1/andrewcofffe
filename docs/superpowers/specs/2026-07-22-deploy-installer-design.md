# Дизайн: продакшн-обвязка и установщик для кофейни

Дата: 2026-07-22
Статус: утверждён владельцем

## Цель

Сделать так, чтобы приложение можно было развернуть на моноблоке в кофейне «за один
запуск»: автоматические бэкапы БД с внешней копией, автозапуск при включении, настройка
окружения и удобный установщик, оформленные в репозитории на GitHub. Закрывает Tier-1
пункты продакшн-готовности (в т.ч. ранее намеченный подпроект «бэкапы»).

## Ключевые решения (утверждены)

- **Внешняя копия бэкапа** → отправка файла БД в **Telegram владельцу(ам)** (тем же
  админам, кому идут уведомления; отдельный env не нужен).
- **Автозапуск** → **Планировщик заданий Windows** (триггер «При входе») + **браузер в
  kiosk-режиме**. Без сторонних служб.
- **Установщик** → единый **`install.ps1`**, при отсутствии Python ставит его через
  `winget`.

## Область

Входит: автобэкапы (локальный снимок + ротация + Telegram-копия + уведомление о
результате), встроенное расписание, кнопка «Сделать бэкап сейчас» в админке, скрипты
автозапуска (сервер + киоск), `install.ps1`, `update.ps1`, `README.md`, `.env.example`.

Вне рамок: отчётность/Excel, X-отчёт, управление пользователями в UI, фото товаров,
Alembic-миграции, восстановление одной кнопкой (восстановление — по инструкции в README).

## Архитектура и компоненты

### 1. `app/services/backup_service.py` (ядро, тестируемо)

- `make_local_backup(*, engine=engine, backups_dir=Path(settings.backups_dir), keep_days=settings.backup_keep_days, now=None) -> Path`
  - Делает **онлайн-снимок** через Python API `sqlite3.Connection.backup()`
    (консистентно при WAL, в отличие от сырого копирования файла):
    ```python
    raw = engine.raw_connection()
    try:
        src = raw.driver_connection            # низкоуровневый sqlite3.Connection
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = to_almaty(now or utcnow()).strftime("%Y%m%d-%H%M")
        dest_path = backups_dir / f"pos-{stamp}.db"
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        raw.close()
    ```
  - **Ротация**: после создания удаляет файлы `pos-*.db` в `backups_dir` старше
    `keep_days` (по времени в имени/mtime). Возвращает путь снимка.
  - Работает независимо от Telegram/токена.

- `async def send_backup_to_admins(bot, path: Path, session, *, caption: str) -> int`
  - Шлёт файл `bot.send_document(tg_id, FSInputFile(path), caption=caption)` каждому
    админу из `user_service.admin_telegram_ids(session)`; возвращает число успешных
    доставок; ошибки по каждому админу логирует, но не роняет остальных.

- `async def run_backup_once(*, engine=engine, now=None) -> BackupResult`
  - `path = make_local_backup(...)` (всегда).
  - Если `settings.bot_token`: создаёт временный `Bot(settings.bot_token)`, шлёт файл
    админам и текст-результат («✅ Бэкап за ДД.ММ отправлен (X МБ)» / при ошибке
    отправки — «⚠ Бэкап сделан локально, отправить не удалось: …»); корректно закрывает
    сессию бота (`await bot.session.close()`).
  - Возвращает `BackupResult(path, size_bytes, delivered_count, error)` —
    dataclass; используется кнопкой в UI и логами планировщика.
  - Предупреждение при `size_bytes > 50 МБ` (лимит Telegram sendDocument) — в результат
    и в текст админам.

### 2. `app/services/backup_scheduler.py` (расписание)

- `def seconds_until(target_hhmm: str, now) -> float` — чистая функция: секунды до
  ближайшего наступления времени `HH:MM` (в Asia/Almaty). Тестируется без сна.
- `async def run_backup_scheduler(*, engine=engine) -> None` — бесконечный цикл:
  `sleep(seconds_until(settings.backup_time, now))` → `await run_backup_once(...)` →
  повтор. Любое исключение из `run_backup_once` логируется, цикл продолжается (одна
  неудачная ночь не убивает планировщик).

### 3. Интеграция в `app/main.py`

В `lifespan` рядом с ботом запускать планировщик бэкапов **независимо от бота** (локальный
снимок нужен даже без токена):
```python
backup_task = None
if settings.backup_enabled:
    from app.services.backup_scheduler import run_backup_scheduler
    backup_task = asyncio.create_task(run_backup_scheduler())
    backup_task.add_done_callback(_log_task_exit)
...
# при остановке: backup_task.cancel()
```

### 4. `app/services/user_service.py` (+ хелпер)

- `def admin_telegram_ids(session) -> list[int]` — `telegram_id` активных админов
  (та же выборка, что в `bot/notifier.py`; выносим, чтобы переиспользовать).

### 5. Конфиг `app/config.py` (+ поля)

```python
backup_enabled: bool = True
backup_time: str = "03:00"        # Asia/Almaty
backup_keep_days: int = 14
backups_dir: str = "backups"
```

### 6. Админ-UI — кнопка «Сделать бэкап сейчас»

На `app/ui/admin_dashboard.py` добавить кнопку (видна админу): async-обработчик вызывает
`run_backup_once()`, показывает результат (`ui.notify`: путь/размер/сколько доставлено или
ошибка). Нужна для проверки сразу при установке.

### 7. `deploy/` — автозапуск

- `deploy/run-server.ps1` — активирует venv и запускает `python -m app.main` скрыто
  (без окна консоли), перенаправляя вывод в `logs/server.log`.
- `deploy/run-kiosk.ps1` — ждёт готовности `http://localhost:8080/health`, затем открывает
  браузер (Edge: `msedge --kiosk http://localhost:8080 --edge-kiosk-type=fullscreen
  --no-first-run`) на кассу.
- Установщик регистрирует задачи Планировщика (`schtasks /Create`): `CoffeePOS-Server` и
  `CoffeePOS-Kiosk`, триггер `ONLOGON`, для сервера — перезапуск при сбое.

### 8. `install.ps1` (единый установщик, самоподнимается до администратора)

Шаги:
1. Проверить права администратора; при отсутствии — перезапустить себя
   `Start-Process -Verb RunAs`.
2. Проверить Python 3.13 (`py -3.13 --version`); если нет — `winget install -e --id
   Python.Python.3.13`.
3. Создать `.venv`, `pip install -r requirements.txt`.
4. Если нет `.env` — сгенерировать `STORAGE_SECRET` (случайный),
   спросить `BOT_TOKEN` (можно пропустить — бэкапы будут только локальные), записать `.env`
   на основе `.env.example`.
5. Если база пустая — спросить Telegram ID владельца и запустить `python seed.py <id>`
   (создаст владельца PIN 9999 и кассира PIN 1234; в README — сменить PIN).
6. Зарегистрировать задачи автозапуска (сервер + киоск) через `schtasks`.
7. Запустить сервер, дождаться `/health`, открыть браузер.
8. Вывести памятку: сменить PIN, зарегистрировать Kaspi-терминал на `/admin/kaspi`,
   проверить бэкап кнопкой «Сделать бэкап сейчас».

### 9. `update.ps1`

`git pull` → `pip install -r requirements.txt` в venv → перезапуск задач сервера/киоска.

### 10. GitHub-оформление

- `README.md` (RU): назначение; требования; **Установка в 3 шага** (скачать/клонировать →
  запустить `install.ps1` → ввести токен и Telegram ID); где лежат бэкапы (`backups/` +
  Telegram); **как восстановиться** (заменить `pos.db` присланным файлом при остановленном
  сервере, перезапустить); как обновиться (`update.ps1`); настройка Kaspi.
- `.env.example` — все ключи с комментариями.
- `.gitignore` — добавить `backups/` и `logs/`.

## Обработка ошибок и краёв

- Нет интернета/бот недоступен ночью → локальный снимок всё равно сделан; отправка
  повторится следующей ночью; о неудаче отправки — запись в лог (и, если получится, текст
  админам при восстановлении связи не дублируем — просто следующий бэкап).
- Токен пуст → бэкапы только локальные (внешней копии нет — предупредить в README и в
  результате кнопки).
- Размер > 50 МБ → предупреждение (для кофейни маловероятно).
- `schtasks`/`winget` требуют админ → `install.ps1` самоподнимается.
- Снимок при активной записи → `sqlite3.backup()` безопасен (онлайн-бэкап SQLite).

## Тестирование

Юнит-тесты (pytest), без новых зависимостей:
- `make_local_backup`: на временной SQLite создаёт валидный снимок; данные в снимке
  совпадают с источником; ротация удаляет файлы старше `keep_days`, оставляет свежие.
- `admin_telegram_ids`: возвращает id только активных админов.
- `send_backup_to_admins`: с мок-ботом (объект с async `send_document`, пишущим вызовы)
  шлёт каждому админу, считает доставки, переживает ошибку одного получателя.
- `run_backup_once`: с мок-ботом и временной БД — делает снимок, зовёт отправку, формирует
  `BackupResult`; при пустом токене — только локальный снимок, `delivered_count == 0`.
- `seconds_until`: для набора «сейчас/цель» возвращает корректные секунды до ближайшего
  времени (в т.ч. переход через полночь).

PowerShell-скрипты и `install.ps1`/`update.ps1` — проверяются вручную (в CI не гоняются).
Полный регресс существующего набора остаётся зелёным (текущий ориентир — 122).

## Порядок реализации

1. Конфиг (поля) + `.gitignore` (`backups/`, `logs/`).
2. `backup_service.make_local_backup` + ротация + тесты.
3. `user_service.admin_telegram_ids` + `send_backup_to_admins` + тесты (мок-бот).
4. `run_backup_once` (+ `BackupResult`) + тесты.
5. `backup_scheduler.seconds_until` + цикл + интеграция в `main.lifespan` + тест
   `seconds_until`.
6. Кнопка «Сделать бэкап сейчас» в админ-дашборде.
7. `deploy/run-server.ps1`, `deploy/run-kiosk.ps1`.
8. `install.ps1`.
9. `update.ps1` + `README.md` + `.env.example`.
