"""Создаёт разделы склада по категориям кассы и раскладывает по ним позиции.

Раздел позиции определяется по товару, который с ней связан: если «Круассан
с семгой» лежит в меню в «Сендвичи и стрит-фуд», то и складская позиция
попадёт в одноимённый раздел. Позиции без связанного товара (сырьё вроде
молока и зерна) остаются без раздела — их место в меню не определено.

Запуск:
    .venv\\Scripts\\python sync_stock_categories.py          — показать план
    .venv\\Scripts\\python sync_stock_categories.py --apply  — применить
"""
import sys

from app.db import SessionLocal
from app.models import Category, Ingredient, Product, StockCategory
from app.services import inventory_service as inv


def main() -> None:
    apply = "--apply" in sys.argv

    with SessionLocal() as s:
        cats = {c.id: c.name for c in s.query(Category).all()}

        # позиция склада -> название категории меню связанного товара
        wanted: dict[int, str] = {}
        for p in s.query(Product).filter(Product.is_active,
                                         Product.ingredient_id.isnot(None)).all():
            name = cats.get(p.category_id)
            if name:
                wanted.setdefault(p.ingredient_id, name)

        needed = sorted(set(wanted.values()))
        # Ключ нормализованный: в базе встречаются «Мороженое» и «Мороженое »
        # с висячим пробелом, и поиск по точному имени пытался завести дубль.
        existing = {c.name.strip().casefold(): c for c in s.query(StockCategory).all()}

        def key(n: str) -> str:
            return n.strip().casefold()

        created = [n for n in needed if key(n) not in existing]
        by_section: dict[str, list[str]] = {}
        moved = 0

        for ing in s.query(Ingredient).filter(Ingredient.is_active).all():
            target = wanted.get(ing.id)
            if target is None:
                continue
            by_section.setdefault(target, []).append(ing.name.strip())
            if apply:
                cat = existing.get(key(target))
                if cat is None:
                    cat = inv.create_stock_category(s, target.strip(),
                                                    sort_order=needed.index(target))
                    existing[key(target)] = cat
                if ing.category_id != cat.id:
                    ing.category_id = cat.id
                    moved += 1
        if apply:
            s.commit()

        orphans = s.query(Ingredient).filter(
            Ingredient.is_active, Ingredient.id.notin_(list(wanted) or [0])).count()

        print("=== " + ("ПРИМЕНЕНО" if apply else "ПЛАН (база не изменена)") + " ===")
        print(f"разделов будет создано: {len(created)}")
        for n in created:
            print(f"   {n}")
        print(f"\nпозиций разложено по разделам: {sum(len(v) for v in by_section.values())}")
        for name in sorted(by_section):
            items = sorted(by_section[name])
            print(f"\n   [{name}] — {len(items)}")
            print("      " + ", ".join(items))
        print(f"\nбез раздела остаются: {orphans} "
              "(сырьё и позиции без связанного товара)")
        if apply:
            print(f"перенесено позиций: {moved}")
        else:
            print("\nПрименить: .venv\\Scripts\\python sync_stock_categories.py --apply")


if __name__ == "__main__":
    main()
