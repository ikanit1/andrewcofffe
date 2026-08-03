"""Восстановление базы из копии: проверка файла и подмена рабочей базы."""
import sqlite3

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import Base, enable_sqlite_fk
from app.models import Category, Product, Shift, User
from app.services import backup_service as bs


def _make_db(path, *, users=1, products=1) -> None:
    """Готовая база кассы на диске — из неё и делают копии."""
    engine = create_engine(f"sqlite:///{path}")
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for n in range(users):
            s.add(User(telegram_id=100 + n, name=f"Кассир {n}", role="admin"))
        cat = Category(name="Кофе")
        s.add(cat)
        s.flush()
        for n in range(products):
            s.add(Product(name=f"Товар {n}", category_id=cat.id, kind="retail",
                          price_tiyn=50000))
        s.commit()
    engine.dispose()


# --------------------------------------------------------------------------
# проверка файла
# --------------------------------------------------------------------------


def test_inspect_accepts_real_database_and_counts_rows(tmp_path):
    db = tmp_path / "pos.db"
    _make_db(db, users=2, products=3)

    check = bs.inspect_backup(db)

    assert check.ok and check.problems == ()
    counts = dict(check.counts)
    assert counts["Пользователи"] == 2
    assert counts["Товары"] == 3
    assert counts["Чеки"] == 0
    assert check.size_bytes > 0 and check.created_at is not None


def test_inspect_rejects_missing_empty_and_foreign_files(tmp_path):
    assert bs.inspect_backup(tmp_path / "нет.db").problems == ("Файл не найден",)

    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert bs.inspect_backup(empty).problems == ("Файл пустой",)

    # Валидная база SQLite, но не от кассы
    foreign = tmp_path / "foreign.db"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    check = bs.inspect_backup(foreign)
    assert not check.ok
    assert "не база кассы" in check.problems[0]


def test_inspect_rejects_garbage_and_database_without_users(tmp_path):
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"\x00\x01\x02 not a database at all")
    assert not bs.inspect_backup(garbage).ok

    empty_users = tmp_path / "no-users.db"
    _make_db(empty_users, users=0)
    check = bs.inspect_backup(empty_users)
    assert not check.ok
    assert "нет ни одного пользователя" in check.problems[0]


# --------------------------------------------------------------------------
# подмена базы
# --------------------------------------------------------------------------


def _live_engine(path):
    engine = create_engine(f"sqlite:///{path}")
    enable_sqlite_fk(engine)
    return engine


def test_restore_replaces_database_and_keeps_previous_copy(tmp_path, monkeypatch):
    working = tmp_path / "pos.db"
    _make_db(working, users=1, products=1)
    incoming = tmp_path / "backup.db"
    _make_db(incoming, users=2, products=7)

    engine = _live_engine(working)
    monkeypatch.setattr("app.db.init_db", lambda: None)   # схема уже актуальна

    result = bs.restore_from_file(incoming, engine=engine)

    assert result.ok, result.message
    assert result.previous_copy.startswith("pos-before-restore-")
    assert (tmp_path / "backups" / result.previous_copy).exists()

    # В рабочей базе теперь данные из копии
    check = bs.inspect_backup(working)
    assert dict(check.counts)["Товары"] == 7
    # А прежняя база сохранена целиком
    assert dict(bs.inspect_backup(tmp_path / "backups" / result.previous_copy)
               .counts)["Товары"] == 1


def test_restore_removes_wal_sidecars(tmp_path, monkeypatch):
    """Журнал WAL от прежней базы применился бы поверх новой и смешал бы данные."""
    working = tmp_path / "pos.db"
    _make_db(working, products=1)
    incoming = tmp_path / "backup.db"
    _make_db(incoming, products=5)
    for sidecar in ("pos.db-wal", "pos.db-shm"):
        (tmp_path / sidecar).write_bytes(b"stale journal")

    engine = _live_engine(working)
    monkeypatch.setattr("app.db.init_db", lambda: None)

    assert bs.restore_from_file(incoming, engine=engine).ok
    assert not (tmp_path / "pos.db-wal").exists()
    assert not (tmp_path / "pos.db-shm").exists()


def test_restore_refuses_broken_file_and_leaves_database_untouched(tmp_path):
    working = tmp_path / "pos.db"
    _make_db(working, products=3)
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database")

    engine = _live_engine(working)
    result = bs.restore_from_file(broken, engine=engine)

    assert not result.ok
    assert "не прошёл проверку" in result.message
    assert dict(bs.inspect_backup(working).counts)["Товары"] == 3
    assert not (tmp_path / "backups").exists()   # копию зря не снимали


def test_restore_refuses_while_shift_is_open(tmp_path):
    working = tmp_path / "pos.db"
    _make_db(working, products=1)
    incoming = tmp_path / "backup.db"
    _make_db(incoming, products=9)

    engine = _live_engine(working)
    with Session(engine) as s:
        cashier = s.query(User).first()
        s.add(Shift(cashier_id=cashier.id, opening_cash_tiyn=0, status="open"))
        s.commit()

    result = bs.restore_from_file(incoming, engine=engine)

    assert not result.ok
    assert "закройте смену" in result.message
    assert dict(bs.inspect_backup(working).counts)["Товары"] == 1


def test_restore_upgrades_schema_of_old_copy(tmp_path, monkeypatch):
    """Копия могла быть снята версией, где складских колонок ещё не было."""
    working = tmp_path / "pos.db"
    _make_db(working, products=1)

    old = tmp_path / "old.db"
    _make_db(old, products=2)
    conn = sqlite3.connect(old)
    conn.execute("ALTER TABLE products DROP COLUMN stock_qty")
    conn.commit()
    conn.close()
    assert "stock_qty" not in {
        r[1] for r in sqlite3.connect(old).execute("PRAGMA table_info(products)")}

    engine = _live_engine(working)
    # init_db работает с боевым движком; в тесте подменяем на ensure_schema нашего
    from app.db import ensure_schema
    monkeypatch.setattr("app.db.init_db", lambda: ensure_schema(engine))

    result = bs.restore_from_file(old, engine=engine)

    assert result.ok, result.message
    with engine.connect() as conn:
        columns = {r[1] for r in conn.execute(text("PRAGMA table_info(products)"))}
    assert {"stock_qty", "low_stock_threshold", "cost_tiyn"} <= columns


def test_restore_rejects_non_sqlite_engine(tmp_path):
    incoming = tmp_path / "backup.db"
    _make_db(incoming)
    memory = create_engine("sqlite://")           # база в памяти — подменять нечего
    result = bs.restore_from_file(incoming, engine=memory)
    assert not result.ok
    assert "только для SQLite" in result.message


@pytest.mark.parametrize("kind", ["directory", "text"])
def test_inspect_survives_wrong_kinds_of_input(tmp_path, kind):
    if kind == "directory":
        target = tmp_path / "folder.db"
        target.mkdir()
    else:
        target = tmp_path / "notes.db"
        target.write_text("просто текст", encoding="utf-8")
    assert not bs.inspect_backup(target).ok
