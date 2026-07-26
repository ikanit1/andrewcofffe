"""Проверка, вышла ли новая версия кассы.

Версия лежит в файле VERSION в корне проекта и едет вместе с кодом. Именно файл,
а не хеш коммита: установка из ZIP (как описано в README) приходит без истории
git, и `git rev-parse` там просто нечего спросить.

Проверка только читает — обновление не применяется. Причины две. Админка
смотрит в интернет через Tailscale Funnel, и кнопка «обновить», дёргающая
git pull с перезапуском, была бы способом выполнить чужой код на кассе для
всякого, кто попал внутрь. И отдельно: сервер, убивающий сам себя посреди
смены, — плохая идея для кассы.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"
REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/ikanit1/andrewcofffe/master/VERSION"
)
_TIMEOUT_SECONDS = 10.0

# Версия — дата выпуска и, необязательно, порядковый номер выпуска за этот день:
# 2026.07.27 или 2026.07.27.2. Номер нужен потому, что за сутки обновление могут
# выпустить не один раз, а по одной дате касса решила бы, что менять нечего.
# Отсутствующий номер считаем нулём: 2026.07.27 старше, чем 2026.07.27.1.
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")

Status = Literal["current", "outdated", "ahead", "unknown"]


@dataclass(frozen=True)
class UpdateCheck:
    status: Status
    local: str
    remote: str | None = None
    error: str | None = None


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """(2026, 7, 27, 0) из «2026.07.27», (2026, 7, 27, 2) из «2026.07.27.2».

    Длина всегда 4 — чтобы версии сравнивались как кортежи без оговорок.
    None — распознать не удалось.
    """
    if not text:
        return None
    first_line = text.strip().splitlines()[0].strip() if text.strip() else ""
    m = _VERSION_RE.match(first_line)
    if m is None:
        return None
    year, month, day, seq = m.groups()
    return (int(year), int(month), int(day), int(seq or 0))


def compare_versions(local: str, remote: str) -> Status:
    a, b = parse_version(local), parse_version(remote)
    if a is None or b is None:
        return "unknown"
    if a == b:
        return "current"
    return "outdated" if a < b else "ahead"


def local_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("Не удалось прочитать %s", VERSION_FILE)
        return ""


async def _fetch_remote_version() -> str:
    import httpx

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        resp = await client.get(REMOTE_VERSION_URL)
    resp.raise_for_status()
    return resp.text


async def check_for_update() -> UpdateCheck:
    """Сравнивает локальную версию с опубликованной. Сеть недоступна — не ошибка."""
    local = local_version()
    try:
        remote_raw = await _fetch_remote_version()
    except Exception as e:  # сеть, DNS, 404, что угодно — касса продолжает работать
        logger.info("Проверка обновления не удалась: %r", e)
        return UpdateCheck(status="unknown", local=local, error=str(e) or type(e).__name__)

    remote = (remote_raw.strip().splitlines() or [""])[0].strip()
    return UpdateCheck(status=compare_versions(local, remote), local=local, remote=remote)
