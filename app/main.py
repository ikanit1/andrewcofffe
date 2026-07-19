import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
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
        yield
        if bot_task is not None:
            bot_task.cancel()

    app = FastAPI(title="Coffee POS", lifespan=lifespan)
    init_db()

    @app.get("/health")
    def health():
        return {"status": "ok"}

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:create_app", factory=True, host="0.0.0.0", port=8080)
