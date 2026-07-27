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


@pytest.fixture(autouse=True)
def _freeze_promo_clock(monkeypatch):
    """Акции привязаны к часам, а тесты не должны зависеть от времени запуска.

    В фикстурах товар называется «Латте» и стоит 1500 тг. Без заморозки часов
    прогон между 08:30 и 11:00 подставлял бы акционные 990 тг, и проверки сумм
    падали бы через раз — ровно в утреннюю смену, когда их запускают чаще всего.
    Тесты самих акций передают время явным параметром и фикстуру не замечают.
    """
    from datetime import datetime

    from app.services import promo
    from app.timezone import ALMATY

    monkeypatch.setattr(
        promo, "now_almaty",
        lambda: datetime(2026, 7, 27, 15, 0, tzinfo=ALMATY),  # день, акции нет
    )


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")  # in-memory
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
