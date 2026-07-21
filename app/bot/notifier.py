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
            delivered = False
            for tg_id in admin_ids:
                try:
                    await bot.send_message(tg_id, note.text)
                    delivered = True
                except Exception:
                    logger.exception(
                        "Не удалось отправить уведомление %s админу %s", note.id, tg_id
                    )
            if delivered:
                ns.mark_sent(session, note.id)
