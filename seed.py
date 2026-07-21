"""Стартовые данные: админ + пример меню. Запуск: python seed.py <telegram_id_админа>"""
import sys

from app.auth import hash_pin
from app.db import SessionLocal, init_db
from app.models import (
    Category,
    Ingredient,
    Modifier,
    ModifierGroup,
    Product,
    ProductModifierGroup,
    RecipeItem,
    User,
)


def seed(admin_telegram_id: int) -> None:
    init_db()
    with SessionLocal() as s:
        if s.query(User).count() > 0:
            print("БД уже содержит данные — сид пропущен")
            return
        s.add(User(telegram_id=admin_telegram_id, name="Владелец", role="admin",
                   pin_hash=hash_pin("9999")))
        s.add(User(telegram_id=admin_telegram_id + 1, name="Кассир", role="cashier",
                   discount_limit_percent=10, pin_hash=hash_pin("1234")))

        coffee = Category(name="Кофе", sort_order=1)
        snacks = Category(name="Снеки", sort_order=2)
        s.add_all([coffee, snacks])
        s.flush()

        milk = Ingredient(name="Молоко", unit="мл", low_stock_threshold=2000)
        beans = Ingredient(name="Кофе зерно", unit="г", low_stock_threshold=500)
        croissant = Ingredient(name="Круассан", unit="шт", low_stock_threshold=5)
        s.add_all([milk, beans, croissant])
        s.flush()

        latte = Product(name="Латте", category_id=coffee.id, kind="prepared", price_tiyn=150000)
        s.add(latte)
        s.flush()
        s.add_all([
            RecipeItem(product_id=latte.id, ingredient_id=beans.id, qty=18),
            RecipeItem(product_id=latte.id, ingredient_id=milk.id, qty=200),
            Product(
                name="Круассан",
                category_id=snacks.id,
                kind="retail",
                price_tiyn=90000,
                ingredient_id=croissant.id,
            ),
        ])

        size = ModifierGroup(name="Объём", is_required=True)
        s.add(size)
        s.flush()
        s.add_all([
            Modifier(group_id=size.id, name="M", price_delta_tiyn=0),
            Modifier(group_id=size.id, name="L", price_delta_tiyn=20000),
            ProductModifierGroup(product_id=latte.id, group_id=size.id),
        ])

        s.commit()
        print("Готово: админ и пример меню созданы")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python seed.py <telegram_id_админа>")
        sys.exit(1)
    seed(int(sys.argv[1]))
