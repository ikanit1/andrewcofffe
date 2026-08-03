from sqlalchemy.orm import Session

from app.models import Product


def unit_cost_tiyn(session: Session, product: Product, modifier_ids: list[int]) -> int:
    """Себестоимость одной единицы товара в тиынах.

    Это закупочная цена самого товара: склад считается штуками из меню, отдельных
    ингредиентов в системе нет. Модификаторы себестоимость не меняют — сироп или
    второй шот отражаются надбавкой к цене, а не расходом со склада.

    Аргумент modifier_ids сохранён, чтобы вызывающий код продажи не разбирался,
    какие товары что учитывают: смысл вызова один и тот же.
    """
    return product.cost_tiyn or 0
