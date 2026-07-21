import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NotificationOutbox
from app.models.inventory import utcnow

logger = logging.getLogger(__name__)

NotificationKind = Literal["shift_open", "shift_close", "collection", "refund", "low_stock"]


def enqueue(session: Session, *, kind: NotificationKind, text: str) -> NotificationOutbox:
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
    """Коммитит сразу — вызывается из отдельной сессии фонового отправителя бота,
    не участвует в бизнес-транзакции."""
    note = session.get(NotificationOutbox, notification_id)
    if note is not None:
        note.status = "sent"
        note.sent_at = utcnow()
        session.commit()
    else:
        logger.warning("mark_sent: уведомление %s не найдено", notification_id)


def mark_failed(session: Session, notification_id: int) -> None:
    """Коммитит сразу — см. mark_sent."""
    note = session.get(NotificationOutbox, notification_id)
    if note is not None:
        note.status = "failed"
        session.commit()
    else:
        logger.warning("mark_failed: уведомление %s не найдено", notification_id)
