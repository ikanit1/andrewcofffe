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


def init_db() -> None:
    import app.models  # noqa: F401  (регистрирует таблицы)

    Base.metadata.create_all(engine)
