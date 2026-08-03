from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Modifier, ModifierGroup, ProductModifierGroup


def create_group(session: Session, name: str, is_required: bool = False) -> ModifierGroup:
    grp = ModifierGroup(name=name, is_required=is_required)
    session.add(grp)
    session.commit()
    return grp


def add_modifier(session: Session, *, group_id: int, name: str, price_delta_tiyn: int = 0) -> Modifier:
    m = Modifier(group_id=group_id, name=name, price_delta_tiyn=price_delta_tiyn)
    session.add(m)
    session.commit()
    return m


def attach_group(session: Session, *, product_id: int, group_id: int) -> None:
    exists = session.scalar(
        select(ProductModifierGroup).where(
            ProductModifierGroup.product_id == product_id,
            ProductModifierGroup.group_id == group_id,
        )
    )
    if exists is not None:
        return
    session.add(ProductModifierGroup(product_id=product_id, group_id=group_id))
    session.commit()


def groups_for_product(session: Session, product_id: int) -> list[tuple[ModifierGroup, list[Modifier]]]:
    groups = session.scalars(
        select(ModifierGroup)
        .join(ProductModifierGroup, ProductModifierGroup.group_id == ModifierGroup.id)
        .where(ProductModifierGroup.product_id == product_id)
    ).all()
    result = []
    for g in groups:
        mods = session.scalars(
            select(Modifier).where(Modifier.group_id == g.id, Modifier.is_active)
        ).all()
        result.append((g, list(mods)))
    return result
