from datetime import datetime

from app.models import KaspiSettings


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
