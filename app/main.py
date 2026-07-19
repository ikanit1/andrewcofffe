import asyncio

from fastapi import FastAPI
from nicegui import ui

from app.config import settings
from app.db import init_db


def create_app(start_bot: bool = True) -> FastAPI:
    app = FastAPI(title="Coffee POS")
    init_db()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    if start_bot and settings.bot_token:
        @app.on_event("startup")
        async def _start_bot():
            from app.bot import run_bot

            asyncio.create_task(run_bot())

    from app.ui import register_pages

    register_pages()
    ui.run_with(app, storage_secret="coffee-pos-local", title="Касса")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080)
