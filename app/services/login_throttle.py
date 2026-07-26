"""Серверный лимит попыток ввода пин-кода.

Счётчик в памяти процесса: касса — один процесс, отдельная таблица тут не нужна,
а перезапуск сервера как способ обойти блокировку атакующему недоступен.
"""
import time

MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60


class LockedOut(Exception):
    """Попытки исчерпаны, вход временно заблокирован."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Слишком много попыток, подождите {retry_after_seconds} с")


class LoginThrottle:
    def __init__(self, max_attempts: int = MAX_ATTEMPTS, lockout_seconds: int = LOCKOUT_SECONDS):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._failures: dict[str, tuple[int, float]] = {}  # key -> (счётчик, время последней ошибки)

    def check(self, key: str, *, now: float | None = None) -> None:
        """Бросает LockedOut, если по ключу сейчас блокировка."""
        now = time.monotonic() if now is None else now
        count, last = self._failures.get(key, (0, 0.0))
        if count < self.max_attempts:
            return
        remaining = self.lockout_seconds - (now - last)
        if remaining > 0:
            raise LockedOut(int(remaining))

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        count, _ = self._failures.get(key, (0, 0.0))
        self._failures[key] = (count + 1, now)

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)

    def reset_all(self) -> None:
        self._failures.clear()


throttle = LoginThrottle()
