import os
import sqlite3
import time
from pathlib import Path

from sqlalchemy import create_engine, text

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
