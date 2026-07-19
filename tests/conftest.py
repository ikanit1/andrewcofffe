import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base, enable_sqlite_fk


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")  # in-memory
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
