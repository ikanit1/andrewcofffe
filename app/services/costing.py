from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, ModifierItem, Product, RecipeItem


def unit_cost_tiyn(session: Session, product: Product, modifier_ids: list[int]) -> int:
    """Себестоимость одной единицы товара с учётом выбранных модификаторов (в тиынах).

    prepared — по тех-карте; retail — по привязанной складской позиции.
    Плюс списания выбранных модификаторов (ModifierItem).
    """
    if (product.inventory_policy or "track") == "untracked":
        return 0

    cost = 0.0
    if product.kind == "prepared":
        rows = session.scalars(
            select(RecipeItem).where(RecipeItem.product_id == product.id)
        ).all()
        for r in rows:
            ing = session.get(Ingredient, r.ingredient_id)
            cost += r.qty * ing.avg_cost_tiyn
    elif product.kind == "retail":
        if product.ingredient_id is not None:
            ing = session.get(Ingredient, product.ingredient_id)
            cost += ing.avg_cost_tiyn  # 1 единица на порцию

    if modifier_ids:
        items = session.scalars(
            select(ModifierItem).where(ModifierItem.modifier_id.in_(modifier_ids))
        ).all()
        for mi in items:
            ing = session.get(Ingredient, mi.ingredient_id)
            cost += mi.qty * ing.avg_cost_tiyn

    return round(cost)
