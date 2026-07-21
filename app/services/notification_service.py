from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NotificationOutbox
from app.models.inventory import utcnow


def enqueue(session: Session, *, kind: str, text: str) -> NotificationOutbox:
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
    note = session.get(NotificationOutbox, notification_id)
    if note is not None:
        note.status = "sent"
        note.sent_at = utcnow()
        session.commit()


def mark_failed(session: Session, notification_id: int) -> None:
    note = session.get(NotificationOutbox, notification_id)
    if note is not None:
        note.status = "failed"
        session.commit()
