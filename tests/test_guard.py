from app.auth import hash_pin
from app.models import User
from app.services import user_service as us
from app.ui.guard import current_user_id, is_admin, session_user


class _FakeStorage:
    def __init__(self, data):
        self.user = data


def test_current_user_id_reads_storage():
    assert current_user_id(_FakeStorage({"user_id": 7})) == 7
    assert current_user_id(_FakeStorage({})) is None


def test_is_admin_flag():
    assert is_admin(_FakeStorage({"role": "admin"})) is True
    assert is_admin(_FakeStorage({"role": "cashier"})) is False
    assert is_admin(_FakeStorage({})) is False


def _user(session, role="cashier", active=True):
    u = User(telegram_id=1, name="Кассир", role=role, is_active=active,
             pin_hash=hash_pin("1234"))
    session.add(u)
    session.commit()
    return u


def test_session_user_returns_live_record(session):
    u = _user(session)
    got = session_user(session, _FakeStorage({"user_id": u.id, "role": "cashier"}))
    assert got is not None and got.id == u.id


def test_session_user_rejects_deactivated_user(session):
    """Уволили кассира — его открытая сессия на кассе должна перестать работать
    сразу, а не после того, как он сам нажмёт «Выход»."""
    u = _user(session)
    us.set_active(session, u.id, False)
    assert session_user(session, _FakeStorage({"user_id": u.id, "role": "cashier"})) is None


def test_session_user_rejects_stale_role_after_demotion(session):
    """Роль в сессии — снимок на момент входа. Если админа понизили,
    его текущая вкладка не должна остаться админской."""
    admin = _user(session, role="admin")
    _user2 = User(telegram_id=2, name="Второй админ", role="admin", is_active=True,
                  pin_hash=hash_pin("9999"))
    session.add(_user2)
    session.commit()

    storage = _FakeStorage({"user_id": admin.id, "role": "admin"})
    assert session_user(session, storage) is not None

    admin.role = "cashier"
    session.commit()
    assert session_user(session, storage) is None


def test_session_user_rejects_unknown_id(session):
    assert session_user(session, _FakeStorage({"user_id": 4242, "role": "admin"})) is None
    assert session_user(session, _FakeStorage({})) is None
