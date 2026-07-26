import pytest

from app.services.login_throttle import LockedOut, LoginThrottle


def _throttle():
    return LoginThrottle(max_attempts=3, lockout_seconds=60)


def test_allows_attempts_below_limit():
    t = _throttle()
    for _ in range(2):
        t.check("user:1", now=0.0)
        t.record_failure("user:1", now=0.0)
    t.check("user:1", now=0.0)  # третья попытка ещё разрешена


def test_locks_after_max_failures():
    t = _throttle()
    for _ in range(3):
        t.record_failure("user:1", now=0.0)
    with pytest.raises(LockedOut) as e:
        t.check("user:1", now=0.0)
    assert e.value.retry_after_seconds == 60


def test_success_clears_failures():
    t = _throttle()
    for _ in range(3):
        t.record_failure("user:1", now=0.0)
    t.record_success("user:1")
    t.check("user:1", now=0.0)  # блокировки больше нет


def test_lockout_expires_after_window():
    t = _throttle()
    for _ in range(3):
        t.record_failure("user:1", now=0.0)
    with pytest.raises(LockedOut):
        t.check("user:1", now=59.0)
    t.check("user:1", now=60.0)  # окно прошло — попытка снова разрешена


def test_failure_after_expiry_locks_again_immediately():
    """После исчерпания лимита каждая новая ошибка стоит целого окна:
    перебор замедляется до одной попытки в минуту."""
    t = _throttle()
    for _ in range(3):
        t.record_failure("user:1", now=0.0)
    t.check("user:1", now=60.0)
    t.record_failure("user:1", now=60.0)
    with pytest.raises(LockedOut):
        t.check("user:1", now=61.0)


def test_retry_after_counts_down():
    t = _throttle()
    for _ in range(3):
        t.record_failure("user:1", now=0.0)
    with pytest.raises(LockedOut) as e:
        t.check("user:1", now=45.0)
    assert e.value.retry_after_seconds == 15


def test_keys_are_independent():
    t = _throttle()
    for _ in range(3):
        t.record_failure("user:1", now=0.0)
    t.check("user:2", now=0.0)  # блокировка одного не задевает другого
