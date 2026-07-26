"""Разовая разбивка «готовые обеды» на нормальные категории меню.

Товары не создаются и не удаляются — только переносятся в новые категории.
Опустевшая «готовые обеды» отключается (is_active=False), а не удаляется:
на неё могут ссылаться старые отчёты, и отключение обратимо.

Запуск:
    .venv\\Scripts\\python split_lunch_categories.py          — показать план
    .venv\\Scripts\\python split_lunch_categories.py --apply  — применить
"""
import sys

from app.db import SessionLocal
from app.models import Category, Product
from app.services import catalog_service as cs

OLD_CATEGORY = "готовые обеды"

# (категория, sort_order, позиции). Порядок как в зале: завтраки, горячее, гарниры, закуски.
GROUPS: list[tuple[str, int, list[str]]] = [
    ("Завтраки", 30, [
        "Пита", "Французский завтрак", "Изи Брик завтрак", "ПП завтрак",
        "Омлет со шпинатом", "Скрембл", "Сырники", "Бельгийские вафли", "Гранолла",
    ]),
    ("Горячие блюда", 31, [
        "Бризоль", "Шашлык куриный", "Шашлык утка", "Чикен крылышки",
        "Острые крылышки", "Стрипсы", "Мясо по-французски", "Курица Терияки",
        "Курица по-тайски", "Куриный шницель", "Гречка с курицей в сливочном соусе",
        "Митбоул", "Вареники в сливочно-грибном соусе", "Допанжи", "Манты",
        "Плов", "Жареные пельмени", "Бефстроганов", "Том Ям", "Удон", "Цомян",
    ]),
    ("Паста", 32, ["Паста Песто", "Паста Фетучини"]),
    ("Салаты", 33, [
        "Салат Цезарь", "Салат греческий", "Салат сельдь под шубой",
        "Боул куриный", "Боул семга",
    ]),
    ("Сендвичи и стрит-фуд", 34, [
        "Круассан с курицей", "Круассан с семгой", "Панини с курицей", "Бейгл",
        "Ролл куриный", "Клаб сендвич", "Кесадилья", "Мини бургеры",
        "Френч дог сырный", "Френч дог томатный", "Френч дог барбекю",
    ]),
    ("Десерты", 35, ["Печенье брауни"]),
]

# Названия, которые в базе записаны иначе, чем в присланном списке.
RENAMES: dict[str, str] = {
    "Курица Тереяки": "Курица Терияки",   # в первом списке была опечатка
    "Салат цезарь": "Салат Цезарь",       # с заглавной, как в новом списке
}


def main() -> None:
    apply = "--apply" in sys.argv
    moved, renamed, missing = [], [], []

    with SessionLocal() as s:
        by_name = {p.name.strip().lower(): p for p in s.query(Product).all()}

        for old, new in RENAMES.items():
            p = by_name.get(old.strip().lower())
            if p is not None:
                renamed.append((p.name, new))
                if apply:
                    p.name = new
                # и в плане, и в бою товар дальше ищется по новому имени,
                # иначе пробный прогон врал бы «не найден»
                by_name[new.strip().lower()] = p
        if apply and renamed:
            s.commit()

        for cat_name, sort_order, items in GROUPS:
            cat = s.query(Category).filter(Category.name == cat_name).one_or_none()
            if cat is None and apply:
                cat = cs.create_category(s, cat_name, sort_order=sort_order)
            for order, item in enumerate(items):
                p = by_name.get(item.strip().lower())
                if p is None:
                    missing.append(item)
                    continue
                moved.append((cat_name, p.name))
                if apply:
                    p.category_id = cat.id
                    p.sort_order = order
        if apply:
            s.commit()
            old_cat = s.query(Category).filter(Category.name == OLD_CATEGORY).one_or_none()
            if old_cat is not None:
                left = s.query(Product).filter(Product.category_id == old_cat.id).count()
                if left == 0:
                    old_cat.is_active = False
                    s.commit()

    head = "ПРИМЕНЕНО" if apply else "ПЛАН (база не изменена)"
    print(f"=== {head} ===")
    if renamed:
        print("Переименования:")
        for a, b in renamed:
            print(f"   {a}  →  {b}")
    print(f"\nПеренос товаров: {len(moved)}")
    for cat_name, _, items in GROUPS:
        got = [n for c, n in moved if c == cat_name]
        print(f"   {cat_name}: {len(got)} из {len(items)}")
    if missing:
        print(f"\nНЕ НАЙДЕНЫ В БАЗЕ ({len(missing)}): {missing}")
    else:
        print("\nВсе позиции из списка найдены в базе.")
    if not apply:
        print("\nПрименить: .venv\\Scripts\\python split_lunch_categories.py --apply")


if __name__ == "__main__":
    main()
