"""Склад кофейни: сколько штук товара лежит на точке.

Никаких ингредиентов, граммов и тех-карт — считается сам товар из меню.
Остаток может быть не задан (stock_qty = None): у кофе, который варят из общих
запасов, количества не существует, и такие товары склад просто не трогает.

Продажа никогда не блокируется: остаток может уйти в минус, и это видно в
списке — но касса обязана пробить чек в любом случае.
"""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Product, StockMove
from app.services import notification_service

# Виды движений. "sale" и "refund" пишет касса, остальные — владелец руками.
MOVE_LABELS = {
    "purchase": "Приход",
    "sale": "Продажа",
    "refund": "Возврат",
    "adjustment": "Корректировка",
}


def tracked(product: Product) -> bool:
    """Считаем ли остаток по этому товару."""
    return product.stock_qty is not None


def apply_move(
    session: Session,
    product_id: int,
    *,
    qty_delta: int,
    kind: str,
    cost_tiyn: int | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
    commit: bool = False,
) -> StockMove | None:
    """Единственная точка изменения остатка: журнал + кэш в одной транзакции.

    None — товар не считается (stock_qty is None), движение не пишется: иначе
    продажа кофе плодила бы журнал, который никто не заводил.

    Коммитит владелец транзакции: по умолчанию делается только flush,
    session.commit() — забота вызывающего кода (или commit=True явно).
    """
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"Товар {product_id} не найден")
    if not tracked(product):
        return None
    move = StockMove(
        product_id=product_id,
        qty_delta=qty_delta,
        kind=kind,
        cost_tiyn=cost_tiyn,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )
    # атомарный UPDATE ... SET stock_qty = stock_qty + qty_delta (без гонок на уровне БД)
    product.stock_qty = Product.stock_qty + qty_delta
    session.add(move)
    session.flush()
    _check_low_stock(session, product)
    if commit:
        session.commit()
    return move


def _check_low_stock(session: Session, product: Product) -> None:
    """Уведомляет при падении ниже порога. Порог 0 — отслеживание выключено.

    Повторное уведомление — только после пополнения выше порога и нового
    падения: иначе каждая продажа на исходе слала бы владельцу сообщение.
    """
    if product.low_stock_threshold <= 0 or product.stock_qty is None:
        return
    if product.stock_qty < product.low_stock_threshold:
        if not product.low_stock_notified:
            notification_service.enqueue(
                session, kind="low_stock",
                text=(f"Низкий остаток: {product.name} — {product.stock_qty} шт "
                      f"(порог {product.low_stock_threshold})"),
            )
            product.low_stock_notified = True
    else:
        product.low_stock_notified = False


def set_stock(session: Session, product_id: int, *, new_qty: int | None,
              note: str | None = None) -> StockMove | None:
    """Выставляет остаток в указанное значение. None — перестать считать товар.

    Пишется движением на разницу, а не присваиванием: остаток обязан оставаться
    суммой журнала, иначе история и факт разъедутся.
    """
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"Товар {product_id} не найден")

    if new_qty is None:
        product.stock_qty = None
        product.low_stock_notified = False
        session.commit()
        return None

    if product.stock_qty is None:
        # Товар начинают считать: остаток заводится одним движением от нуля
        product.stock_qty = 0
        session.flush()
    delta = new_qty - product.stock_qty
    if delta == 0:
        session.commit()
        return None
    move = apply_move(session, product_id, qty_delta=delta, kind="adjustment",
                      note=note or "ручная корректировка", commit=False)
    session.commit()
    return move


def receive_purchase(session: Session, product_id: int, *, qty: int,
                     total_cost_tiyn: int) -> None:
    """Приход: остаток растёт, закупочная цена за штуку пересчитывается."""
    if qty <= 0:
        raise ValueError("Количество прихода должно быть больше нуля")
    if total_cost_tiyn < 0:
        raise ValueError("Сумма прихода не может быть отрицательной")
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"Товар {product_id} не найден")

    # Приход всегда включает товар в учёт: раз его закупили штуками, считать есть что
    if product.stock_qty is None:
        product.stock_qty = 0
        session.flush()

    if total_cost_tiyn:
        old_qty = max(product.stock_qty, 0)  # минус не должен ломать среднюю цену
        product.cost_tiyn = round(
            (old_qty * product.cost_tiyn + total_cost_tiyn) / (old_qty + qty))
    apply_move(session, product_id, qty_delta=qty, kind="purchase",
               cost_tiyn=total_cost_tiyn, commit=False)
    session.commit()


