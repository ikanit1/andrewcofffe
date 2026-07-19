# Coffee POS — касса кофейни в Telegram

Один Python-процесс: FastAPI + NiceGUI (интерфейс) + aiogram (бот). БД — SQLite.

## Первый запуск

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env   # вписать BOT_TOKEN от @BotFather и STORAGE_SECRET
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
