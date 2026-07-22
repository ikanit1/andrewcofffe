import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.kaspi import settings as ksettings
from app.kaspi.client import KaspiClient

logger = logging.getLogger(__name__)

_EXPIRATION_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class PaymentResult:
    status: str  # "success" | "fail" | "unknown"
    terminal_method: str | None = None  # "qr" | "card" | "alaqan"
    transaction_id: str | None = None
    message: str | None = None


def amount_to_tenge(total_tiyn: int) -> int:
    """Конвертирует тиыны в целые тенге. Терминал не принимает дробные тенге."""
    if total_tiyn % 100 != 0:
        raise ValueError("Kaspi принимает только целые тенге")
    return total_tiyn // 100


async def _poll_until_final(client, process_id: str, *, poll_interval: float, max_polls: int) -> dict:
    """Опрашивает статус до финального состояния. По исчерпании попыток — unknown.

    Транзиентный сбой опроса (сеть моргнула) не прерывает цикл: ошибка логируется,
    попытка считается неуспешной, а по исчерпании попыток вернётся unknown — чтобы
    вызывающий провёл сверку через actualize, а не потерял оплату без проверки.
    """
    for _ in range(max_polls):
        try:
            data = await client.status(process_id)
        except Exception:
            logger.exception("Ошибка опроса статуса %s", process_id)
            data = None
        if data is not None and data.get("status") != "wait":
            return data
        await asyncio.sleep(poll_interval)
    return {"status": "unknown", "message": "Таймаут ожидания оплаты"}


def _map_result(data: dict) -> PaymentResult:
    status = data.get("status", "unknown")
    if status == "success":
        return PaymentResult(
            status="success",
            terminal_method=(data.get("chequeInfo") or {}).get("method"),
            transaction_id=data.get("transactionId"),
        )
    return PaymentResult(status=status, message=data.get("message"))


async def run_payment(client, total_tiyn: int, *, poll_interval: float = 1.0,
                      max_polls: int = 180) -> PaymentResult:
    """Полный цикл оплаты на уже сконфигурированном клиенте (без БД).

    Проверяет сумму, запускает payment, опрашивает статус; при unknown пробует actualize.
    """
    amount = amount_to_tenge(total_tiyn)
    pay_data = await client.payment(amount, owncheque=False)
    process_id = pay_data["processId"]
    data = await _poll_until_final(client, process_id, poll_interval=poll_interval, max_polls=max_polls)
    if data.get("status") == "unknown":
        try:
            data = await client.actualize(process_id)
        except Exception:
            logger.exception("actualize не удался для %s", process_id)
    return _map_result(data)


def _parse_expiration(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, _EXPIRATION_FMT)
    except ValueError:
        return None


def _build_client(s) -> KaspiClient:
    return KaspiClient(s.terminal_url, access_token=s.access_token, terminal_id=s.terminal_id)


async def check_connection(session: Session) -> dict:
    """Проверка связи: deviceinfo. Работает и без токена."""
    s = ksettings.get_settings(session)
    client = _build_client(s)
    data = await client.deviceinfo()
    if data.get("terminalId"):
        ksettings.save_terminal_id(session, terminal_id=data["terminalId"])
    return data


async def register_cashier(session: Session) -> None:
    """Регистрация кассы: register → сохраняем токены; затем deviceinfo → terminalId."""
    s = ksettings.get_settings(session)
    client = KaspiClient(s.terminal_url)  # register без токена
    data = await client.register(s.cashier_name)
    ksettings.save_tokens(
        session,
        access_token=data["accessToken"],
        refresh_token=data["refreshToken"],
        expires_at=_parse_expiration(data.get("expirationDate")),
    )
    info = await _build_client(ksettings.get_settings(session)).deviceinfo()
    if info.get("terminalId"):
        ksettings.save_terminal_id(session, terminal_id=info["terminalId"])


async def pay(session: Session, total_tiyn: int, *, poll_interval: float = 1.0,
              max_polls: int = 180) -> PaymentResult:
    """Оплата с настройками из БД. Требует зарегистрированной кассы (есть access_token)."""
    s = ksettings.get_settings(session)
    if s.protection_enabled and not s.access_token:
        raise ValueError("Касса не зарегистрирована на терминале (см. /admin/kaspi)")
    client = _build_client(s)
    return await run_payment(client, total_tiyn, poll_interval=poll_interval, max_polls=max_polls)
