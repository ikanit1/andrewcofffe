"""Реестр фоновых задач и момент старта процесса.

create_app держит бота, бэкапы и дневную сводку в локальных переменных lifespan:
снаружи узнать, жива ли задача, было нельзя, а «упала» и «выключена в .env»
выглядели одинаково — задачи просто не было. Экран «Сервер» спрашивает состояние
здесь и различает три случая: работает, выключена, упала с ошибкой.

Состояние — обычный словарь на уровне модуля. Касса живёт одним процессом с одним
event loop, поэтому передавать экземпляр реестра через полприложения ради трёх
задач незачем. Плата за это — общая на весь процесс память, которую тесты чистят
через reset().
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime

from app.models.inventory import utcnow


@dataclass(frozen=True)
class TaskState:
    name: str
    enabled: bool
    running: bool
    error: str


# имя -> (включена ли в настройках, объект задачи или None)
_tasks: dict[str, tuple[bool, object | None]] = {}
_started_at: datetime | None = None


def mark_started(now: datetime | None = None) -> None:
    """Отметка старта процесса; из неё считается аптайм на экране «Сервер»."""
    global _started_at
    _started_at = now if now is not None else utcnow()


def started_at() -> datetime | None:
    return _started_at


def uptime_seconds(now: datetime | None = None) -> float | None:
    if _started_at is None:
        return None
    return ((now if now is not None else utcnow()) - _started_at).total_seconds()


def register_task(name: str, task, *, enabled: bool = True) -> None:
    _tasks[name] = (enabled, task)


def register_disabled(name: str) -> None:
    """Задача не запускалась: выключена в .env или нет токена.

    Регистрировать её всё равно нужно — иначе на экране не будет строки, и
    владелец решит, что сводка приходит, просто он её не заметил.
    """
    _tasks[name] = (False, None)


def task_states() -> list[TaskState]:
    """Состояние считается на каждый вызов: задача могла упасть минуту назад."""
    return [_state(name, enabled, task) for name, (enabled, task) in _tasks.items()]


def reset() -> None:
    global _started_at
    _tasks.clear()
    _started_at = None


def _state(name: str, enabled: bool, task) -> TaskState:
    if not enabled or task is None:
        return TaskState(name=name, enabled=enabled, running=False, error="")
    if not task.done():
        return TaskState(name=name, enabled=True, running=True, error="")
    if task.cancelled():
        # Отмена — штатное завершение при остановке кассы, а не поломка.
        return TaskState(name=name, enabled=True, running=False, error="")
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        # Задачу отменили между done() и exception(). CancelledError — потомок
        # BaseException, без явного перехвата он ушёл бы наружу и уронил экран.
        return TaskState(name=name, enabled=True, running=False, error="")
    return TaskState(name=name, enabled=True, running=False,
                     error=repr(exc) if exc is not None else "")
