from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    role: Mapped[str]  # "cashier" | "admin"
    pin_hash: Mapped[str | None] = mapped_column(default=None)
    discount_limit_percent: Mapped[int] = mapped_column(default=10)
    is_active: Mapped[bool] = mapped_column(default=True)
