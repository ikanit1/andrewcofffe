from datetime import datetime

from sqlalchemy.orm import Session

from app.models import KaspiSettings


def get_settings(session: Session) -> KaspiSettings:
    """Возвращает единственную строку настроек, создавая её при первом обращении."""
    s = session.get(KaspiSettings, 1)
    if s is None:
        s = KaspiSettings(id=1)
        session.add(s)
        session.commit()
    return s


def save_config(session: Session, *, terminal_url: str, cashier_name: str,
                protection_enabled: bool = True) -> None:
    s = get_settings(session)
    s.terminal_url = terminal_url
    s.cashier_name = cashier_name
    s.protection_enabled = protection_enabled
    session.commit()


def save_tokens(session: Session, *, access_token: str, refresh_token: str,
                expires_at: datetime | None) -> None:
    s = get_settings(session)
    s.access_token = access_token
    s.refresh_token = refresh_token
    s.token_expires_at = expires_at
    session.commit()


def save_terminal_id(session: Session, *, terminal_id: str) -> None:
    s = get_settings(session)
    s.terminal_id = terminal_id
    session.commit()