def update_product_stock_settings(
    session: Session, product_id: int, *,
    low_stock_threshold: int | None = None, cost_tiyn: int | None = None,
) -> Product:
    """Складские настройки товара: порог предупреждения и закупочная цена."""
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"Товар {product_id} не найден")
    if low_stock_threshold is not None:
        if low_stock_threshold < 0:
            raise ValueError("Порог не может быть отрицательным")
        product.low_stock_threshold = low_stock_threshold
        # Порог могли поднять выше остатка — тогда нужно уведомить заново
        product.low_stock_notified = False
        _check_low_stock(session, product)
    if cost_tiyn is not None:
        if cost_tiyn < 0:
            raise ValueError("Закупочная цена не может быть отрицательной")
        product.cost_tiyn = cost_tiyn
    session.commit()
    return product


@dataclass(frozen=True)
class StockRow:
    """Строка экрана склада: товар, его остаток и раздел меню."""

    product_id: int
    name: str
    category: str
    stock_qty: int | None
    low_stock_threshold: int
    cost_tiyn: int
    price_tiyn: int
    is_active: bool

    @property
    def tracked(self) -> bool:
        return self.stock_qty is not None

    @property
    def is_low(self) -> bool:
        return (self.stock_qty is not None and self.low_stock_threshold > 0
                and self.stock_qty < self.low_stock_threshold)


def stock_rows(session: Session, *, include_hidden: bool = False,
               query: str | None = None, only_tracked: bool = False) -> list[StockRow]:
    """Товары для экрана склада, по разделам меню и алфавиту внутри раздела."""
    stmt = (
        select(Product, Category.name)
        .outerjoin(Category, Product.category_id == Category.id)
        .order_by(Category.sort_order, Category.name, Product.name)
    )
    if not include_hidden:
        stmt = stmt.where(Product.is_active)
    rows = [
        StockRow(
            product_id=p.id, name=p.name, category=cat or "Без категории",
            stock_qty=p.stock_qty, low_stock_threshold=p.low_stock_threshold,
            cost_tiyn=p.cost_tiyn, price_tiyn=p.price_tiyn, is_active=p.is_active,
        )
        for p, cat in session.execute(stmt).all()
    ]
    text = (query or "").strip().lower()
    if text:
        rows = [r for r in rows if text in r.name.lower()]
    if only_tracked:
        rows = [r for r in rows if r.tracked]
    return rows


def low_stock_products(session: Session) -> list[Product]:
    """Товары, у которых остаток опустился ниже заданного порога."""
    return list(session.scalars(
        select(Product)
        .where(Product.is_active, Product.stock_qty.is_not(None),
               Product.low_stock_threshold > 0,
               Product.stock_qty < Product.low_stock_threshold)
        .order_by(Product.name)
    ).all())


@dataclass(frozen=True)
class MoveRow:
    created_at: object
    product_name: str
    qty_delta: int
    kind: str
    cost_tiyn: int | None
    note: str | None

    @property
    def kind_label(self) -> str:
        return MOVE_LABELS.get(self.kind, self.kind)


def recent_moves(session: Session, *, product_id: int | None = None,
                 kind: str | None = None, limit: int = 50) -> list[MoveRow]:
    """Журнал движений: что приходило, что списывалось и кто это поправил."""
    stmt = (
        select(StockMove, Product.name)
        .join(Product, Product.id == StockMove.product_id)
        .order_by(StockMove.created_at.desc(), StockMove.id.desc())
        .limit(limit)
    )
    if product_id is not None:
        stmt = stmt.where(StockMove.product_id == product_id)
    if kind:
        stmt = stmt.where(StockMove.kind == kind)
    return [
        MoveRow(created_at=move.created_at, product_name=name, qty_delta=move.qty_delta,
                kind=move.kind, cost_tiyn=move.cost_tiyn, note=move.note)
        for move, name in session.execute(stmt).all()
    ]


def clear_moves(session: Session, product_id: int) -> int:
    """Стирает журнал по товару, оставляя текущий остаток как есть."""
    removed = session.query(StockMove).filter(
        StockMove.product_id == product_id).delete(synchronize_session=False)
    session.commit()
    return int(removed)


def stock_value_tiyn(session: Session) -> int:
    """Во сколько обходится всё, что лежит на складе, по закупочным ценам."""
    return int(session.scalar(
        select(func.coalesce(func.sum(Product.stock_qty * Product.cost_tiyn), 0))
        .where(Product.is_active, Product.stock_qty.is_not(None),
               Product.stock_qty > 0)
    ) or 0)
