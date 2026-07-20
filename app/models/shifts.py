from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inventory import utcnow


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    opening_cash_tiyn: Mapped[int] = mapped_column(default=0)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expected_cash_tiyn: Mapped[int | None] = mapped_column(default=None)
    counted_cash_tiyn: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="open")  # "open" | "closed"


class CashCollection(Base):
    """Инкассация: изъятие наличности в течение смены."""

    __tablename__ = "cash_collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    amount_tiyn: Mapped[int]
    note: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
