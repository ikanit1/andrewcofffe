import asyncio

import pytest

from app.kaspi import service as ks


def test_amount_to_tenge_whole():
    assert ks.amount_to_tenge(150000) == 1500


def test_amount_to_tenge_rejects_fraction():
    with pytest.raises(ValueError):
        ks.amount_to_tenge(150050)


class _FakeClient:
    """Фейковый клиент: отдаёт заранее заготовленные ответы status по очереди."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.payment_calls = []

    async def payment(self, amount, *, owncheque=False):
        self.payment_calls.append(amount)
        return {"processId": "p1", "status": "wait"}

    async def status(self, process_id):
        return self._statuses.pop(0)

    async def actualize(self, process_id):
        return {"status": "fail", "message": "Операция отменена"}


def test_poll_returns_success():
    fake = _FakeClient([
        {"status": "wait"},
        {"status": "wait"},
        {"status": "success", "transactionId": "504711333", "chequeInfo": {"method": "qr"}},
    ])
    data = asyncio.run(ks._poll_until_final(fake, "p1", poll_interval=0, max_polls=10))
    assert data["status"] == "success"
    assert data["transactionId"] == "504711333"


def test_poll_returns_fail():
    fake = _FakeClient([{"status": "wait"}, {"status": "fail", "message": "Отмена"}])
    data = asyncio.run(ks._poll_until_final(fake, "p1", poll_interval=0, max_polls=10))
    assert data["status"] == "fail"


def test_poll_timeout_returns_unknown():
    fake = _FakeClient([{"status": "wait"}, {"status": "wait"}, {"status": "wait"}])
    data = asyncio.run(ks._poll_until_final(fake, "p1", poll_interval=0, max_polls=3))
    assert data["status"] == "unknown"


def test_run_payment_success_maps_result():
    fake = _FakeClient([
        {"status": "wait"},
        {"status": "success", "transactionId": "R123", "chequeInfo": {"method": "card"}},
    ])
    result = asyncio.run(ks.run_payment(fake, 150000, poll_interval=0, max_polls=10))
    assert result.status == "success"
    assert result.terminal_method == "card"
    assert result.transaction_id == "R123"
    assert fake.payment_calls == [1500]


def test_run_payment_fraction_rejected():
    fake = _FakeClient([])
    with pytest.raises(ValueError):
        asyncio.run(ks.run_payment(fake, 150050, poll_interval=0, max_polls=10))


def test_run_payment_fail_maps_message():
    fake = _FakeClient([{"status": "fail", "message": "Покупатель отменил"}])
    result = asyncio.run(ks.run_payment(fake, 150000, poll_interval=0, max_polls=10))
    assert result.status == "fail"
    assert "отменил" in result.message


def test_run_payment_unknown_calls_actualize():
    fake = _FakeClient([{"status": "wait"}, {"status": "wait"}])
    result = asyncio.run(ks.run_payment(fake, 150000, poll_interval=0, max_polls=2))
    assert result.status == "fail"
