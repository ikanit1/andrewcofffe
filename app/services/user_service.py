import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import validate_init_data, verify_pin
from app.models import User


def active_users(session: Session) -> list[User]:
    return list(session.scalars(
        select(User).where(User.is_active).order_by(User.name)
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
