"""Операции обслуживания: сжатие базы, журнал WAL, чистка копий и архив журнала."""
import os
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from app.services import maintenance_service as ms


def _engine(tmp_path: Path, *, wal: bool = True):
    """Движок на файле: размеры файлов на базе в памяти проверить нечем."""
    engine = create_engine(f"sqlite:///{tmp_path / 'pos.db'}")
    with engine.begin() as conn:
        if wal:
            conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, payload TEXT)"))
    return engine


def _fill(engine, rows: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO t (payload) SELECT :p FROM "
                          "(WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL "
                          "SELECT x+1 FROM c WHERE x < :n) SELECT x FROM c)"),
                     {"p": "x" * 400, "n": rows})


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


# ---------- VACUUM ----------

def test_vacuum_frees_space_after_delete(tmp_path):
    engine = _engine(tmp_path, wal=False)
    _fill(engine, 3000)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM t"))
    before = _size(tmp_path / "pos.db")

    result = ms.vacuum(engine=engine)

    assert result.ok
    assert _size(tmp_path / "pos.db") < before
    assert result.freed_bytes > 0
    assert "освободилось" in result.message


def test_vacuum_on_clean_base_reports_nothing_freed(tmp_path):
    engine = _engine(tmp_path, wal=False)

    result = ms.vacuum(engine=engine)

    assert result.ok
    assert result.freed_bytes == 0
    assert "и не было" in result.message


def test_vacuum_survives_broken_engine(tmp_path):
    """Сломанный движок даёт понятный отказ, а не исключение на весь экран."""
    engine = create_engine(f"sqlite:///{tmp_path / 'missing' / 'pos.db'}")

    result = ms.vacuum(engine=engine)

    assert not result.ok
    assert result.detail


# ---------- WAL ----------

def test_wal_checkpoint_shrinks_journal(tmp_path):
    engine = _engine(tmp_path)
    _fill(engine, 3000)
    wal = tmp_path / "pos.db-wal"
    assert _size(wal) > 0, "журнал должен был вырасти до контрольной точки"

    result = ms.wal_checkpoint(engine=engine)

    assert result.ok
    assert _size(wal) == 0
    assert result.freed_bytes > 0


def test_wal_checkpoint_on_base_without_wal(tmp_path):
    engine = _engine(tmp_path, wal=False)

    result = ms.wal_checkpoint(engine=engine)

    assert result.ok
    assert result.freed_bytes == 0


# ---------- целостность и статистика ----------

def test_integrity_check_passes_on_healthy_base(tmp_path):
    engine = _engine(tmp_path)
    _fill(engine, 50)

    result = ms.integrity_check(engine=engine)

    assert result.ok
    assert "в порядке" in result.message


def test_integrity_check_finds_orphan_reference(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pos.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE child (id INTEGER PRIMARY KEY, "
                          "parent_id INTEGER REFERENCES parent(id))"))
        # Внешние ключи по умолчанию выключены — строка-сирота записывается молча,
        # и находит её именно проверка целостности.
        conn.execute(text("INSERT INTO child (parent_id) VALUES (999)"))

    result = ms.integrity_check(engine=engine)

    assert not result.ok
    assert "child" in result.detail


def test_analyze_runs(tmp_path):
    engine = _engine(tmp_path)
    _fill(engine, 100)

    assert ms.analyze(engine=engine).ok


# ---------- журнал ----------

def test_archive_log_moves_file_and_starts_empty(tmp_path):
    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "server.log"
    log.write_text("запуск сервера\nошибка\n", encoding="utf-8")

    result = ms.archive_log(root=tmp_path, now=datetime(2026, 7, 29, 21, 30, 15))

    assert result.ok
    assert log.exists() and log.read_text(encoding="utf-8") == ""
    archived = tmp_path / "logs" / "server-20260729-213015.log"
    assert archived.read_text(encoding="utf-8").startswith("запуск сервера")


def test_archive_log_without_file(tmp_path):
    result = ms.archive_log(root=tmp_path)

    assert not result.ok
    assert "ни разу не запускался" in result.message


# ---------- копии базы ----------

def _backup(directory: Path, name: str, *, days_old: float) -> Path:
    path = directory / name
    path.write_bytes(b"x" * 1024)
    stamp = time.time() - days_old * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_cleanup_backups_removes_old_and_keeps_fresh(tmp_path):
    old = _backup(tmp_path, "pos-20260101-030000.db", days_old=30)
    fresh = _backup(tmp_path, "pos-20260728-030000.db", days_old=1)

    result = ms.cleanup_backups(keep_days=14, backups_dir=tmp_path)

    assert result.ok
    assert not old.exists()
    assert fresh.exists()
    assert result.freed_bytes == 1024


def test_cleanup_backups_never_touches_manual_copies(tmp_path):
    """Копию перед обновлением делают руками — она и есть точка отката."""
    manual = _backup(tmp_path, "pos-before-update.db", days_old=90)

    result = ms.cleanup_backups(keep_days=14, backups_dir=tmp_path)

    assert manual.exists()
    assert "ручных копий сохранено: 1" in result.detail


def test_cleanup_backups_on_empty_directory(tmp_path):
    result = ms.cleanup_backups(keep_days=14, backups_dir=tmp_path)

    assert result.ok
    assert result.freed_bytes == 0
    assert "Удалять нечего" in result.message
