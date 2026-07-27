"""Связывает штучные товары с позициями склада по совпадению названия.

Зачем: товар с типом "prepared" и пустой тех-картой при продаже НЕ списывает
ничего — молча. Именно из-за этого «Круассан с семгой» продавался, а остаток
на складе не менялся.

Что делает: если у товара есть позиция склада с тем же названием, товар
переводится в тип "retail" (штучный) и привязывается к ней. После этого
продажа уменьшает остаток на 1 за штуку, а возврат — возвращает обратно.

Кофе, чай и прочее готовящееся на месте скрипт не трогает: им нужны настоящие
тех-карты (молоко, зерно, сироп), а не привязка «один к одному».

Флаг --create-missing заводит позицию склада (в штуках, остаток 0) для штучных
товаров, у которых её ещё нет, и сразу привязывает. Категории напитков при этом
всё равно пропускаются.

Запуск:
    .venv\\Scripts\\python link_products_to_stock.py                    — план
    .venv\\Scripts\\python link_products_to_stock.py --apply            — связать
    .venv\\Scripts\\python link_products_to_stock.py --create-missing --apply
"""
import sys

from app.db import SessionLocal
from app.models import Category, Ingredient, Product, RecipeItem

# Категории, товары которых готовятся на месте: им нужна тех-карта, а не
# привязка «одна продажа — одна штука со склада».
DRINK_CATEGORIES = ("кофе", "чай", "холодные напитки")

# Порог низкого остатка у новых позиций — 0, то есть уведомления выключены.
# Иначе 33 позиции с нулевым остатком тут же прислали бы 33 сообщения «на исходе».
NEW_THRESHOLD = 0


def deducts_stock(session, p: Product) -> bool:
    """Списывает ли товар склад при продаже — та же логика, что в sales_service."""
    if p.kind == "prepared":
        return session.query(RecipeItem).filter(RecipeItem.product_id == p.id).count() > 0
    return p.ingredient_id is not None


def main() -> None:
    apply = "--apply" in sys.argv
    create_missing = "--create-missing" in sys.argv
    link, created, drinks, no_position, already = [], [], [], [], 0

    with SessionLocal() as s:
        ings = {i.name.strip().lower(): i
                for i in s.query(Ingredient).filter(Ingredient.is_active).all()}
        cats = {c.id: c.name.strip().lower() for c in s.query(Category).all()}

        for p in s.query(Product).filter(Product.is_active).order_by(Product.name).all():
            if deducts_stock(s, p):
                already += 1
                continue
            if cats.get(p.category_id, "") in DRINK_CATEGORIES:
                drinks.append(p)
                continue

            ing = ings.get(p.name.strip().lower())
            if ing is not None:
                link.append((p, ing))
                if apply:
                    p.kind = "retail"
                    p.ingredient_id = ing.id
                continue

            if not create_missing:
                no_position.append(p)
                continue
            created.append(p)
            if apply:
                ing = Ingredient(name=p.name.strip(), unit="шт", stock_qty=0,
                                 avg_cost_tiyn=0.0, low_stock_threshold=NEW_THRESHOLD)
                s.add(ing)
                s.flush()
                p.kind = "retail"
                p.ingredient_id = ing.id
        if apply:
            s.commit()

        print("=== " + ("ПРИМЕНЕНО" if apply else "ПЛАН (база не изменена)") + " ===")
        print(f"уже списывают склад: {already}")

        if link:
            print(f"\nсвязаны с существующей позицией: {len(link)}")
            for p, ing in link:
                print(f"   {p.name:34} -> «{ing.name.strip()}» ({ing.stock_qty} {ing.unit})")

        if created:
            print(f"\nсоздана позиция склада (шт, остаток 0): {len(created)}")
            for p in created:
                print(f"   {p.name}")

        if no_position:
            print(f"\nбез позиции склада — добавьте --create-missing: {len(no_position)}")
            for p in no_position:
                print(f"   {p.name}")

        print(f"\nпропущены как готовящиеся на месте: {len(drinks)}")
        print("   " + ", ".join(p.name for p in drinks))

        if not apply:
            flag = "--create-missing --apply" if create_missing else "--apply"
            print(f"\nПрименить: .venv\\Scripts\\python link_products_to_stock.py {flag}")


if __name__ == "__main__":
    main()
