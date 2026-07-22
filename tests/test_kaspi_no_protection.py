import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.kaspi import service as kaspi_service
from app.models import KaspiSettings


def _session(protection: bool, token: str | None):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    s.add(KaspiSettings(id=1, terminal_url="http://192.168.0.100:8080",
                        cashier_name="Kashier1", access_token=token,
                        protection_enabled=protection))
    s.commit()
    return s


def test_pay_without_protection_skips_registration(monkeypatch):
    async def fake_run_payment(client, total_tiyn, **kw):
        return kaspi_service.PaymentResult(status="success", terminal_method="qr")

    monkeypatch.setattr(kaspi_service, "run_payment", fake_run_payment)
    with _session(protection=False, token=None) as s:
        result = asyncio.run(kaspi_service.pay(s, 10000))
    assert result.status == "success"


def test_pay_with_protection_requires_token():
    with _session(protection=True, token=None) as s:
        with pytest.raises(ValueError):
            asyncio.run(kaspi_service.pay(s, 10000))
