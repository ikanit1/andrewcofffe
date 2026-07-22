import asyncio
import os
import sqlite3
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.auth import hash_pin
from app.models import User
from app.services import backup_service as bs


def _file_engine(tmp_path):
    db = tmp_path / "source.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
        conn.execute(text("INSERT INTO t (v) VALUES ('alpha'), ('beta')"))
    return engine


def test_make_local_backup_copies_data(tmp_path):
    engine = _file_engine(tmp_path)
    dest_dir = tmp_path / "backups"
    path = bs.make_local_backup(engine=engine, backups_dir=dest_dir, keep_days=14)
    assert path.exists()
    con = sqlite3.connect(path)
    rows = con.execute("SELECT v FROM t ORDER BY id").fetchall()
    con.close()
    assert [r[0] for r in rows] == ["alpha", "beta"]


def test_make_local_backup_rotation(tmp_path):
    engine = _file_engine(tmp_path)
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    old = dest_dir / "pos-20000101-000000.db"
    old.write_bytes(b"old")
    old_time = time.time() - 40 * 86400
    os.utime(old, (old_time, old_time))
    bs.make_local_backup(engine=engine, backups_dir=dest_dir, keep_days=14)
    assert not old.exists()               # старше keep_days — удалён
    assert list(dest_dir.glob("pos-*.db"))  # свежий снимок остался


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_document(self, chat_id, document, caption=None):
        self.sent.append((chat_id, caption))


def _seed_admins(engine, ids):
    from app.db import Base
    Base.metadata.create_all(engine)
    Sm = sessionmaker(bind=engine)
    with Sm() as s:
        for tid in ids:
            s.add(User(telegram_id=tid, name=f"A{tid}", role="admin",
                       is_active=True, pin_hash=hash_pin("1234")))
        s.commit()
    return Sm


def test_send_backup_to_admins_counts_deliveries(tmp_path):
    engine = _file_engine(tmp_path)
    Sm = _seed_admins(engine, [10, 20])
    bot = _FakeBot()
    f = tmp_path / "pos-x.db"
    f.write_bytes(b"db")
    with Sm() as s:
        n = asyncio.run(bs.send_backup_to_admins(bot, f, s, caption="c"))
    assert n == 2
    assert {c for c, _ in bot.sent} == {10, 20}


def test_run_backup_once_with_bot(tmp_path):
    engine = _file_engine(tmp_path)
    Sm = _seed_admins(engine, [10, 20])
    bot = _FakeBot()
    result = asyncio.run(bs.run_backup_once(
        engine=engine, backups_dir=tmp_path / "backups",
        session_factory=Sm, bot=bot))
    assert result.path.exists()
    assert result.delivered_count == 2
    assert result.error is None
