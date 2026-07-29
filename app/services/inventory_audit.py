from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, Modifier, ModifierItem, Product, RecipeItem


@dataclass(frozen=True)
class StockRequirement:
    ingredient_id: int
    name: str
    unit: str
    required_qty: int
    stock_qty: int


@dataclass(frozen=True)
class ProductInventoryStatus:
    product_id: int
    product_name: str
    policy: str
    is_sellable: bool
    issues: tuple[str, ...]
    requirements: tuple[StockRequirement, ...]
    max_qty: int | None


def product_inventory_status(
    session: Session,
    product: Product,
    *,
    modifier_ids: list[int] | None = None,
) -> ProductInventoryStatus:
    policy = product.inventory_policy or "track"
    if policy == "untracked":
        return ProductInventoryStatus(
            product.id, product.name, policy, True, (), (), None
        )

    issues: list[str] = []
    per_unit: dict[int, StockRequirement] = {}

    def add_requirement(ingredient_id: int, qty: int, label: str) -> None:
        ing = session.get(Ingredient, ingredient_id)
        if ing is None:
            issues.append(f"{label}: складская позиция не найдена")
            return
        if not ing.is_active:
            issues.append(f"{label}: складская позиция скрыта")
            return
        current = per_unit.get(ing.id)
        if current is None:
            per_unit[ing.id] = StockRequirement(
                ing.id, ing.name, ing.unit, qty, ing.stock_qty
            )
        else:
            per_unit[ing.id] = StockRequirement(
                ing.id, ing.name, ing.unit,
                current.required_qty + qty, ing.stock_qty,
            )

    if product.kind == "prepared":
        rows = session.scalars(
            select(RecipeItem).where(RecipeItem.product_id == product.id)
        ).all()
        if not rows:
            issues.append("нет техкарты")
        for row in rows:
            add_requirement(row.ingredient_id, row.qty, "техкарта")
    elif product.kind == "retail":
        if product.ingredient_id is None:
            issues.append("штучный товар не привязан к складу")
        else:
            add_requirement(product.ingredient_id, 1, "товар")

    if modifier_ids:
        items = session.scalars(
            select(ModifierItem).where(ModifierItem.modifier_id.in_(modifier_ids))
        ).all()
        for item in items:
            add_requirement(item.ingredient_id, item.qty, "модификатор")

    requirements = tuple(per_unit.values())
    max_qty_raw = min(
        (r.stock_qty // r.required_qty for r in requirements if r.required_qty > 0),
        default=None,
    )
    max_qty = max(max_qty_raw, 0) if max_qty_raw is not None else None
    return ProductInventoryStatus(
        product.id,
        product.name,
        policy,
        not issues and (max_qty is None or max_qty > 0),
        tuple(issues),
        requirements,
        max_qty,
    )


def validate_sale_inventory(
    session: Session,
    lines: list[tuple[Product, list[Modifier], int]],
) -> None:
    issues: list[str] = []
    totals: dict[int, StockRequirement] = {}

    for product, mods, qty in lines:
        status = product_inventory_status(
            session,
            product,
            modifier_ids=[m.id for m in mods],
        )
        if status.issues:
            issues.append(f"{product.name}: {', '.join(status.issues)}")
        for req in status.requirements:
            needed = req.required_qty * qty
            current = totals.get(req.ingredient_id)
            if current is None:
                totals[req.ingredient_id] = StockRequirement(
                    req.ingredient_id, req.name, req.unit, needed, req.stock_qty
                )
            else:
                totals[req.ingredient_id] = StockRequirement(
                    req.ingredient_id, req.name, req.unit,
                    current.required_qty + needed, req.stock_qty,
                )

    for req in totals.values():
        if req.required_qty > req.stock_qty:
            issues.append(
                f"{req.name}: нужно {req.required_qty} {req.unit}, есть {req.stock_qty} {req.unit}"
            )

    if issues:
        raise ValueError("Продажа заблокирована складом: " + "; ".join(issues))
