"""Стартовые данные: владелец, кассир и меню кофейни.

Запуск: python seed.py <telegram_id_админа>

Меню описано данными ниже — правьте здесь, чтобы установка с нуля на новой
машине поднималась сразу с нужными товарами и ценами. Саму базу (pos.db) git
не хранит, поэтому этот файл и есть то, что переезжает вместе с проектом.
Тех-карты (recipe_items) заполняются уже в интерфейсе: граммовки у каждой
кофейни свои.
"""
import sys

from sqlalchemy.orm import Session

from app.auth import hash_pin
from app.db import SessionLocal, init_db
from app.models import (
    Category,
    KaspiSettings,
    Modifier,
    ModifierGroup,
    Product,
    ProductModifierGroup,
    User,
)

# название группы -> (обязательна ли, [(вариант, наценка в тенге)])
MODIFIER_GROUPS: dict[str, tuple[bool, list[tuple[str, int]]]] = {
    "Объём":          (True, [("0.3 л", 0), ("0.4 л", 100)]),
    "Вкус рафа":      (True, [("Классика", 0), ("Лаванда", 0)]),
    "Вкус милкшейка": (True, [("Ваниль", 0), ("Шоколад", 0), ("Ягодный", 0), ("Клубничный", 0)]),
    "Вкус лимонада":  (True, [("Гранат", 0), ("Цитрус", 0), ("Киви-лайм", 0), ("Манго-маракуйя", 0)]),
    "Вид чая":        (True, [("Чёрный", 0), ("Зелёный", 0), ("С лимоном", 0)]),
    "Вид авторского": (True, [("Ягодный", 0), ("Облепиховый", 0), ("Марокканский", 0)]),
}

# категория -> [(товар, цена в тенге, [группы модификаторов])]
MENU: list[tuple[str, list[tuple[str, int, list[str]]]]] = [
    ("Кофе", [
        ("Эспрессо",  600,  []),
        ("Американо", 900,  []),
        ("Капучино",  1100, ["Объём"]),
        ("Латте",     1100, ["Объём"]),
        ("Флэтуайт",  1200, ["Объём"]),
        ("Какао",     1100, ["Объём"]),
        ("Раф",       1300, ["Вкус рафа"]),
        ("Айс кофе",  1300, []),
    ]),
    ("Холодные напитки", [
        ("Милкшейк", 1350, ["Вкус милкшейка"]),
        ("Лимонад",  1100, ["Вкус лимонада"]),
        ("Мохито",   1100, ["Вкус лимонада"]),
    ]),
    ("Чай", [
        ("Чай классический", 400,  ["Вид чая"]),
        ("Чай авторский",    1000, ["Вид авторского"]),
    ]),
]


def apply_seed(session: Session, admin_telegram_id: int) -> bool:
    """Наполняет пустую базу. False — если пользователи уже есть и сид пропущен."""
    if session.query(User).count() > 0:
        return False

    session.add(User(telegram_id=admin_telegram_id, name="Владелец", role="admin",
                     pin_hash=hash_pin("9999")))
    session.add(User(telegram_id=admin_telegram_id + 1, name="Кассир", role="cashier",
                     discount_limit_percent=10, pin_hash=hash_pin("1234")))

    group_ids: dict[str, int] = {}
    for name, (required, variants) in MODIFIER_GROUPS.items():
        group = ModifierGroup(name=name, is_required=required)
        session.add(group)
        session.flush()
        group_ids[name] = group.id
        for variant, delta_tenge in variants:
            session.add(Modifier(group_id=group.id, name=variant,
                                 price_delta_tiyn=delta_tenge * 100))

    for cat_order, (cat_name, products) in enumerate(MENU, start=1):
        category = Category(name=cat_name, sort_order=cat_order)
        session.add(category)
        session.flush()
        for prod_order, (prod_name, price_tenge, groups) in enumerate(products, start=1):
            product = Product(name=prod_name, category_id=category.id, kind="prepared",
                              price_tiyn=price_tenge * 100, sort_order=prod_order)
            session.add(product)
            session.flush()
            for group_name in groups:
                session.add(ProductModifierGroup(product_id=product.id,
                                                 group_id=group_ids[group_name]))

    session.add(KaspiSettings(id=1))
    session.commit()
    return True


def seed(admin_telegram_id: int) -> None:
    init_db()
    with SessionLocal() as session:
        if apply_seed(session, admin_telegram_id):
            products = session.query(Product).count()
            print(f"Готово: владелец, кассир и меню ({products} товаров) созданы.")
            print("PIN владельца 9999, кассира 1234 — смените их после первого входа.")
            print("Тех-карты пока пустые: заполните в «Склад и тех-карты», иначе")
            print("себестоимость и маржа в отчётах будут нулевыми, а склад не спишется.")
        else:
            print("БД уже содержит данные — сид пропущен")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python seed.py <telegram_id_админа>")
        sys.exit(1)
    seed(int(sys.argv[1]))
