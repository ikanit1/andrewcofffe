"""Убирает задвоения меню и склада, возникшие при уточнении названий.

Старый товар не удаляется, а скрывается (is_active=False): на него ссылаются
позиции прошлых чеков, и удаление порвало бы историю продаж.

Остаток со скрываемой позиции склада переносится на остающуюся движением
kind="adjustment" — остаток обязан оставаться суммой журнала, поэтому просто
переписать числа нельзя.

Пары проверены владельцем. «Шашлык куриный» и «Курица на шпажках», как и
«Курица по-тайски» и «Мясо по-тайски с рисом», — разные блюда, их не трогаем.

Запуск:
    .venv\\Scripts\\python merge_duplicates.py          — показать план
    .venv\\Scripts\\python merge_duplicates.py --apply  — применить
"""
import sys

from app.db import SessionLocal
from app.models import Ingredient, Product
from app.services import inventory_service as inv

# (скрыть, оставить)
PRODUCT_PAIRS = [
    ("Изи Брик завтрак", "Easy Break"),
    ("Паста Фетучини", "Фетучини с курицей и грибами"),
    ("Курица Терияки", "Курица в соусе Терияки с рисом"),
    ("Мясо по-французски", "По-французски"),
    ("Гречка с курицей в сливочном соусе", "Курица в сливочном соусе"),
]

# Товар привязан к позиции со старым написанием, а правильно названная висит
# без товара: (товар, позиция-как-надо, позиция-дубль)
STOCK_RELINK = [
    ("Блины с фаршем", "Блины с фаршем", "Блины фарш"),
    ("Блины с семгой", "Блины с семгой", "Блины семга"),
]


def main() -> None:
    apply = "--apply" in sys.argv
    hidden, relinked, moved_stock, skipped = [], [], [], []

    with SessionLocal() as s:
        def prod(name):
            return s.query(Product).filter(Product.name == name).first()

        def ing(name):
            return s.query(Ingredient).filter(Ingredient.name == name).first()

        for old_name, keep_name in PRODUCT_PAIRS:
            old, keep = prod(old_name), prod(keep_name)
            if old is None or keep is None:
                skipped.append(f"{old_name} / {keep_name}: одного из товаров нет")
                continue
            old_ing = s.get(Ingredient, old.ingredient_id) if old.ingredient_id else None
            keep_ing = s.get(Ingredient, keep.ingredient_id) if keep.ingredient_id else None
            qty = old_ing.stock_qty if old_ing else 0
            hidden.append((old_name, keep_name, qty))
            if apply:
                old.is_active = False
                s.commit()
                if old_ing is not None:
                    # Остаток переносим, а не обнуляем: это учётные данные
                    if qty and keep_ing is not None:
                        inv.adjust_stock(s, old_ing.id, new_qty=0,
                                         note=f"перенос на «{keep_name}»")
                        inv.adjust_stock(s, keep_ing.id,
                                         new_qty=keep_ing.stock_qty + qty,
                                         note=f"перенос с «{old_name}»")
                        moved_stock.append((old_name, keep_name, qty))
                    inv.set_ingredient_active(s, old_ing.id, False)

        for prod_name, keep_ing_name, dup_ing_name in STOCK_RELINK:
            p, good, dup = prod(prod_name), ing(keep_ing_name), ing(dup_ing_name)
            if p is None or good is None or dup is None:
                skipped.append(f"{prod_name}: нечего перепривязывать")
                continue
            relinked.append((prod_name, dup.name, good.name, dup.stock_qty))
            if apply:
                if dup.stock_qty:
                    inv.adjust_stock(s, dup.id, new_qty=0,
                                     note=f"перенос на «{good.name}»")
                    inv.adjust_stock(s, good.id,
                                     new_qty=good.stock_qty + dup.stock_qty,
                                     note=f"перенос с «{dup.name}»")
                good.category_id = dup.category_id or good.category_id
                p.ingredient_id = good.id
                s.commit()
                inv.set_ingredient_active(s, dup.id, False)

    print("=== " + ("ПРИМЕНЕНО" if apply else "ПЛАН (база не изменена)") + " ===")
    print(f"\nскрыто товаров-дублей: {len(hidden)}")
    for old, keep, qty in hidden:
        tail = f"   (остаток {qty} перенесён)" if qty else ""
        print(f"   {old!r} -> остаётся {keep!r}{tail}")
    print(f"\nперепривязано к правильной позиции склада: {len(relinked)}")
    for pname, dup, good, qty in relinked:
        tail = f", остаток {qty} перенесён" if qty else ""
        print(f"   {pname!r}: {dup!r} -> {good!r}{tail}")
    if skipped:
        print(f"\nпропущено: {len(skipped)}")
        for m in skipped:
            print(f"   {m}")
    if not apply:
        print("\nПрименить: .venv\\Scripts\\python merge_duplicates.py --apply")


if __name__ == "__main__":
    main()
