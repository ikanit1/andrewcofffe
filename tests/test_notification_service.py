from app.models import NotificationOutbox
from app.services import notification_service as ns


def test_enqueue_creates_pending_record(session):
    note = ns.enqueue(session, kind="shift_open", text="Смена открыта")
    session.commit()
    assert note.status == "pending"
    assert note.sent_at is None
    assert session.query(NotificationOutbox).count() == 1


def test_pending_returns_only_pending(session):
    ns.enqueue(session, kind="shift_open", text="A")
    b = ns.enqueue(session, kind="shift_open", text="B")
    session.commit()
    ns.mark_sent(session, b.id)
    pending = ns.pending(session)
    assert [n.text for n in pending] == ["A"]


def test_mark_sent_sets_status_and_timestamp(session):
    note = ns.enqueue(session, kind="shift_open", text="A")
    session.commit()
    ns.mark_sent(session, note.id)
    got = session.get(NotificationOutbox, note.id)
    assert got.status == "sent"
    assert got.sent_at is not None


def test_mark_failed_sets_status(session):
    note = ns.enqueue(session, kind="shift_open", text="A")
    session.commit()
    ns.mark_failed(session, note.id)
    got = session.get(NotificationOutbox, note.id)
    assert got.status == "failed"
