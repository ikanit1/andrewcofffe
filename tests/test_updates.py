import asyncio

import pytest

from app.services import updates


@pytest.mark.parametrize("text, expected", [
    ("2026.07.27", (2026, 7, 27)),
    (" 2026.07.27\n", (2026, 7, 27)),
    ("2026.07.27\n# комментарий", (2026, 7, 27)),
    ("2026.7.5", (2026, 7, 5)),
])
def test_parses_version(text, expected):
    assert updates.parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "не версия", "2026", "2026.07.27.1.2", "v1.2.3-beta"])
def test_rejects_unparseable_version(text):
    assert updates.parse_version(text) is None


def test_same_version_is_current():
    assert updates.compare_versions("2026.07.27", "2026.07.27") == "current"


def test_older_local_means_update_available():
    assert updates.compare_versions("2026.07.20", "2026.07.27") == "outdated"
    assert updates.compare_versions("2025.12.31", "2026.01.01") == "outdated"


def test_newer_local_is_ahead():
    """На машине разработчика код бывает свежее опубликованного —
    это не повод предлагать «обновиться» до более старого."""
    assert updates.compare_versions("2026.07.28", "2026.07.27") == "ahead"


def test_unparseable_input_is_unknown():
    assert updates.compare_versions("мусор", "2026.07.27") == "unknown"
    assert updates.compare_versions("2026.07.27", "") == "unknown"


def test_local_version_is_readable_and_valid():
    """Файл VERSION едет вместе с кодом — он и есть источник правды
    для установок из ZIP, где нет истории git."""
    assert updates.parse_version(updates.local_version()) is not None


def test_check_reports_update_when_remote_is_newer(monkeypatch):
    async def fake_fetch() -> str:
        return "2026.09.01"

    monkeypatch.setattr(updates, "_fetch_remote_version", fake_fetch)
    monkeypatch.setattr(updates, "local_version", lambda: "2026.07.27")

    result = asyncio.run(updates.check_for_update())
    assert result.status == "outdated"
    assert result.remote == "2026.09.01"
    assert result.local == "2026.07.27"
    assert result.error is None


def test_check_reports_current_when_versions_match(monkeypatch):
    async def fake_fetch() -> str:
        return "2026.07.27"

    monkeypatch.setattr(updates, "_fetch_remote_version", fake_fetch)
    monkeypatch.setattr(updates, "local_version", lambda: "2026.07.27")

    assert asyncio.run(updates.check_for_update()).status == "current"


def test_check_survives_network_failure(monkeypatch):
    """Нет интернета — касса продолжает работать, экран просто говорит,
    что проверить не удалось."""
    async def boom() -> str:
        raise OSError("сеть недоступна")

    monkeypatch.setattr(updates, "_fetch_remote_version", boom)
    result = asyncio.run(updates.check_for_update())
    assert result.status == "unknown"
    assert result.error is not None
    assert result.remote is None
