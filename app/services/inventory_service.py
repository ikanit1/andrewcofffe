from sqlalchemy.orm import Session

from app.models import Ingredient, StockMove
from app.services import notification_service


def apply_move(
    session: Session,
    ingredient_id: int,
    *,
    qty_delta: int,
    kind: str,
    cost_tiyn: int | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
    commit: bool = False,
) -> StockMove:
    """Единственная точка изменения остатка: журнал + кэш в одной транзакции.

    Коммитит владелец транзакции: по умолчанию делается только flush,
    session.commit() — забота вызывающего кода (или commit=True явно).
    """
    ing = session.get(Ingredient, ingredient_id)
    if ing is None:
        raise ValueError(f"Позиция склада {ingredient_id} не найдена")
    move = StockMove(
        ingredient_id=ingredient_id,
        qty_delta=qty_delta,
        kind=kind,
        cost_tiyn=cost_tiyn,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )
    # атомарный UPDATE ... SET stock_qty = stock_qty + qty_delta (без гонок на уровне БД)
    ing.stock_qty = Ingredient.stock_qty + qty_delta
    session.add(move)
    session.flush()
    _check_low_stock(session, ing)
    if commit:
        session.commit()
    return move


def _check_low_stock(session: Session, ing: Ingredient) -> None:
    """Уведомляет один раз при пересечении порога вниз; повтор — только после
    пересечения порога вверх (пополнение) и нового падения."""
    if ing.stock_qty < ing.low_stock_threshold:
        if not ing.low_stock_notified:
            notification_service.enqueue(
                session, kind="low_stock",
                text=(
                    f"Низкий остаток: {ing.name} — {ing.stock_qty} {ing.unit} "
                    f"(порог {ing.low_stock_threshold})"
                ),
            )
            ing.low_stock_notified = True
    else:
        ing.low_stock_notified = False


def receive_purchase(
    session: Session, ingredient_id: int, *, qty: int, total_cost_tiyn: int
) -> None:
    """Приход: остаток растёт, себестоимость пересчитывается средневзвешенно."""
    if qty <= 0:
        raise ValueError("Количество прихода должно быть больше нуля")
    if total_cost_tiyn < 0:
        raise ValueError("Сумма прихода не может быть отрицательной")
    ing = session.get(Ingredient, ingredient_id)
    if ing is None:
        raise ValueError(f"Позиция склада {ingredient_id} не найдена")

    old_qty = max(ing.stock_qty, 0)  # отрицательный остаток не должен ломать среднюю
    new_total_qty = old_qty + qty
    ing.avg_cost_tiyn = (old_qty * ing.avg_cost_tiyn + total_cost_tiyn) / new_total_qty
    apply_move(
        session,
        ingredient_id,
        qty_delta=qty,
        kind="purchase",
        cost_tiyn=total_cost_tiyn,
        commit=False,
    )
    session.commit()
