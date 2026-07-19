import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")  # in-memory
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
