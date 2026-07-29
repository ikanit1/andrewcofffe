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
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


enable_sqlite_fk(engine)


def ensure_schema(engine: Engine) -> None:
    """Идемпотентно добавляет недостающие колонки в существующие таблицы SQLite.

    У проекта нет Alembic; Base.metadata.create_all создаёт новые таблицы, но не
    изменяет уже существующие. Здесь добавляем колонки, появившиеся после того, как
    боевая pos.db была создана.

    Рассчитано на single-process запуск приложения: проверка "колонка есть?" и
    ALTER не атомарны, но одновременного старта двух процессов в этом проекте нет.
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
        "kaspi_settings": {
            "protection_enabled": "BOOLEAN NOT NULL DEFAULT 1",
        },
        "products": {
            "image": "BLOB",
            "image_mime": "VARCHAR",
            "has_image": "BOOLEAN NOT NULL DEFAULT 0",
            "inventory_policy": "VARCHAR NOT NULL DEFAULT 'track'",
        },
        "ingredients": {
            # Без REFERENCES: SQLite не умеет добавлять внешний ключ через
            # ALTER TABLE, а переливать таблицу с боевыми остатками ради этого
            # рискованнее, чем жить со ссылкой без ограничения на уровне БД.
            # Осиротевшие ссылки исключены в коде: удаление раздела сначала
            # обнуляет category_id у его позиций.
            "category_id": "INTEGER",
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
