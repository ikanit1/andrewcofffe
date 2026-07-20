from app.ui.guard import current_user_id, is_admin


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
