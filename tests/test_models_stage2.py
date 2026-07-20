from app.models import CashCollection, Shift, User


def _cashier(session):
    u = User(telegram_id=555, name="Кассир", role="cashier")
    session.add(u)
    session.flush()
    return u


def test_shift_open_defaults(session):
    c = _cashier(session)
    sh = Shift(cashier_id=c.id, opening_cash_tiyn=500000)
    session.add(sh)
    session.commit()
    got = session.query(Shift).one()
    assert got.status == "open"
    assert got.closed_at is None
    assert got.opening_cash_tiyn == 500000
    assert got.opened_at is not None


def test_cash_collection(session):
    c = _cashier(session)
    sh = Shift(cashier_id=c.id, opening_cash_tiyn=0)
    session.add(sh)
    session.flush()
    session.add(CashCollection(shift_id=sh.id, amount_tiyn=300000, note="в сейф"))
    session.commit()
    coll = session.query(CashCollection).one()
    assert coll.amount_tiyn == 300000
    assert coll.note == "в сейф"
