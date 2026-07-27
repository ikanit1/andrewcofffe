"""Добавляет новые блюда кухни и уточняет названия существующих.

Правило переименования намеренно узкое: старое название должно быть началом
нового («Пита» -> «Пита с омлетом и говядиной»). Похожесть строк для этого
не годится — она предлагала «Мясо по-французски» -> «Мясо по-тайски», а это
разные блюда, и такое переименование испортило бы меню.

Всё, что под правило не попало, заводится новым товаром: дополнить меню
безопаснее, чем угадать переименование. Лишнее потом убирается кнопкой
в админке, а неверно переименованное пришлось бы восстанавливать руками.

Каждому новому блюду заводится позиция склада (шт, остаток 0) и привязывается,
иначе продажа не будет списывать остаток.

Запуск:
    .venv\\Scripts\\python add_kitchen_menu.py          — показать план
    .venv\\Scripts\\python add_kitchen_menu.py --apply  — применить
"""
import sys

from app.db import SessionLocal
from app.models import Category, Ingredient, Product, StockCategory
from app.services import catalog_service as cs
from app.services import inventory_service as inv

# (категория кассы, название, цена в тенге)
MENU: list[tuple[str, str, int]] = [
    ("Завтраки", "Сырники", 1050),
    ("Завтраки", "Блины с фаршем", 1100),
    ("Завтраки", "Блины с семгой", 1200),
    ("Завтраки", "Бельгийские вафли", 1100),
    ("Завтраки", "Пита с омлетом и говядиной", 1600),
    ("Завтраки", "Easy Break", 1600),
    ("Завтраки", "Омлет со шпинатом", 1600),
    ("Завтраки", "Французский завтрак", 1600),
    ("Завтраки", "Скрембл с говяжьей сосиской", 1600),
    ("Завтраки", "ПП завтрак", 1600),

    ("Горячие блюда", "Бризоль из говядины с рисом", 1600),
    ("Горячие блюда", "Фетучини с курицей и грибами", 1600),
    ("Горячие блюда", "Удон", 1600),
    ("Горячие блюда", "Курица в соусе Терияки с рисом", 1600),
    ("Горячие блюда", "Паста Песто", 1600),
    ("Горячие блюда", "Цомян", 1600),
    ("Горячие блюда", "Манты", 1600),
    ("Горячие блюда", "Курица на шпажках", 1600),
    ("Горячие блюда", "Фаршированный перец с пюре", 1600),
    ("Горячие блюда", "Гуляш с рисом", 1600),
    ("Горячие блюда", "Мясо по-тайски с рисом", 1600),
    ("Горячие блюда", "Митбоул с томатным соусом", 1600),
    ("Горячие блюда", "Куриный шницель с рисом", 1600),
    ("Горячие блюда", "Фрикасе", 1600),
    ("Горячие блюда", "Бефстроганов", 1600),
    ("Горячие блюда", "Плов", 1600),
    ("Горячие блюда", "Куриная запеканка", 1600),
    ("Горячие блюда", "Острые крылышки", 1600),
    ("Горячие блюда", "Мясо по-тайски", 1600),
    ("Горячие блюда", "По-французски", 1600),
    ("Горячие блюда", "Жаркое", 1600),
    ("Горячие блюда", "Курица в сливочном соусе", 1600),
    ("Горячие блюда", "Вареники в сливочно-грибном соусе", 1600),
    ("Горячие блюда", "Рыба в кисло-сладком соусе", 1600),

    ("Салаты", "Греческий", 1300),
    ("Салаты", "Цезарь", 1500),
    ("Салаты", "Сельдь под шубой", 1200),
    ("Салаты", "Боул куриный", 2100),
    ("Салаты", "Боул семга", 2200),

    ("Сендвичи и стрит-фуд", "Круассан с курицей", 1300),
    ("Сендвичи и стрит-фуд", "Круассан с семгой", 1400),
    ("Сендвичи и стрит-фуд", "Френч дог сырный", 1050),
    ("Сендвичи и стрит-фуд", "Френч дог томатный", 1050),
    ("Сендвичи и стрит-фуд", "Френч дог барбекю", 1050),
    ("Сендвичи и стрит-фуд", "Панини куриный", 1150),
    ("Сендвичи и стрит-фуд", "Бейгл с индейкой", 1150),
    ("Сендвичи и стрит-фуд", "Чиабатта с курицей и халапеньо", 1150),
    ("Сендвичи и стрит-фуд", "Чиабатта с курицей", 1150),
    ("Сендвичи и стрит-фуд", "Кесадилья", 1150),
    ("Сендвичи и стрит-фуд", "Клаб-сэндвич", 1100),
    ("Сендвичи и стрит-фуд", "Ролл куриный", 1100),

    ("Десерты", "Печенье брауни", 1200),
    ("Десерты", "Гранолла", 1200),
    ("Десерты", "Трайфл Орео", 1200),
    ("Десерты", "Трайфл киндер", 1200),
    ("Десерты", "Испанский чизкейк", 1200),
]

