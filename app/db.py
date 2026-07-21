from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


# check_same_thread нужен только SQLite; для Postgres на этапе переезда аргумент недопустим
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def enable_sqlite_fk(engine: Engine) -> None:
    """SQLite по умолчанию не проверяет внешние ключи — включаем на каждом соединении.

    Для остальных диалектов (Postgres и т.п.) это не нужно, поэтому листенер
    регистрируется только когда движок реально работает через SQLite.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


enable_sqlite_fk(engine)


def ensure_schema(engine: Engine) -> None:
    """Идемпотентно добавляет недостающие колонки в существующие таблицы SQLite.

    У проекта нет Alembic; Base.metadata.create_all создаёт новые таблицы, но не
    изменяет уже существующие. Здесь добавляем колонки, появившиеся после того, как
    боевая pos.db была создана.
    """
    if engine.dialect.name != "sqlite":
        return
    from sqlalchemy import text

    wanted = {
        "payments": {
            "provider": "VARCHAR NOT NULL DEFAULT 'manual'",
            "terminal_method": "VARCHAR",
            "transaction_id": "VARCHAR",
        },
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            present = conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")).fetchone()
            if present is None:
                continue
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col, ddl in columns.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def init_db() -> None:
    import app.models  # noqa: F401  (регистрирует таблицы)

    Base.metadata.create_all(engine)
    ensure_schema(engine)
