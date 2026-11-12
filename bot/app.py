"""Спільна логіка для serverless-режиму (Vercel): вебхук Telegram і тік нагадувань."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from . import config, db, handlers, scheduler
from .storage import DbStorage

log = logging.getLogger("app")

_ready = False
_dp: Dispatcher | None = None


def setup():
    """Одноразова ініціалізація на холодний старт: з'єднання з БД і диспетчер."""
    global _ready, _dp
    if not _ready:
        db.init_from_env()
        _dp = Dispatcher(storage=DbStorage())
        _dp.include_router(handlers.router)
        _ready = True
    return _dp


async def process_update(data: dict) -> None:
    dp = setup()
    bot = Bot(config.BOT_TOKEN)
    try:
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        # Завжди відповідаємо 200, щоб Telegram не повторював збійний апдейт без кінця
        log.exception("update failed")
    finally:
        await bot.session.close()


async def run_tick() -> None:
    setup()
    bot = Bot(config.BOT_TOKEN)
    try:
        await scheduler.tick(bot)
    finally:
        await bot.session.close()
