from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Product
from app.services import images

_PRODUCT_UPDATABLE_FIELDS = {
    "name",
    "category_id",
    "kind",
    "price_tiyn",
    "inventory_policy",
    "ingredient_id",
    "sort_order",
    "is_active",
}


def _validate_kind(kind: str) -> None:
    if kind not in ("prepared", "retail"):
        raise ValueError(f"Неизвестный тип товара: {kind}")


def _validate_inventory_policy(policy: str) -> None:
    if policy not in ("track", "untracked"):
        raise ValueError(f"Неизвестный режим склада: {policy}")


def create_category(session: Session, name: str, sort_order: int = 0) -> Category:
    cat = Category(name=name, sort_order=sort_order)
    session.add(cat)
    session.commit()
    return cat


def rename_category(session: Session, category_id: int, name: str) -> Category:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажите название категории")
    cat = session.get(Category, category_id)
    if cat is None:
        raise ValueError("Категория не найдена")
    clash = session.query(Category).filter(
        Category.name == name, Category.id != category_id).first()
    if clash:
        raise ValueError(f"Категория «{name}» уже есть")
    old_name = cat.name
    cat.name = name
    _rename_matching_stock_category(session, old_name, name)
    session.commit()
    return cat


def _rename_matching_stock_category(session: Session, old_name: str, new_name: str) -> None:
    """Тянет за категорией меню одноимённый раздел склада.

    Разделы склада заводятся по именам категорий меню (см. create_product_with_stock).
    Без этого переименование их разводит: новые товары идут в раздел с новым
    именем, а прежние остаются в разделе со старым, и на складе появляются
    два раздела с одним смыслом.
    """
    from app.models import Ingredient, StockCategory

    source = next((c for c in session.query(StockCategory).all()
                   if c.name.strip().lower() == old_name.strip().lower()), None)
    if source is None:
        return
    target = next((c for c in session.query(StockCategory).all()
                   if c.id != source.id
                   and c.name.strip().lower() == new_name.strip().lower()), None)
    if target is None:
        source.name = new_name
        return
    # Раздел с новым именем уже есть — сводим позиции в него, дубль убираем.
    session.query(Ingredient).filter(Ingredient.category_id == source.id).update(
        {Ingredient.category_id: target.id}, synchronize_session=False)
    session.delete(source)


def delete_category(session: Session, category_id: int,
                    *, move_to_id: int | None = None) -> int:
    """Удаляет категорию меню. Возвращает, сколько товаров перенесено.

    Товар обязан лежать в категории (столбец NOT NULL), поэтому удалить
    непустую категорию можно только указав, куда переселить товары. Иначе
    отказ: молча удалить вместе с товарами значило бы потерять и продажи по ним.
    """
    cat = session.get(Category, category_id)
    if cat is None:
        raise ValueError("Категория не найдена")
    products = session.query(Product).filter(Product.category_id == category_id)
    count = products.count()
    if count:
        if move_to_id is None:
            raise ValueError(
                f"В категории {count} товаров — выберите, куда их перенести")
        if move_to_id == category_id:
            raise ValueError("Нельзя перенести товары в удаляемую категорию")
        if session.get(Category, move_to_id) is None:
            raise ValueError("Категория для переноса не найдена")
        products.update({Product.category_id: move_to_id}, synchronize_session=False)
    session.delete(cat)
    session.commit()
    return count


def create_product(
    session: Session,
    *,
    name: str,
    category_id: int,
    kind: str,
    price_tiyn: int,
    ingredient_id: int | None = None,
    sort_order: int = 0,
) -> Product:
    _validate_kind(kind)
    if price_tiyn <= 0:
        raise ValueError("Цена должна быть больше нуля")
    p = Product(
        name=name,
        category_id=category_id,
        kind=kind,
        price_tiyn=price_tiyn,
        ingredient_id=ingredient_id,
        sort_order=sort_order,
    )
    session.add(p)
    session.commit()
    return p


def create_product_with_stock(
    session: Session, *, name: str, category_id: int, kind: str, price_tiyn: int,
    stock_category_id: int | None = None,
) -> Product:
    """Создаёт товар и для штучного сразу заводит позицию склада с тем же именем.

    Без привязки штучный товар продаётся, но остаток не уменьшается, и делает
    это молча — именно так в меню накопились десятки несписывающихся позиций.
    Поэтому связка создаётся здесь, а не оставляется на память владельца.

    Если позиция с таким именем уже есть, берём её, а не заводим вторую: две
    позиции под одно блюдо разводят остатки по разным счётчикам.

    Раздел склада по умолчанию повторяет категорию меню и заводится при
    необходимости. Иначе новая позиция падает в «Без раздела» в самый низ
    длинного списка, и владелец решает, что она вообще не создалась.
    """
    from app.models import Ingredient, StockCategory  # склад не нужен остальным

    ingredient_id = None
    if kind == "retail":
        clean = (name or "").strip()
        if stock_category_id is None:
            cat = session.get(Category, category_id)
            if cat is not None:
                target = cat.name.strip().casefold()
                sc = next((c for c in session.query(StockCategory).all()
                           if c.name.strip().casefold() == target), None)
                if sc is None:
                    sc = StockCategory(name=cat.name.strip(), sort_order=cat.sort_order)
                    session.add(sc)
                    session.flush()
                stock_category_id = sc.id
        # Сравнение регистра делаем в Python, а не через SQL lower(): встроенный
        # lower() в SQLite работает только с латиницей, и «Брауни» не совпал бы
        # с «брауни» — завелась бы вторая позиция под то же блюдо.
        target = clean.casefold()
        ing = next((i for i in session.query(Ingredient).all()
                    if i.name.strip().casefold() == target), None)
        if ing is None:
            ing = Ingredient(name=clean, unit="шт", stock_qty=0, avg_cost_tiyn=0.0,
                             low_stock_threshold=0, category_id=stock_category_id)
            session.add(ing)
            session.flush()
        ingredient_id = ing.id
    return create_product(session, name=name, category_id=category_id, kind=kind,
                          price_tiyn=price_tiyn, ingredient_id=ingredient_id)


