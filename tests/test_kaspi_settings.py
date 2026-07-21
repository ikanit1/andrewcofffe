from datetime import datetime, timezone

from app.models import KaspiSettings
from app.kaspi import settings as ksettings


def test_kaspi_settings_roundtrip(session):
    s = KaspiSettings(
        terminal_url="http://192.168.0.100:8080",
        cashier_name="Kashier1",
        access_token="a", refresh_token="r",
        token_expires_at=datetime(2026, 7, 23, 12, 0),
        terminal_id="00000000",
    )
    session.add(s)
    session.commit()
    got = session.query(KaspiSettings).one()
    assert got.terminal_url == "http://192.168.0.100:8080"
    assert got.cashier_name == "Kashier1"
    assert got.terminal_id == "00000000"


def test_kaspi_settings_defaults(session):
    s = KaspiSettings()
    session.add(s)
    session.commit()
    got = session.query(KaspiSettings).one()
    assert got.terminal_url == "http://192.168.0.100:8080"
    assert got.cashier_name == "Kashier1"
    assert got.access_token is None
    assert got.terminal_id is None


def test_get_settings_creates_singleton(session):
    s1 = ksettings.get_settings(session)
    assert s1.id == 1
    assert s1.terminal_url == "http://192.168.0.100:8080"
    s2 = ksettings.get_settings(session)
    assert s2.id == 1
    assert session.query(KaspiSettings).count() == 1


def test_save_config_updates_url_and_name(session):
    ksettings.get_settings(session)
    ksettings.save_config(session, terminal_url="https://10.0.0.5:8080", cashier_name="Bar1")
    s = ksettings.get_settings(session)
    assert s.terminal_url == "https://10.0.0.5:8080"
    assert s.cashier_name == "Bar1"


def test_save_tokens_and_terminal_id(session):
    ksettings.get_settings(session)
    exp = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    ksettings.save_tokens(session, access_token="acc", refresh_token="ref", expires_at=exp)
    ksettings.save_terminal_id(session, terminal_id="00000000")
    s = ksettings.get_settings(session)
    assert s.access_token == "acc"
    assert s.refresh_token == "ref"
    assert s.terminal_id == "00000000"
