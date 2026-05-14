from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from app.bot import register_handlers
from app.config import get_settings
from app.llm import OllamaGenerator
from app.logging_config import setup_logging
from app.models import make_session_factory
from app.ozon_client import OzonClient
from app.service import PostService


def build_app() -> tuple[Application, AsyncIOScheduler]:
    settings = get_settings()
    setup_logging(settings.log_level)

    session_factory = make_session_factory(settings.database_url)
    ozon = OzonClient(
        settings.ozon_client_id,
        settings.ozon_api_key,
        settings.ozon_base_url,
        visibility=settings.ozon_visibility,
    )
    generator = OllamaGenerator(
        settings.ollama_base_url,
        settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
        num_predict=settings.ollama_num_predict,
    )
    service = PostService(settings, session_factory, ozon, generator)

    app = Application.builder().token(settings.telegram_bot_token).build()
    register_handlers(app, service, settings)

    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        service.sync_and_prepare,
        "interval",
        minutes=settings.post_interval_minutes,
        args=[app],
        id="sync_and_prepare",
        replace_existing=True,
    )
    return app, scheduler


def main() -> None:
    app, scheduler = build_app()
    scheduler.start()
    logging.getLogger(__name__).info("Bot started")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