# Пары, где короткое имя — не начало нового, но блюдо то же. Проверено глазами.
EXPLICIT_RENAMES = {
    "салат греческий": "Греческий",
    "салат сельдь под шубой": "Сельдь под шубой",
    "салат цезарь": "Цезарь",
    "панини с курицей": "Панини куриный",
    "клаб сендвич": "Клаб-сэндвич",
    "блины фарш": "Блины с фаршем",
    "блины семга": "Блины с семгой",
}


def norm(s: str) -> str:
    return (s or "").strip().lower()


def main() -> None:
    apply = "--apply" in sys.argv
    renames, created, price_fix, untouched, conflicts = [], [], [], [], []

    with SessionLocal() as s:
        cats = {c.name: c for c in s.query(Category).all()}
        prods = {norm(p.name): p for p in s.query(Product).filter(Product.is_active).all()}
        stock_cats = {c.name: c for c in s.query(StockCategory).all()}
        ings = {norm(i.name): i for i in s.query(Ingredient).all()}
        taken: set[str] = set()

        for cat_name, name, price in MENU:
            key = norm(name)
            if key in prods:                       # уже есть под этим именем
                p = prods[key]
                taken.add(key)
                if p.price_tiyn // 100 != price:
                    price_fix.append((p.name, p.price_tiyn // 100, price))
                    if apply:
                        p.price_tiyn = price * 100
                continue

            # старое имя — начало нового, либо явная пара из списка выше
            match = None
            for old_key, p in prods.items():
                if old_key in taken:
                    continue
                if EXPLICIT_RENAMES.get(old_key) == name or key.startswith(old_key + " "):
                    match = p
                    break
            if match is not None:
                taken.add(norm(match.name))
                renames.append((match.name, name, match.price_tiyn // 100, price))
                ing = (s.get(Ingredient, match.ingredient_id)
                       if match.ingredient_id else None)
                if ing is not None and norm(ing.name) != key:
                    # Имя позиции склада уникально. Если такое уже занято другой
                    # позицией (в базе завелись обе формы написания), переименование
                    # упало бы на ограничении и откатило бы весь прогон. Сливать
                    # позиции здесь нельзя: у обеих свои остатки и своя история.
                    other = ings.get(key)
                    if other is not None and other.id != ing.id:
                        conflicts.append((ing.name, other.name, ing.stock_qty,
                                          other.stock_qty))
                        ing = None
                if apply:
                    match.name = name
                    match.price_tiyn = price * 100
                    if ing is not None:
                        ing.name = name          # склад и касса зовутся одинаково
                        ings[key] = ing
                continue

            created.append((cat_name, name, price))
            if apply:
                cat = cats.get(cat_name)
                if cat is None:
                    cat = cs.create_category(s, cat_name)
                    cats[cat_name] = cat
                ing = ings.get(key)
                if ing is None:
                    ing = Ingredient(name=name, unit="шт", stock_qty=0,
                                     avg_cost_tiyn=0.0, low_stock_threshold=0,
                                     category_id=stock_cats[cat_name].id
                                     if cat_name in stock_cats else None)
                    s.add(ing)
                    s.flush()
                    ings[key] = ing
                cs.create_product(s, name=name, category_id=cat.id, kind="retail",
                                  price_tiyn=price * 100, ingredient_id=ing.id)
        if apply:
            s.commit()

        untouched = [p.name for k, p in prods.items() if k not in taken]

    print("=== " + ("ПРИМЕНЕНО" if apply else "ПЛАН (база не изменена)") + " ===")
    print(f"\nпереименовано: {len(renames)}")
    for old, new, op, np in renames:
        pc = "" if op == np else f"   цена {op} -> {np}"
        print(f"   {old!r} -> {new!r}{pc}")
    print(f"\nновых товаров (со складом): {len(created)}")
    for c, n, p in created:
        print(f"   [{c}] {n} — {p} тг")
    if price_fix:
        print(f"\nобновлена цена: {len(price_fix)}")
        for n, o, np in price_fix:
            print(f"   {n}: {o} -> {np}")
    print(f"\nне тронуто товаров: {len(untouched)}")
    if not apply:
        print("\nПрименить: .venv\\Scripts\\python add_kitchen_menu.py --apply")


if __name__ == "__main__":
    main()
