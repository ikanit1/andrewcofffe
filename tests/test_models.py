from app.models import User


def test_user_roundtrip(session):
    u = User(telegram_id=111, name="Айгерим", role="cashier")
    session.add(u)
    session.commit()
    got = session.query(User).filter_by(telegram_id=111).one()
    assert got.role == "cashier"
    assert got.is_active is True
    assert got.discount_limit_percent == 10
