from nicegui import ui
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Ingredient, Modifier, ModifierGroup, Product
from app.services import modifier_service as ms


@ui.page("/admin/modifiers")
def admin_modifiers_page() -> None:
    from app.ui.guard import require_admin
    if not require_admin():
        return

    ui.label("Модификаторы").classes("text-2xl font-bold")

    groups_box = ui.column().classes("w-full max-w-3xl gap-2")

    def refresh() -> None:
        groups_box.clear()
        with groups_box, SessionLocal() as session:
            groups = session.scalars(select(ModifierGroup)).all()
            ing_options = {
                i.id: f"{i.name} ({i.unit})"
                for i in session.scalars(select(Ingredient).where(Ingredient.is_active)).all()
            }
            for g in groups:
                req = "обязательная" if g.is_required else "необязательная"
                ui.label(f"{g.name} — {req}").classes("text-xl mt-4")
                mods = session.scalars(select(Modifier).where(Modifier.group_id == g.id)).all()
                for m in mods:
                    ui.label(f"  {m.name}: +{m.price_delta_tiyn / 100:.0f} тг").classes("text-gray-600")
                with ui.row().classes("items-end gap-2"):
                    mn = ui.input("Новый модификатор")
                    mp = ui.number("Наценка, тг", value=0, min=0, format="%.0f")
                    mi = ui.select(ing_options, label="Списывать ингредиент (необяз.)")
                    mq = ui.number("Кол-во", value=0, min=0, format="%.0f")

                    def add_mod(gid=g.id, name=mn, price=mp, ing=mi, qty=mq) -> None:
                        if not name.value:
                            ui.notify("Введите название", color="red")
                            return
                        if ing.value and (not qty.value or round(qty.value) < 1):
                            ui.notify("Укажите количество списания ≥ 1", color="red")
                            return
                        try:
                            with SessionLocal() as s:
                                mod = ms.add_modifier(s, group_id=gid, name=name.value,
                                                      price_delta_tiyn=round((price.value or 0) * 100))
                                if ing.value and qty.value:
                                    ms.set_modifier_item(s, modifier_id=mod.id,
                                                         ingredient_id=ing.value, qty=round(qty.value))
                        except (ValueError, IntegrityError) as e:
                            ui.notify(str(e), color="red")
                            return
                        refresh()

                    ui.button("Добавить", on_click=add_mod)

    with ui.expansion("Добавить группу").classes("w-full max-w-3xl"):
        gn = ui.input("Название группы (напр. Объём)")
        gr = ui.checkbox("Обязательная")

        def add_group() -> None:
            if not gn.value:
                return
            try:
                with SessionLocal() as s:
                    ms.create_group(s, gn.value, is_required=gr.value)
            except (ValueError, IntegrityError) as e:
                ui.notify(str(e), color="red")
                return
            gn.value = ""
            refresh()

        ui.button("Создать группу", on_click=add_group)

    with ui.expansion("Привязать группу к товару").classes("w-full max-w-3xl"):
        with SessionLocal() as session:
            prod_opts = {
                p.id: p.name
                for p in session.scalars(
                    select(Product).where(Product.kind == "prepared", Product.is_active)
                ).all()
            }
            grp_opts = {g.id: g.name for g in session.scalars(select(ModifierGroup)).all()}
        ps = ui.select(prod_opts, label="Товар")
        gs = ui.select(grp_opts, label="Группа")

        def do_attach() -> None:
            if not (ps.value and gs.value):
                ui.notify("Выберите товар и группу", color="red")
                return
            try:
                with SessionLocal() as s:
                    ms.attach_group(s, product_id=ps.value, group_id=gs.value)
            except (ValueError, IntegrityError) as e:
                ui.notify(str(e), color="red")
                return
            ui.notify("Привязано")

        ui.button("Привязать", on_click=do_attach)

    refresh()
