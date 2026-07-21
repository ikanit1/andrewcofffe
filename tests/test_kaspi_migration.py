from sqlalchemy import create_engine, text

from app.db import ensure_schema


def test_ensure_schema_adds_missing_payment_columns():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE payments (id INTEGER PRIMARY KEY, method VARCHAR, amount_tiyn INTEGER)"
        ))
        conn.execute(text("INSERT INTO payments (method, amount_tiyn) VALUES ('cash', 100)"))
    ensure_schema(engine)
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(payments)"))}
        assert {"provider", "terminal_method", "transaction_id"} <= cols
        val = conn.execute(text("SELECT provider FROM payments WHERE method='cash'")).scalar()
        assert val == "manual"


def test_ensure_schema_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE payments (id INTEGER PRIMARY KEY, method VARCHAR, amount_tiyn INTEGER)"
        ))
    ensure_schema(engine)
    ensure_schema(engine)
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(payments)"))}
        assert "provider" in cols


def test_ensure_schema_skips_when_no_payments_table():
    engine = create_engine("sqlite://")
    ensure_schema(engine)
