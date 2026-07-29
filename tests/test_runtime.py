import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services import runtime


@pytest.fixture(autouse=True)
def _clean_registry():
    """Реестр общий на процесс — иначе задачи одного теста видны в следующем."""
    runtime.reset()
    yield
    runtime.reset()


class _FakeTask:
    """Реестру от задачи нужны только done/cancelled/exception.

    Настоящий asyncio.Task в состоянии «работает» вне живого event loop не
    удержать: на закрытии цикла он становится отменённым.
    """

    def __init__(self, *, done=False, cancelled=False, exc=None, raises=None):
        self._done = done
        self._cancelled = cancelled
        self._exc = exc
        self._raises = raises

    def done(self):
        return self._done

    def cancelled(self):
        return self._cancelled

    def exception(self):
        if self._raises is not None:
            raise self._raises
        return self._exc

    def finish(self, exc=None):
        self._done = True
        self._exc = exc


def _finished_task(coro_factory):
    """Прогоняет корутину до конца и отдаёт саму задачу — уже завершённую."""

    async def main():
        task = asyncio.create_task(coro_factory())
        await asyncio.gather(task, return_exceptions=True)
        return task

    return asyncio.run(main())


def _cancelled_task():
    async def main():
        task = asyncio.create_task(asyncio.sleep(3600))
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return task

    return asyncio.run(main())


def test_running_task_is_reported_as_alive():
    runtime.register_task("Бэкапы", _FakeTask())

    (state,) = runtime.task_states()
    assert state == runtime.TaskState(name="Бэкапы", enabled=True, running=True, error="")


def test_disabled_task_is_off_not_broken():
    runtime.register_disabled("Telegram-бот")

    (state,) = runtime.task_states()
    assert state.enabled is False
    assert state.running is False
    assert state.error == ""


def test_task_registered_as_disabled_keeps_its_flag():
    runtime.register_task("Сводка за день", _FakeTask(), enabled=False)

    (state,) = runtime.task_states()
    assert (state.enabled, state.running) == (False, False)


def test_crashed_task_reports_the_exception():
    async def boom():
        raise RuntimeError("нет связи с Telegram")

    runtime.register_task("Telegram-бот", _finished_task(boom))

    (state,) = runtime.task_states()
    assert state.enabled is True
    assert state.running is False
    assert "RuntimeError" in state.error and "Telegram" in state.error


def test_cancelled_task_is_not_an_error():
    """Отмена — это штатная остановка кассы, а не поломка задачи."""
    runtime.register_task("Бэкапы", _cancelled_task())

    (state,) = runtime.task_states()
    assert state.running is False
    assert state.error == ""


def test_exception_of_cancelled_task_does_not_leak_out():
    """Гонка: задачу отменили между done() и exception().

    CancelledError — потомок BaseException, без перехвата он ушёл бы наружу
    и уронил бы весь экран «Сервер» вместо строки об одной задаче.
    """
    runtime.register_task("Бэкапы", _FakeTask(done=True, raises=asyncio.CancelledError()))

    (state,) = runtime.task_states()
    assert state.running is False
    assert state.error == ""


def test_finished_task_without_exception_is_not_an_error():
    async def quiet():
        return None

    runtime.register_task("Сводка за день", _finished_task(quiet))

    (state,) = runtime.task_states()
    assert state.running is False
    assert state.error == ""


def test_states_keep_registration_order():
    runtime.register_disabled("Telegram-бот")
    runtime.register_task("Бэкапы", _FakeTask())
    runtime.register_task("Сводка за день", _FakeTask())

    assert [s.name for s in runtime.task_states()] == [
        "Telegram-бот", "Бэкапы", "Сводка за день"]


def test_state_is_recomputed_on_every_call():
    """Задача могла упасть уже после запуска — экран должен это увидеть."""
    task = _FakeTask()
    runtime.register_task("Бэкапы", task)
    assert runtime.task_states()[0].running is True

    task.finish(ValueError("диск полон"))
    assert runtime.task_states()[0].error == repr(ValueError("диск полон"))


def test_uptime_counts_from_mark_started():
    start = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)
    runtime.mark_started(start)

    assert runtime.started_at() == start
    assert runtime.uptime_seconds(start + timedelta(hours=2)) == 2 * 3600


def test_started_at_is_aware_utc():
    runtime.mark_started()

    started = runtime.started_at()
    assert started is not None and started.tzinfo is not None
    assert started.utcoffset() == timedelta(0)


def test_uptime_is_unknown_before_start():
    assert runtime.started_at() is None
    assert runtime.uptime_seconds() is None


def test_reset_clears_tasks_and_start_time():
    runtime.mark_started()
    runtime.register_task("Бэкапы", _FakeTask())

    runtime.reset()

    assert runtime.task_states() == []
    assert runtime.started_at() is None
    assert runtime.uptime_seconds() is None
