"""Связывает штучные товары с позициями склада по совпадению названия.

Зачем: товар с типом "prepared" и пустой тех-картой при продаже НЕ списывает
ничего — молча. Именно из-за этого «Круассан с семгой» продавался, а остаток
на складе не менялся.

Что делает: если у товара есть позиция склада с тем же названием, товар
переводится в тип "retail" (штучный) и привязывается к ней. После этого
продажа уменьшает остаток на 1 за штуку, а возврат — возвращает обратно.

Кофе, чай и прочее готовящееся на месте скрипт не трогает: им нужны настоящие
тех-карты (молоко, зерно, сироп), а не привязка «один к одному».

Запуск:
    .venv\\Scripts\\python link_products_to_stock.py          — показать план
    .venv\\Scripts\\python link_products_to_stock.py --apply  — применить
"""
import sys

from app.db import SessionLocal
from app.models import Ingredient, Product, RecipeItem


def deducts_stock(session, p: Product) -> bool:
    """Списывает ли товар склад при продаже — та же логика, что в sales_service."""
    if p.kind == "prepared":
        return session.query(RecipeItem).filter(RecipeItem.product_id == p.id).count() > 0
    return p.ingredient_id is not None


def main() -> None:
    apply = "--apply" in sys.argv
    link, no_position, already = [], [], 0

    with SessionLocal() as s:
        ings = {i.name.strip().lower(): i
                for i in s.query(Ingredient).filter(Ingredient.is_active).all()}

        for p in s.query(Product).filter(Product.is_active).order_by(Product.name).all():
            if deducts_stock(s, p):
                already += 1
                continue
            ing = ings.get(p.name.strip().lower())
            if ing is None:
                no_position.append(p)
                continue
            link.append((p, ing))
            if apply:
                p.kind = "retail"
                p.ingredient_id = ing.id
        if apply:
            s.commit()

        print("=== " + ("ПРИМЕНЕНО" if apply else "ПЛАН (база не изменена)") + " ===")
        print(f"уже списывают склад: {already}")
        print(f"\nбудут связаны со складом: {len(link)}")
        for p, ing in link:
            print(f"   {p.name:34} -> склад «{ing.name}» ({ing.stock_qty} {ing.unit})")

        print(f"\nбез позиции склада — нужна тех-карта или новая позиция: {len(no_position)}")
        for p in no_position:
            print(f"   {p.name}")

        if not apply:
            print("\nПрименить: .venv\\Scripts\\python link_products_to_stock.py --apply")


if __name__ == "__main__":
    main()
