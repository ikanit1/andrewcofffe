"""Обнуление продаж: удаляет чеки, оплаты, возвраты, смены и инкассации.

НЕ трогает: пользователей, категории, товары, модификаторы, ингредиенты
и остатки склада — обнуляется только история продаж, каталог остаётся.

Движения склада (StockMove) не удаляются: там лежат приходы товара, а списания
по продажам уменьшили остатки, и просто стереть их значило бы разойтись
с фактическим складом. Если списания по продажам есть, скрипт остановится
и скажет об этом — молча портить остатки он не будет.

Запуск:
    .venv\\Scripts\\python reset_orders.py          — показать, что удалится
    .venv\\Scripts\\python reset_orders.py --apply  — удалить
"""
import sys

from app.db import SessionLocal
from app.models import (CashCollection, NotificationOutbox, Order, OrderItem,
                        OrderItemModifier, Payment, Refund, RefundItem, Shift,
                        StockMove)

# Порядок важен: сначала то, что ссылается, потом то, на что ссылаются.
WIPE = [
    (RefundItem, "позиции возвратов"),
    (Refund, "возвраты"),
    (OrderItemModifier, "модификаторы в чеках"),
    (OrderItem, "позиции чеков"),
    (Payment, "оплаты"),
    (Order, "чеки"),
    (CashCollection, "инкассации"),
    (Shift, "смены"),
    (NotificationOutbox, "очередь уведомлений"),
]

# Виды движений склада, которые создаются продажей и возвратом
SALE_MOVE_KINDS = ("sale", "refund")


def main() -> None:
    apply = "--apply" in sys.argv

    with SessionLocal() as s:
        sale_moves = s.query(StockMove).filter(StockMove.kind.in_(SALE_MOVE_KINDS)).count()
        counts = [(label, s.query(model).count()) for model, label in WIPE]

        print("=== " + ("УДАЛЕНО" if apply else "БУДЕТ УДАЛЕНО (пробный прогон)") + " ===")
        for label, n in counts:
            print(f"   {label}: {n}")
        total = sum(n for _, n in counts)
        print(f"   всего записей: {total}")

        if sale_moves:
            print(f"\nСТОП: найдено {sale_moves} движений склада по продажам/возвратам.")
            print("Их удаление разошлось бы с фактическими остатками, а сохранение")
            print("оставило бы списания без чеков. Разберитесь со складом вручную")
            print("или скажите, что делать с остатками.")
            return

        if not apply:
            print("\nСохранится: пользователи, категории, товары, модификаторы,")
            print("ингредиенты и остатки склада.")
            print("\nУдалить: .venv\\Scripts\\python reset_orders.py --apply")
            return

        for model, _ in WIPE:
            s.query(model).delete(synchronize_session=False)
        s.commit()

        left = sum(s.query(model).count() for model, _ in WIPE)
        print(f"\nОсталось записей продаж: {left}")


if __name__ == "__main__":
    main()
