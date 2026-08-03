import logging

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# check_same_thread нужен только SQLite; для Postgres на этапе переезда аргумент недопустим
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def enable_sqlite_fk(engine: Engine) -> None:
    """SQLite по умолчанию не проверяет внешние ключи — включаем на каждом соединении.

    Для остальных диалектов (Postgres и т.п.) это не нужно, поэтому листенер
    регистрируется только когда движок реально работает через SQLite.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


enable_sqlite_fk(engine)


def ensure_schema(engine: Engine) -> None:
    """Идемпотентно добавляет недостающие колонки в существующие таблицы SQLite.

    У проекта нет Alembic; Base.metadata.create_all создаёт новые таблицы, но не
    изменяет уже существующие. Здесь добавляем колонки, появившиеся после того, как
    боевая pos.db была создана.

    Рассчитано на single-process запуск приложения: проверка "колонка есть?" и
    ALTER не атомарны, но одновременного старта двух процессов в этом проекте нет.
    """
    if engine.dialect.name != "sqlite":
        return
    from sqlalchemy import text

    wanted = {
        "payments": {
            "provider": "VARCHAR NOT NULL DEFAULT 'manual'",
            "terminal_method": "VARCHAR",
            "transaction_id": "VARCHAR",
        },
        "kaspi_settings": {
            "protection_enabled": "BOOLEAN NOT NULL DEFAULT 1",
        },
        "products": {
            "image": "BLOB",
            "image_mime": "VARCHAR",
            "has_image": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "products": {
            # Склад считается по самому товару: остаток в штуках, порог
            # предупреждения и закупочная цена. NULL в stock_qty означает
            # «этот товар не считаем» (кофе из общих запасов).
            "stock_qty": "INTEGER",
            "low_stock_threshold": "INTEGER NOT NULL DEFAULT 0",
            "low_stock_notified": "BOOLEAN NOT NULL DEFAULT 0",
            "cost_tiyn": "INTEGER NOT NULL DEFAULT 0",
        },
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            present = conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")).fetchone()
            if present is None:
                continue
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col, ddl in columns.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
    _migrate_ingredient_stock_to_products(engine)


def _migrate_ingredient_stock_to_products(engine: Engine) -> None:
    """Склад переехал со складских позиций на сами товары меню.

    Позиции заводились по одной на штучный товар (см. прежний
    create_product_with_stock), поэтому остаток, порог и себестоимость просто
    переезжают в товар — по прямой привязке products.ingredient_id, а где её нет
    — по совпадению названий. Журнал движений переливается той же картой, чтобы
    история приходов и списаний не оборвалась на дате обновления.

    Позиции, которым товар не нашёлся (заведены на складе, но не в меню),
    остаются в отложенной таблице stock_moves_ingredients / ingredients: молча
    выбросить чужой учёт нельзя, а придумать им товар — тем более.
    """
    from sqlalchemy import inspect, text

    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "stock_moves" not in tables:
        return
    if "ingredient_id" not in {c["name"] for c in inspector.get_columns("stock_moves")}:
        return

    from app.models.inventory import StockMove

    with engine.begin() as conn:
        mapping: dict[int, int] = {}
        if "ingredients" in tables:
            # Сопоставление обязано быть взаимно однозначным: если одну позицию
            # отдать двум товарам, её остаток задвоится, а если товару достанутся
            # две позиции — вторая молча затрёт первую.
            taken: set[int] = set()
            # Одну позицию могли привязать к двум товарам-тёзкам, из которых один
            # уже убран из меню. Остаток отдаём тому, с которым работают сегодня,
            # иначе он осядет на скрытом дубле и на складе покажется пустая полка.
            def owner_of(where: str) -> str:
                return ("SELECT p.id FROM products p WHERE " + where +
                        " ORDER BY p.is_active DESC, p.id LIMIT 1")

            # Прямая привязка важнее совпадения имён: имена в меню и на складе
            # могли разойтись после переименования товара.
            for ing_id, product_id in conn.execute(text(
                "SELECT DISTINCT ingredient_id, (" +
                owner_of("p.ingredient_id = products.ingredient_id") +
                ") FROM products WHERE ingredient_id IS NOT NULL"
            )):
                mapping[int(ing_id)] = int(product_id)
                taken.add(int(product_id))
            for ing_id, product_id in conn.execute(text(
                "SELECT i.id, (" +
                owner_of("lower(trim(p.name)) = lower(trim(i.name)) "
                         "AND p.ingredient_id IS NULL") +
                ") FROM ingredients i "
                "WHERE i.id NOT IN (SELECT ingredient_id FROM products "
                "                   WHERE ingredient_id IS NOT NULL)"
            )):
                if product_id is None or int(product_id) in taken:
                    continue
                mapping[int(ing_id)] = int(product_id)
                taken.add(int(product_id))

            for ing_id, product_id in mapping.items():
                conn.execute(
                    text("UPDATE products SET stock_qty = (SELECT stock_qty FROM ingredients WHERE id = :ing), "
                         "low_stock_threshold = (SELECT low_stock_threshold FROM ingredients WHERE id = :ing), "
                         "cost_tiyn = (SELECT CAST(ROUND(avg_cost_tiyn) AS INTEGER) FROM ingredients WHERE id = :ing) "
                         "WHERE id = :prod"),
                    {"ing": ing_id, "prod": product_id},
                )

        conn.execute(text("ALTER TABLE stock_moves RENAME TO stock_moves_ingredients"))

    StockMove.__table__.create(engine)

    if not mapping:
        return
    with engine.begin() as conn:
        moved = 0
        for ing_id, product_id in mapping.items():
            result = conn.execute(
                text("INSERT INTO stock_moves "
                     "(product_id, qty_delta, kind, cost_tiyn, ref_type, ref_id, note, created_at) "
                     "SELECT :prod, qty_delta, kind, cost_tiyn, ref_type, ref_id, note, created_at "
                     "FROM stock_moves_ingredients WHERE ingredient_id = :ing"),
                {"ing": ing_id, "prod": product_id},
            )
            moved += result.rowcount or 0
        left = conn.execute(text("SELECT COUNT(*) FROM stock_moves_ingredients")).scalar() or 0
    logger.info("Склад переведён на товары: перенесено движений %s из %s, "
                "товаров с остатком %s", moved, left, len(mapping))


def init_db() -> None:
    import app.models  # noqa: F401  (регистрирует таблицы)

    Base.metadata.create_all(engine)
    ensure_schema(engine)
