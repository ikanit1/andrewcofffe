import pytest

from app.auth import hash_pin
from app.models import User
from app.services import user_service as us


def _user(session, tid=42, pin="1234", role="cashier", active=True):
    u = User(telegram_id=tid, name="Кассир", role=role, is_active=active, pin_hash=hash_pin(pin))
    session.add(u)
    session.commit()
    return u


def test_active_users_for_login(session):
    _user(session, tid=1, role="cashier")
    _user(session, tid=2, role="admin")
    _user(session, tid=3, active=False)
    users = us.active_users(session)
    assert {u.telegram_id for u in users} == {1, 2}


def test_authenticate_pin_ok(session):
    u = _user(session, pin="4821")
    got = us.authenticate(session, user_id=u.id, pin="4821")
    assert got is not None
    assert got.id == u.id


def test_authenticate_wrong_pin(session):
    u = _user(session, pin="4821")
    assert us.authenticate(session, user_id=u.id, pin="0000") is None


def test_authenticate_inactive_rejected(session):
    u = _user(session, pin="1111", active=False)
    assert us.authenticate(session, user_id=u.id, pin="1111") is None


def test_authenticate_no_pin_set(session):
    u = User(telegram_id=9, name="Без пина", role="cashier", is_active=True)
    session.add(u)
    session.commit()
    assert us.authenticate(session, user_id=u.id, pin="1234") is None


def test_user_from_init_data_valid(session):
    import hashlib
    import hmac
    from urllib.parse import urlencode
    token = "1234567890:TEST-TOKEN"
    u = _user(session, tid=777)
    params = {"auth_date": "1752900000", "user": '{"id":777}'}
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    init = urlencode({**params, "hash": h})
    got = us.user_from_init_data(session, init, token)
    assert got is not None and got.telegram_id == 777


def test_user_from_init_data_bad_signature(session):
    _user(session, tid=777)
    assert us.user_from_init_data(session, "auth_date=1&user=%7B%22id%22%3A777%7D&hash=deadbeef", "tok") is None
