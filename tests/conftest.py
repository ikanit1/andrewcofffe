import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base, enable_sqlite_fk


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """Счётчик попыток живёт в памяти процесса — между тестами его надо чистить."""
    from app.services.login_throttle import throttle

    throttle.reset_all()
    yield
    throttle.reset_all()


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")  # in-memory
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
