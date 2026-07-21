import asyncio

import httpx
import pytest

from app.kaspi.client import KaspiClient, KaspiError


def _client(handler, **kw):
    return KaspiClient("http://term:8080", transport=httpx.MockTransport(handler), **kw)


def test_deviceinfo_ok():
    def handler(request):
        assert request.url.path == "/v2/deviceinfo"
        return httpx.Response(200, json={
            "data": {"posNum": "0", "serialNum": "ND000000000", "terminalId": "00000000"},
            "statusCode": 0,
        })
    data = asyncio.run(_client(handler).deviceinfo())
    assert data["serialNum"] == "ND000000000"
    assert data["terminalId"] == "00000000"


def test_register_sends_name_no_token():
    def handler(request):
        assert request.url.path == "/v2/register"
        assert request.url.params.get("name") == "Kashier1"
        assert "accesstoken" not in request.headers
        return httpx.Response(200, json={
            "data": {"accessToken": "acc", "refreshToken": "ref",
                     "expirationDate": "2026-07-23 12:00:00"},
            "statusCode": 0,
        })
    data = asyncio.run(_client(handler).register("Kashier1"))
    assert data["accessToken"] == "acc"
    assert data["expirationDate"] == "2026-07-23 12:00:00"


def test_payment_sends_amount_and_token():
    def handler(request):
        assert request.url.path == "/v2/payment"
        assert request.url.params.get("amount") == "1500"
        assert request.url.params.get("owncheque") == "false"
        assert request.headers.get("accesstoken") == "acc"
        return httpx.Response(200, json={
            "data": {"processId": "p1", "status": "wait"}, "statusCode": 0,
        })
    data = asyncio.run(_client(handler, access_token="acc").payment(1500, owncheque=False))
    assert data["processId"] == "p1"


def test_status_sends_process_and_terminal_id():
    def handler(request):
        assert request.url.path == "/v2/status"
        assert request.url.params.get("processId") == "p1"
        assert request.headers.get("accesstoken") == "acc"
        assert request.headers.get("terminalId") == "00000000"
        return httpx.Response(200, json={
            "data": {"processId": "p1", "status": "success", "transactionId": "504711333",
                     "chequeInfo": {"method": "qr"}},
            "statusCode": 0,
        })
    data = asyncio.run(_client(handler, access_token="acc", terminal_id="00000000").status("p1"))
    assert data["status"] == "success"
    assert data["transactionId"] == "504711333"


def test_business_error_raises_kaspi_error():
    def handler(request):
        return httpx.Response(200, json={"errorText": "Process not found", "statusCode": 101})
    with pytest.raises(KaspiError) as exc:
        asyncio.run(_client(handler, access_token="acc").status("nope"))
    assert exc.value.status_code == 101
    assert "Process not found" in str(exc.value)


def test_http_error_raises_kaspi_error():
    def handler(request):
        return httpx.Response(403, text="Forbidden")
    with pytest.raises(KaspiError) as exc:
        asyncio.run(_client(handler, access_token="bad").deviceinfo())
    assert exc.value.status_code == 403
