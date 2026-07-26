import pytest

from app.auth import hash_pin
from app.models import User
from app.services import login_throttle as lt
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


def test_admin_telegram_ids_only_active_admins(session):
    _user(session, tid=10, role="admin", active=True)
    _user(session, tid=11, role="admin", active=False)
    _user(session, tid=12, role="cashier", active=True)
    assert us.admin_telegram_ids(session) == [10]


def test_create_user_and_login(session):
    u = us.create_user(session, name="Новый", telegram_id=555, role="cashier", pin="4321")
    assert u.id is not None
    assert us.authenticate(session, user_id=u.id, pin="4321") is not None


def test_create_user_duplicate_telegram_id(session):
    us.create_user(session, name="A", telegram_id=555, role="cashier", pin="1111")
    with pytest.raises(ValueError):
        us.create_user(session, name="B", telegram_id=555, role="cashier", pin="2222")


def test_create_user_bad_pin(session):
    with pytest.raises(ValueError):
        us.create_user(session, name="A", telegram_id=1, role="cashier", pin="12")


def test_set_pin_changes_login(session):
    u = _user(session, tid=7, pin="1111")
    us.set_pin(session, u.id, "9999")
    assert us.authenticate(session, user_id=u.id, pin="1111") is None
    assert us.authenticate(session, user_id=u.id, pin="9999") is not None


def test_set_active_blocks_last_admin(session):
    a = _user(session, tid=1, role="admin")
    with pytest.raises(ValueError):
        us.set_active(session, a.id, False)


def test_set_active_deactivates_cashier(session):
    c = _user(session, tid=2, role="cashier")
    us.set_active(session, c.id, False)
    assert us.authenticate(session, user_id=c.id, pin="1234") is None


def test_admin_by_pin(session):
    a = _user(session, tid=1, role="admin", pin="7777")
    _user(session, tid=2, role="cashier", pin="7777")  # тот же PIN, но не админ
    got = us.admin_by_pin(session, "7777")
    assert got is not None and got.id == a.id
    assert us.admin_by_pin(session, "0000") is None


def test_authenticate_locks_out_after_repeated_wrong_pin(session):
    u = _user(session, pin="4821")
    for _ in range(lt.MAX_ATTEMPTS):
        assert us.authenticate(session, user_id=u.id, pin="0000") is None
    with pytest.raises(lt.LockedOut):
        us.authenticate(session, user_id=u.id, pin="0000")
    # правильный пин тоже отбивается, пока идёт блокировка
    with pytest.raises(lt.LockedOut):
        us.authenticate(session, user_id=u.id, pin="4821")


def test_authenticate_success_resets_attempts(session):
    u = _user(session, pin="4821")
    for _ in range(lt.MAX_ATTEMPTS - 1):
        us.authenticate(session, user_id=u.id, pin="0000")
    assert us.authenticate(session, user_id=u.id, pin="4821") is not None
    # счётчик обнулён: снова доступен полный лимит
    for _ in range(lt.MAX_ATTEMPTS - 1):
        assert us.authenticate(session, user_id=u.id, pin="0000") is None


def test_lockout_is_per_user(session):
    a = _user(session, tid=1, pin="1111")
    b = _user(session, tid=2, pin="2222")
    for _ in range(lt.MAX_ATTEMPTS):
        us.authenticate(session, user_id=a.id, pin="0000")
    assert us.authenticate(session, user_id=b.id, pin="2222") is not None


def test_admin_by_pin_locks_out_after_repeated_guesses(session):
    _user(session, tid=1, role="admin", pin="7777")
    for _ in range(lt.MAX_ATTEMPTS):
        assert us.admin_by_pin(session, "0000") is None
    with pytest.raises(lt.LockedOut):
        us.admin_by_pin(session, "0000")


def test_admin_by_pin_success_resets_attempts(session):
    _user(session, tid=1, role="admin", pin="7777")
    for _ in range(lt.MAX_ATTEMPTS - 1):
        us.admin_by_pin(session, "0000")
    assert us.admin_by_pin(session, "7777") is not None
    for _ in range(lt.MAX_ATTEMPTS - 1):
        assert us.admin_by_pin(session, "0000") is None
