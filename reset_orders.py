"""Обнуление продаж: удаляет чеки, оплаты, возвраты, смены и инкассации.

НЕ трогает: пользователей, категории, товары, модификаторы и сами позиции
склада — обнуляется история, каталог остаётся.

По умолчанию движения склада не удаляются: там лежат приходы товара, а списания
по продажам уменьшили остатки, и просто стереть их значило бы разойтись
с фактическим складом. Если списания по продажам есть, скрипт остановится —
молча портить остатки он не будет.

Флаг --with-stock снимает это ограничение: удаляются все движения, остатки
и средняя себестоимость обнуляются. Это чистый старт «с нуля», склад после
него наполняется приходом товара заново.

Запуск:
    .venv\\Scripts\\python reset_orders.py                       — показать план
    .venv\\Scripts\\python reset_orders.py --apply               — удалить продажи
    .venv\\Scripts\\python reset_orders.py --with-stock --apply  — и склад тоже
"""
import sys

from app.db import SessionLocal
from app.models import (CashCollection, Ingredient, NotificationOutbox, Order,
                        OrderItem, OrderItemModifier, Payment, Refund,
                        RefundItem, Shift, StockMove)

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
    with_stock = "--with-stock" in sys.argv

    with SessionLocal() as s:
        sale_moves = s.query(StockMove).filter(StockMove.kind.in_(SALE_MOVE_KINDS)).count()
        counts = [(label, s.query(model).count()) for model, label in WIPE]

        print("=== " + ("УДАЛЕНО" if apply else "БУДЕТ УДАЛЕНО (пробный прогон)") + " ===")
        for label, n in counts:
            print(f"   {label}: {n}")
        total = sum(n for _, n in counts)

        if with_stock:
            moves = s.query(StockMove).count()
            stocked = s.query(Ingredient).filter(Ingredient.stock_qty != 0).count()
            print(f"   движения склада: {moves}")
            print(f"   позиций с ненулевым остатком (обнулятся): {stocked}")
            total += moves
        print(f"   всего записей: {total}")

        if sale_moves and not with_stock:
            print(f"\nСТОП: найдено {sale_moves} движений склада по продажам/возвратам.")
            print("Их удаление разошлось бы с фактическими остатками, а сохранение")
            print("оставило бы списания без чеков. Либо разберитесь со складом вручную,")
            print("либо обнулите его вместе с продажами: --with-stock")
            return

        if not apply:
            print("\nСохранится: пользователи, категории, товары, модификаторы")
            print("и сами позиции склада" + ("" if with_stock else ", включая остатки"))
            cmd = "--with-stock --apply" if with_stock else "--apply"
            print(f"\nУдалить: .venv\\Scripts\\python reset_orders.py {cmd}")
            return

        for model, _ in WIPE:
            s.query(model).delete(synchronize_session=False)

        if with_stock:
            s.query(StockMove).delete(synchronize_session=False)
            # Остаток обязан оставаться суммой журнала: журнал стёрли — обнуляем и кэш.
            # Средняя себестоимость без приходов тоже теряет смысл.
            for ing in s.query(Ingredient).all():
                ing.stock_qty = 0
                ing.avg_cost_tiyn = 0.0
                ing.low_stock_notified = False
        s.commit()

        left = sum(s.query(model).count() for model, _ in WIPE)
        print(f"\nОсталось записей продаж: {left}")
        if with_stock:
            print(f"Движений склада: {s.query(StockMove).count()}")
            bad = s.query(Ingredient).filter(Ingredient.stock_qty != 0).count()
            print(f"Позиций с ненулевым остатком: {bad}")


if __name__ == "__main__":
    main()
