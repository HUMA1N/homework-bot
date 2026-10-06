"""Сборка и запуск бота."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import Settings
from .handlers import COMMANDS, router
from .reminders import run_reminders
from .storage import Storage

log = logging.getLogger(__name__)


async def main(settings: Settings) -> None:
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    db = Storage(settings.db_path)
    try:
        dp = Dispatcher()
        dp.include_router(router)
        # Эти объекты aiogram передаст в обработчики по имени аргумента.
        dp["db"] = db
        dp["settings"] = settings

        me = await bot.get_me()
        await bot.set_my_commands(COMMANDS)
        log.info(
            "Бот @%s запущен. Утренняя рассылка в %s, вечерняя в %s. Остановить: Ctrl+C",
            me.username,
            settings.morning_time.strftime("%H:%M"),
            settings.evening_time.strftime("%H:%M"),
        )

        reminders = asyncio.create_task(run_reminders(bot, db, settings))
        try:
            await dp.start_polling(bot)
        finally:
            reminders.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reminders
    finally:
        await bot.session.close()
        db.close()
