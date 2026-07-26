"""Разовый импорт меню кофейни: охлаждённые напитки и обеды.

Кофе, чай, милкшейки и лимонады уже заведены и собраны на модификаторах
(«Объём», «Вкус милкшейка» и т.д.) — их скрипт не трогает, иначе появились бы
дубли вида «Капучино» + «Капучино М» + «Капучино L».

Запуск:
    .venv\\Scripts\\python import_menu.py          — показать, что будет сделано
    .venv\\Scripts\\python import_menu.py --apply  — записать в базу
"""
import sys

from app.db import SessionLocal
from app.models import Category, Ingredient, Product
from app.services import catalog_service as cs

# Охлаждённые напитки — штучный товар: каждый заводится складской позицией (шт)
# и товаром kind="retail", привязанным к ней. Так работают приход и остатки.
COLD_DRINKS: list[tuple[str, int]] = [
    ("Gorilla", 620),
    ("Red bull", 970),
    ("Dizzy", 550),
    ("Dizzy mojito", 600),
    ("Royal mojito", 350),
    ("Coca Cola", 550),
    ("Pepsi", 550),
    ("Pepsi ж/б", 600),
    ("Вода Tassay без газа", 400),
    ("Вода Tassay с газом", 400),
    ("Сок детский", 350),
    ("Tassay Energy", 600),
]

# Обеды — приготовленные блюда. Тех-карты не заводим: состав знает только кухня,
# без него склад по ним просто не списывается (цена и продажи работают).
LUNCHES: list[tuple[str, int]] = [
    ("Шашлык куриный", 1600),
    ("Шашлык утка", 1600),
    ("Чикен крылышки", 1600),
    ("Стрипсы", 1600),
    ("Мясо по-французски", 1600),
    ("Курица Тереяки", 1600),
    ("Курица по-тайски", 1600),
    ("Удон", 1600),
    ("Цомян", 1600),
    ("Пита", 1600),
    ("Паста Песто", 1600),
    ("Паста Фетучини", 1600),
    ("Французский завтрак", 1600),
    ("Изи Брик завтрак", 1600),
    ("Куриный шницель", 1600),
    ("Гречка с курицей в сливочном соусе", 1600),
    ("Салат цезарь", 1500),
    ("Бризоль", 1600),
    ("Митбоул", 1600),
    ("Скрембл", 1600),
    ("Боул куриный", 2100),
    ("Боул семга", 2200),
    ("ПП завтрак", 1600),
    ("Омлет со шпинатом", 1600),
    ("Круассан с курицей", 1300),
    ("Круассан с семгой", 1400),
    ("Френч дог сырный", 1050),
    ("Френч дог томатный", 1050),
    ("Френч дог барбекю", 1050),
    ("Панини с курицей", 1150),
    ("Бейгл", 1150),
    ("Гранолла", 1200),
    ("Печенье брауни", 1200),
    ("Ролл куриный", 1100),
    ("Клаб сендвич", 1100),
    ("Кесадилья", 1150),
    ("Острые крылышки", 1600),
    ("Мини бургеры", 700),
    ("Бельгийские вафли", 1100),
    ("Сырники", 1050),
    ("Салат греческий", 1300),
    ("Салат сельдь под шубой", 1200),
    ("Вареники в сливочно-грибном соусе", 1600),
    ("Допанжи", 1600),
    ("Манты", 1600),  # в присланном списке было 1609 — владелец подтвердил опечатку
    ("Плов", 1600),
    ("Жареные пельмени", 1300),
    ("Бефстроганов", 1600),
    ("Том Ям", 1400),
]

COLD_CATEGORY = "Охлаждённые напитки"
LUNCH_CATEGORY = "готовые обеды"


def get_or_create_category(session, name: str, sort_order: int) -> tuple[Category, bool]:
    cat = session.query(Category).filter(Category.name == name).one_or_none()
    if cat is not None:
        return cat, False
    return cs.create_category(session, name, sort_order=sort_order), True


def main() -> None:
    apply = "--apply" in sys.argv
    created_cats, created_ings, created_prods, skipped = [], [], [], []

    with SessionLocal() as s:
        existing = {p.name.strip().lower() for p in s.query(Product).all()}

        cold_cat, made = get_or_create_category(s, COLD_CATEGORY, 25) if apply else (
            s.query(Category).filter(Category.name == COLD_CATEGORY).one_or_none(), True)
        if made and apply:
            created_cats.append(COLD_CATEGORY)
        elif cold_cat is None:
            created_cats.append(COLD_CATEGORY)

        lunch_cat = s.query(Category).filter(Category.name == LUNCH_CATEGORY).one_or_none()
        if lunch_cat is None:
            if apply:
                lunch_cat = cs.create_category(s, LUNCH_CATEGORY, sort_order=40)
            created_cats.append(LUNCH_CATEGORY)

        for order, (name, price) in enumerate(COLD_DRINKS):
            if name.strip().lower() in existing:
                skipped.append(name)
                continue
            created_prods.append((COLD_CATEGORY, name, price))
            created_ings.append(name)
            if apply:
                ing = s.query(Ingredient).filter(Ingredient.name == name).one_or_none()
                if ing is None:
                    ing = Ingredient(name=name, unit="шт", stock_qty=0,
                                     avg_cost_tiyn=0.0, low_stock_threshold=5)
                    s.add(ing)
                    s.commit()
                cs.create_product(s, name=name, category_id=cold_cat.id, kind="retail",
                                  price_tiyn=price * 100, ingredient_id=ing.id,
                                  sort_order=order)

        for order, (name, price) in enumerate(LUNCHES):
            if name.strip().lower() in existing:
                skipped.append(name)
                continue
            created_prods.append((LUNCH_CATEGORY, name, price))
            if apply:
                cs.create_product(s, name=name, category_id=lunch_cat.id, kind="prepared",
                                  price_tiyn=price * 100, sort_order=order)

    head = "ЗАПИСАНО" if apply else "БУДЕТ СОЗДАНО (пробный прогон, база не изменена)"
    print(f"=== {head} ===")
    print(f"Категорий: {len(created_cats)} {created_cats}")
    print(f"Складских позиций (шт): {len(created_ings)}")
    print(f"Товаров: {len(created_prods)}")
    for cat, name, price in created_prods:
        print(f"   [{cat}] {name} — {price} тг")
    if skipped:
        print(f"\nПропущено (уже есть в меню): {len(skipped)} — {skipped}")
    if not apply:
        print("\nЧтобы записать: .venv\\Scripts\\python import_menu.py --apply")


if __name__ == "__main__":
    main()
