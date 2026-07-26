from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Category, Order, OrderItem, Payment, Product, Shift, User
from app.services import daily_summary as ds


def _db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'd.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed(tmp_path, *, shift_status="closed", shift_opened=None):
    """Один день: 2 чека — 30.00 налом и 15.00 картой, себестоимость 12.00."""
    Sm = _db(tmp_path)
    now = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)  # 13:00 Алматы
    with Sm() as s:
        cashier = User(telegram_id=1, name="Айгуль", role="cashier", is_active=True)
        cat = Category(name="Кофе")
        s.add_all([cashier, cat]); s.flush()
        prod = Product(name="Латте", category_id=cat.id, kind="prepared", price_tiyn=1500)
        s.add(prod); s.flush()
        shift = Shift(cashier_id=cashier.id, opened_at=shift_opened or now,
                      status=shift_status, opening_cash_tiyn=0)
        s.add(shift); s.flush()
        for num, (total, cost, method) in enumerate(
            [(3000, 800, "cash"), (1500, 400, "card")], start=1
        ):
            o = Order(shift_id=shift.id, number=num, status="paid", subtotal_tiyn=total,
                      total_tiyn=total, cost_tiyn=cost, created_at=now)
            s.add(o); s.flush()
            s.add(OrderItem(order_id=o.id, product_id=prod.id, name="Латте",
                            unit_price_tiyn=1500, qty=total // 1500,
                            line_total_tiyn=total, unit_cost_tiyn=400))
            s.add(Payment(order_id=o.id, method=method, amount_tiyn=total, created_at=now))
        s.commit()
    return Sm, now


def test_summary_reports_date_and_totals(tmp_path):
    Sm, now = _seed(tmp_path)
    with Sm() as s:
        text = ds.daily_summary_text(s, now=now)
    assert "26.07.2026" in text
    assert "Чеков: 2" in text
    assert "45.00" in text  # выручка 30.00 + 15.00


def test_summary_breaks_down_payment_methods(tmp_path):
    Sm, now = _seed(tmp_path)
    with Sm() as s:
        text = ds.daily_summary_text(s, now=now)
    assert "наличные" in text.lower()
    assert "карта" in text.lower()


def test_summary_shows_margin(tmp_path):
    Sm, now = _seed(tmp_path)
    with Sm() as s:
        text = ds.daily_summary_text(s, now=now)
    assert "12.00" in text  # себестоимость 8.00 + 4.00
    assert "33.00" in text  # маржа 45.00 − 12.00


def test_summary_lists_top_products(tmp_path):
    Sm, now = _seed(tmp_path)
    with Sm() as s:
        text = ds.daily_summary_text(s, now=now)
    assert "Латте" in text


def test_summary_on_empty_day_says_no_sales(tmp_path):
    Sm = _db(tmp_path)
    now = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)
    with Sm() as s:
        text = ds.daily_summary_text(s, now=now)
    assert "продаж не было" in text.lower()
    assert "26.07.2026" in text


def test_summary_warns_about_shift_left_open_from_earlier_day(tmp_path):
    """Незакрытая с прошлых суток смена ломает сверку кассы — о ней надо сказать."""
    opened = datetime(2026, 7, 22, 0, 4, tzinfo=timezone.utc)
    Sm, now = _seed(tmp_path, shift_status="open", shift_opened=opened)
    with Sm() as s:
        text = ds.daily_summary_text(s, now=now)
    assert "22.07" in text
    assert "не закрыта" in text.lower()


def test_enqueue_puts_summary_into_outbox(tmp_path):
    """Сводка уходит через ту же очередь, что и прочие уведомления — с ретраями."""
    from app.models import NotificationOutbox

    Sm, now = _seed(tmp_path)
    with Sm() as s:
        ds.enqueue_daily_summary(s, now=now)
        s.commit()
    with Sm() as s:
        note = s.query(NotificationOutbox).one()
    assert note.kind == "daily_summary"
    assert note.status == "pending"
    assert "Итоги дня 26.07.2026" in note.text


def test_summary_does_not_warn_when_shift_opened_today(tmp_path):
    opened_today = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)  # 11:00 Алматы
    Sm, now = _seed(tmp_path, shift_status="open", shift_opened=opened_today)
    with Sm() as s:
        text = ds.daily_summary_text(s, now=now)
    assert "не закрыта" not in text.lower()
