import asyncio

import pytest

from app.models import Shift, User
from app.services import updater


def _runner(results):
    """Подменяет запуск внешних команд: список (код возврата, вывод) по порядку."""
    calls = []

    async def run(cmd, cwd=None):
        calls.append(list(cmd))
        return results[len(calls) - 1] if len(calls) <= len(results) else (0, "")

    run.calls = calls
    return run


def _cashier(session):
    u = User(telegram_id=1, name="Кассир", role="cashier", is_active=True)
    session.add(u)
    session.commit()
    return u


def test_supervised_flag_read_from_env(monkeypatch):
    monkeypatch.delenv("COFFEEPOS_SUPERVISED", raising=False)
    assert updater.is_supervised() is False
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")
    assert updater.is_supervised() is True


def test_refuses_while_shift_is_open(session, tmp_path):
    """Перезапуск посреди смены оборвал бы работу кассира на полуслове."""
    c = _cashier(session)
    session.add(Shift(cashier_id=c.id, status="open", opening_cash_tiyn=0))
    session.commit()

    run = _runner([])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is False
    assert "смен" in res.message.lower()
    assert run.calls == []  # ничего не запускали


def test_refuses_on_zip_install_without_git(session, tmp_path):
    run = _runner([])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is False
    assert "zip" in res.message.lower() or "архив" in res.message.lower()
    assert run.calls == []


def test_pulls_and_installs_then_schedules_restart(session, tmp_path, monkeypatch):
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")
    (tmp_path / ".git").mkdir()
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

    run = _runner([(0, "master"), (0, "Updating abc..def"), (0, "installed")])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is True
    assert res.restart_scheduled is True
    assert run.calls[0] == ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    # Remote и ветка указаны явно: на кассах без tracking голый pull падал
    assert run.calls[1] == ["git", "pull", "--ff-only", "origin", "master"]
    assert any("pip" in part for part in run.calls[2])


def test_reports_git_failure_without_restarting(session, tmp_path, monkeypatch):
    """Неудачный git pull не должен приводить к перезапуску: код остался прежним,
    а рестарт только оборвал бы работу без всякой пользы."""
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")
    (tmp_path / ".git").mkdir()

    run = _runner([(0, "master"), (1, "error: local changes would be overwritten")])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is False
    assert res.restart_scheduled is False
    assert "local changes" in res.log
    assert len(run.calls) == 2  # ветка и pull; до pip не дошли


def test_updates_but_asks_for_manual_restart_when_unsupervised(session, tmp_path, monkeypatch):
    monkeypatch.delenv("COFFEEPOS_SUPERVISED", raising=False)
    (tmp_path / ".git").mkdir()
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

    run = _runner([(0, "master"), (0, "ok"), (0, "ok")])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is True
    assert res.restart_scheduled is False
    assert "вручную" in res.message.lower() or "start.ps1" in res.message


def test_backs_up_database_before_pulling(session, tmp_path, monkeypatch):
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")
    (tmp_path / ".git").mkdir()
    db = tmp_path / "pos.db"
    db.write_bytes("SQLite format 3\x00данные".encode("utf-8"))

    run = _runner([(0, "master"), (0, "ok"), (0, "ok")])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is True
    copies = list((tmp_path / "backups").glob("pos-before-update-*.db"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == db.read_bytes()


def test_pulls_from_current_branch_not_only_master(session, tmp_path, monkeypatch):
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")
    (tmp_path / ".git").mkdir()

    run = _runner([(0, "stable"), (0, "ok")])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is True
    assert run.calls[1] == ["git", "pull", "--ff-only", "origin", "stable"]
    assert "stable" in " ".join(res.steps)


def test_refuses_on_detached_head_with_a_way_out(session, tmp_path, monkeypatch):
    """В detached HEAD тянуть некуда — владельцу нужно сказать, что делать."""
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")
    (tmp_path / ".git").mkdir()

    run = _runner([(0, "HEAD")])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is False
    assert "git checkout master" in res.message
    assert len(run.calls) == 1


def test_diverged_history_gets_a_readable_hint(session, tmp_path, monkeypatch):
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")
    (tmp_path / ".git").mkdir()

    run = _runner([(0, "master"), (1, "fatal: Not possible to fast-forward, diverged")])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))

    assert res.ok is False
    assert "свои правки" in res.message


def test_request_restart_leaves_marker_for_launcher(tmp_path):
    """Маркер отличает выход ради обновления от Ctrl+C.

    Без него start.ps1 пришлось бы зациклить безусловно, и остановить кассу
    с клавиатуры стало бы нельзя: цикл поднимал бы сервер снова.
    """
    updater.request_restart(root=tmp_path)
    assert (tmp_path / updater.RESTART_MARKER_NAME).exists()


def test_consume_restart_marker_reports_and_removes_it(tmp_path):
    updater.request_restart(root=tmp_path)
    assert updater.consume_restart_marker(root=tmp_path) is True
    assert not (tmp_path / updater.RESTART_MARKER_NAME).exists()


def test_consume_restart_marker_is_false_without_it(tmp_path):
    assert updater.consume_restart_marker(root=tmp_path) is False


def test_restart_marker_is_not_left_over_between_runs(tmp_path):
    """Забытый маркер заставил бы кассу перезапуститься на пустом месте."""
    updater.request_restart(root=tmp_path)
    updater.consume_restart_marker(root=tmp_path)
    assert updater.consume_restart_marker(root=tmp_path) is False


def test_supervised_run_schedules_restart_and_marks_it(session, tmp_path, monkeypatch):
    """Под start.ps1 и под автозапуском одинаково: приложение просит перезапуск само."""
    monkeypatch.setenv("COFFEEPOS_SUPERVISED", "1")
    (tmp_path / ".git").mkdir()
    run = _runner([(0, "ok"), (0, "ok")])
    res = asyncio.run(updater.apply_update(session, runner=run, root=tmp_path))
    assert res.ok is True and res.restart_scheduled is True
    assert "вручную" not in res.message.lower()
