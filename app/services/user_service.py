import json

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_pin, validate_init_data, verify_pin
from app.models import User


def _validate_pin(pin: str) -> None:
    if not (pin or "").isdigit() or not (4 <= len(pin) <= 6):
        raise ValueError("PIN — 4–6 цифр")


def create_user(session: Session, *, name: str, telegram_id, role: str, pin: str) -> User:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажите имя")
    if role not in ("cashier", "admin"):
        raise ValueError("Роль должна быть cashier или admin")
    try:
        tg_id = int(telegram_id)
    except (TypeError, ValueError):
        raise ValueError("Telegram ID — число")
    _validate_pin(pin)
    user = User(telegram_id=tg_id, name=name, role=role,
                pin_hash=hash_pin(pin), is_active=True)
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ValueError("Пользователь с таким Telegram ID уже есть")
    return user


def set_pin(session: Session, user_id: int, pin: str) -> None:
    _validate_pin(pin)
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    user.pin_hash = hash_pin(pin)
    session.commit()


def set_active(session: Session, user_id: int, active: bool) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    if not active and user.role == "admin":
        other_admins = session.scalar(
            select(func.count(User.id)).where(
                User.role == "admin", User.is_active, User.id != user_id)
        )
        if not other_admins:
            raise ValueError("Нельзя отключить последнего администратора")
    user.is_active = active
    session.commit()


def active_users(session: Session) -> list[User]:
    return list(session.scalars(
        select(User).where(User.is_active).order_by(User.name)
    ).all())


def admin_telegram_ids(session: Session) -> list[int]:
    """Telegram ID активных админов — получатели уведомлений и бэкапов."""
    return list(session.scalars(
        select(User.telegram_id).where(User.role == "admin", User.is_active)
    ).all())


def authenticate(session: Session, *, user_id: int, pin: str) -> User | None:
    user = session.get(User, user_id)
    if user is None or not user.is_active or not user.pin_hash:
        return None
    if not verify_pin(pin, user.pin_hash):
        return None
    return user


def user_from_init_data(session: Session, init_data: str, bot_token: str) -> User | None:
    data = validate_init_data(init_data, bot_token)
    if data is None:
        return None
    raw_user = data.get("user")
    if not raw_user:
        return None
    try:
        telegram_id = int(json.loads(raw_user)["id"])
    except (ValueError, KeyError, TypeError):
        return None
    return session.scalars(
        select(User).where(User.telegram_id == telegram_id, User.is_active)
    ).first()
