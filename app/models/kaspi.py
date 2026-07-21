from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KaspiSettings(Base):
    """Настройки интеграции с терминалом Kaspi Smart POS. Всегда одна строка (id=1)."""

    __tablename__ = "kaspi_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    terminal_url: Mapped[str] = mapped_column(default="http://192.168.0.100:8080")
    cashier_name: Mapped[str] = mapped_column(default="Kashier1")
    access_token: Mapped[str | None] = mapped_column(default=None)
    refresh_token: Mapped[str | None] = mapped_column(default=None)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    terminal_id: Mapped[str | None] = mapped_column(default=None)
