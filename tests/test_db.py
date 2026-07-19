from app.config import Settings
from app.db import Base


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None, BOT_TOKEN="x")
    assert s.database_url == "sqlite:///pos.db"


def test_base_exists(session):
    assert Base.metadata is not None
