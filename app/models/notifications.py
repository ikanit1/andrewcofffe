from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inventory import utcnow


class NotificationOutbox(Base):
    """Очередь уведомлений админу. Получатель не хранится — берётся из активных
    админов на момент отправки (переживает изменение состава админов)."""

    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]  # "shift_open" | "shift_close" | "collection" | "refund" | "low_stock"
    text: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")  # "pending" | "sent" | "failed"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
