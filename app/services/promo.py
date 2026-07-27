"""Акции по времени суток.

Утренняя акция кофейни: с 08:30 до 11:00 капучино, флэт-уайт и латте стоят
990 тг за 0.3 л и 1090 тг за 0.4 л.

Реализовано подменой базовой цены, а не отдельной скидкой: разница между
объёмами в акции — те же 100 тг, что добавляет модификатор «Объём». Поэтому
достаточно поставить базовую 990, и 0.4 л сам станет 1090. Скидка на чек при
этом остаётся свободной — кассир может дать её сверху акции.

Время берётся серверное в Asia/Almaty: цену считает сервер при проведении чека,
а не браузер кассира, иначе сбитые часы на моноблоке меняли бы выручку.
"""
from dataclasses import dataclass
from datetime import datetime, time

from app.timezone import now_almaty, to_almaty


@dataclass(frozen=True)
class Promo:
    name: str
    start: time
    end: time
    price_tiyn: int
    products: tuple[str, ...]  # точные названия товаров, регистр не важен

    def covers(self, product_name: str) -> bool:
        return (product_name or "").strip().lower() in self.products

    def is_active_at(self, moment: datetime) -> bool:
        """Полуинтервал [start, end): в 11:00 акция уже не действует."""
        t = moment.time()
        return self.start <= t < self.end

    @property
    def hours(self) -> str:
        return f"{self.start:%H:%M}–{self.end:%H:%M}"


MORNING_COFFEE = Promo(
    name="Утренний кофе",
    start=time(8, 30),
    end=time(11, 0),
    price_tiyn=99000,  # 990 тг за 0.3 л; 0.4 л даёт модификатор объёма (+100 тг)
    products=("капучино", "латте", "флэтуайт"),
)

PROMOS: tuple[Promo, ...] = (MORNING_COFFEE,)


def active_promo_for(product_name: str, *, now: datetime | None = None) -> Promo | None:
    """Акция, действующая на товар прямо сейчас, или None."""
    moment = to_almaty(now) if now is not None else now_almaty()
    for promo in PROMOS:
        if promo.covers(product_name) and promo.is_active_at(moment):
            return promo
    return None


def effective_price_tiyn(product, *, now: datetime | None = None) -> int:
    """Цена товара с учётом акции. Единственная точка расчёта — и для витрины,
    и для проведения чека, иначе на экране одна цена, а в чеке другая."""
    promo = active_promo_for(product.name, now=now)
    return promo.price_tiyn if promo else product.price_tiyn


def active_promos(*, now: datetime | None = None) -> list[Promo]:
    """Идущие сейчас акции — для плашки на экране продажи."""
    moment = to_almaty(now) if now is not None else now_almaty()
    return [p for p in PROMOS if p.is_active_at(moment)]
