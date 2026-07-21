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

## Работа кассира

1. Открыть Mini App в Telegram (или локально `http://localhost:8080/login`).
2. Войти: выбрать пользователя, ввести пин-код (в seed кассир — пин `1234`).
3. Открыть смену, указав стартовую наличность.
4. Экран продажи: категория → товар → (модификаторы) → корзина → «Оплата»
   (наличные со сдачей, карта или Kaspi QR).
5. Возвраты — на отдельном экране, с указанием причины.
6. В конце — закрыть смену: система покажет ожидаемую наличность, кассир вводит фактическую.

Разделы администратора: `/admin/menu`, `/admin/stock`, `/admin/modifiers` (только для роли admin).

## Доступ из Telegram (Mini App)

Telegram открывает Mini App только по публичному HTTPS. Локально — туннель:

```powershell
winget install Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8080
```

Выданный адрес `https://...trycloudflare.com` вписать в `.env` → `PUBLIC_URL`
и перезапустить приложение. Кнопка «Открыть кассу» в боте начнёт работать.

⚠️ Туннель публикует админку (`/admin/menu`, `/admin/stock`) в интернет без пароля —
поднимайте его только на время работы за кассой и закрывайте после смены.
Авторизация по Telegram для веб-интерфейса появится на этапе 2.

## Тесты

```powershell
.venv\Scripts\python -m pytest -q
```