def delete_product(session: Session, product_id: int) -> None:
    """Удаляет товар вместе с тех-картой и привязкой модификаторов.

    Проданный товар удалить нельзя: строки чеков ссылаются на него, и без этой
    связи прошлые продажи перестали бы попадать в свою категорию — отчёты за
    уже закрытые периоды изменились бы задним числом. Такой товар убирают
    из меню (is_active=False): он исчезает с экрана продажи, а история цела.
    """
    from app.models import OrderItem, ProductModifierGroup, RecipeItem

    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"Товар {product_id} не найден")

    sold = session.scalar(
        select(func.count()).select_from(OrderItem).where(OrderItem.product_id == product_id)
    )
    if sold:
        raise ValueError(
            f"«{product.name}» уже продавался ({sold} раз) — удалить нельзя, "
            "иначе изменятся отчёты за прошлые периоды. Уберите его из меню."
        )

    session.query(RecipeItem).filter(RecipeItem.product_id == product_id).delete(
        synchronize_session=False)
    session.query(ProductModifierGroup).filter(
        ProductModifierGroup.product_id == product_id).delete(synchronize_session=False)
    session.delete(product)
    session.commit()


def update_product(session: Session, product_id: int, **fields) -> Product:
    p = session.get(Product, product_id)
    if p is None:
        raise ValueError(f"Товар {product_id} не найден")
    for k in fields:
        if k not in _PRODUCT_UPDATABLE_FIELDS:
            raise ValueError(f"Нет поля {k}")
    if "kind" in fields:
        _validate_kind(fields["kind"])
    if "inventory_policy" in fields:
        _validate_inventory_policy(fields["inventory_policy"])
    if "price_tiyn" in fields and fields["price_tiyn"] <= 0:
        raise ValueError("Цена должна быть больше нуля")
    for k, v in fields.items():
        setattr(p, k, v)
    session.commit()
    return p


def set_product_image(session: Session, product_id: int, data: bytes, mime: str) -> None:
    """Сохраняет фото товара. Тип определяется по содержимому, а не по заголовку:
    /product-image отдаёт файл обратно с сохранённым типом, поэтому доверять
    присланному значению нельзя — см. app/services/images.py."""
    p = session.get(Product, product_id)
    if p is None:
        raise ValueError(f"Товар {product_id} не найден")
    real_mime = images.validate_image(data, claimed_mime=mime)
    p.image = data
    p.image_mime = real_mime
    p.has_image = True
    session.commit()


def clear_product_image(session: Session, product_id: int) -> None:
    p = session.get(Product, product_id)
    if p is None:
        raise ValueError(f"Товар {product_id} не найден")
    p.image = None
    p.image_mime = None
    p.has_image = False
    session.commit()


def get_product_image(session: Session, product_id: int) -> tuple[bytes, str] | None:
    p = session.get(Product, product_id)
    if p is None or not p.has_image or p.image is None:
        return None
    return p.image, p.image_mime or "image/jpeg"


def list_menu(session: Session) -> list[tuple[Category, list[Product]]]:
    """Активные категории с активными товарами, в порядке sort_order."""
    cats = session.scalars(
        select(Category).where(Category.is_active).order_by(Category.sort_order, Category.name)
    ).all()
    result = []
    for cat in cats:
        prods = session.scalars(
            select(Product)
            .where(Product.category_id == cat.id, Product.is_active)
            .order_by(Product.sort_order, Product.name)
        ).all()
        result.append((cat, list(prods)))
    return result


def list_menu_admin(session: Session) -> list[tuple[Category, list[Product]]]:
    """Как list_menu, но включает скрытые товары — экрану редактирования меню
    нужно показывать их приглушёнными с возможностью вернуть, а не прятать совсем."""
    cats = session.scalars(
        select(Category).where(Category.is_active).order_by(Category.sort_order, Category.name)
    ).all()
    result = []
    for cat in cats:
        prods = session.scalars(
            select(Product)
            .where(Product.category_id == cat.id)
            .order_by(Product.sort_order, Product.name)
        ).all()
        result.append((cat, list(prods)))
    return result
