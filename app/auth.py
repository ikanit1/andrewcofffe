import hashlib
import hmac
import os
import re
from urllib.parse import parse_qsl

_HEX_HASH_RE = re.compile(r"[0-9a-f]{64}")


# TODO(этап 2): при подключении к страницам добавить проверку свежести auth_date
# (max_age_seconds, для кассы 1-2 часа) и rate-limit на ввод пин-кода.
def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Проверка подписи Telegram Mini App initData. None — подпись неверна."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash or not _HEX_HASH_RE.fullmatch(received_hash):
        return None
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None
    return pairs


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    return salt.hex() + ":" + digest.hex()


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 100_000)
    return hmac.compare_digest(digest.hex(), digest_hex)
