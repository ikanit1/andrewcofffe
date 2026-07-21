import asyncio

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
    from app.bot.notifier import run_notifier

    notifier_task = asyncio.create_task(run_notifier(bot))
    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        notifier_task.cancel()
