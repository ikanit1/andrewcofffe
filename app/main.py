import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from nicegui import ui

from app.config import settings
from app.db import init_db

logger = logging.getLogger(__name__)


def create_app(start_bot: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bot_task = None
        if start_bot and settings.bot_token:
            from app.bot import run_bot

            bot_task = asyncio.create_task(run_bot())
            bot_task.add_done_callback(_log_bot_exit)
        backup_task = None
        if settings.backup_enabled:
            from app.services.backup_scheduler import run_backup_scheduler

            backup_task = asyncio.create_task(run_backup_scheduler())
            backup_task.add_done_callback(_log_task_exit)
        yield
        if bot_task is not None:
            bot_task.cancel()
        if backup_task is not None:
            backup_task.cancel()

    app = FastAPI(title="Coffee POS", lifespan=lifespan)
    if settings.storage_secret == "change-me-in-env":
        logger.warning("storage_secret не задан (дефолт) — сессии подделываемы; задайте STORAGE_SECRET в .env")
    init_db()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def root():
        return RedirectResponse("/login")

    @app.get("/product-image/{product_id}")
    def product_image(product_id: int):
        from fastapi import Response

        from app.db import SessionLocal
        from app.services.catalog_service import get_product_image
        with SessionLocal() as session:
            img = get_product_image(session, product_id)
        if img is None:
            return Response(status_code=404)
        data, mime = img
        return Response(content=data, media_type=mime)

    from app.ui import register_pages

    register_pages()
    ui.run_with(app, storage_secret=settings.storage_secret, title="Касса")
    return app


def _log_bot_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Telegram-бот упал: %r", exc)


def _log_task_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Фоновая задача упала: %r", exc)


if __name__ == "__main__":
    import uvicorn

    from app.config import settings

    if settings.storage_secret == "change-me-in-env":
        raise SystemExit("Задайте STORAGE_SECRET в .env перед запуском (сейчас дефолтное значение).")

    uvicorn.run("app.main:create_app", factory=True, host="0.0.0.0", port=8080)
