import hashlib
import hmac
from urllib.parse import urlencode

from app.auth import hash_pin, validate_init_data, verify_pin

TOKEN = "1234567890:TEST-TOKEN"


def _make_init_data(params: dict, token: str) -> str:
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": h})


def test_valid_init_data_accepted():
    init = _make_init_data({"auth_date": "1752900000", "user": '{"id":111}'}, TOKEN)
    data = validate_init_data(init, TOKEN)
    assert data is not None
    assert data["auth_date"] == "1752900000"


def test_tampered_init_data_rejected():
    init = _make_init_data({"auth_date": "1752900000", "user": '{"id":111}'}, TOKEN)
    tampered = init.replace("111", "222")
    assert validate_init_data(tampered, TOKEN) is None


def test_wrong_token_rejected():
    init = _make_init_data({"auth_date": "1752900000"}, TOKEN)
    assert validate_init_data(init, "другой:токен") is None


def test_pin_hash_roundtrip():
    h = hash_pin("4821")
    assert verify_pin("4821", h)
    assert not verify_pin("0000", h)
    assert h != "4821"
