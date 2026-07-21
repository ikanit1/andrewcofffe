from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inventory import utcnow


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    method: Mapped[str]  # "cash" | "card" | "kaspi_qr"
    amount_tiyn: Mapped[int]  # сколько этот способ покрывает в чеке
    tendered_tiyn: Mapped[int | None] = mapped_column(default=None)  # получено (наличные)
    change_tiyn: Mapped[int | None] = mapped_column(default=None)  # сдача (наличные)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provider: Mapped[str] = mapped_column(default="manual", server_default="manual")  # "manual" | "terminal"
    terminal_method: Mapped[str | None] = mapped_column(default=None)  # "qr" | "card" | "alaqan"
    transaction_id: Mapped[str | None] = mapped_column(default=None)  # orderNumber (qr/alaqan) или rrn (card)


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    amount_tiyn: Mapped[int]
    reason: Mapped[str]
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefundItem(Base):
    __tablename__ = "refund_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    refund_id: Mapped[int] = mapped_column(ForeignKey("refunds.id"), index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id"), default=None)
    qty: Mapped[int]
    amount_tiyn: Mapped[int | None] = mapped_column(default=None)  # сумма возврата по строке
