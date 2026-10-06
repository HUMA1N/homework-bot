"""Утренняя рассылка и вечернее напоминание."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from . import views
from .config import Settings
from .storage import Storage

log = logging.getLogger(__name__)

# Если компьютер был выключен или спал во время рассылки, она уйдёт после
# включения — но не позже, чем через столько времени после назначенного.
GRACE = timedelta(hours=3)
TICK_SECONDS = 30


def is_due(now: datetime, at: time, last_sent: Optional[str]) -> bool:
    """Пора ли отправлять рассылку, назначенную на время at.

    last_sent — дата (ГГГГ-ММ-ДД), когда эта рассылка уже уходила в этот чат.
    """
    if last_sent == now.date().isoformat():
        return False
    planned = datetime.combine(now.date(), at, tzinfo=now.tzinfo)
    return planned <= now < planned + GRACE


async def _send_reminder(bot: Bot, db: Storage, settings: Settings, chat_id: int, kind: str) -> None:
    today = settings.today()
    view = views.MORNING if kind == "morning" else views.EVENING
    tasks = views.collect(view, db, chat_id, today)
    # Вечером пишем, только если есть что доделать.
    if view == views.EVENING and not tasks:
        return
    text, keyboard = views.render(view, tasks, today)
    await bot.send_message(chat_id, text, reply_markup=keyboard)


async def check_reminders(bot: Bot, db: Storage, settings: Settings) -> None:
    now = settings.now()
    schedule = {"morning": settings.morning_time, "evening": settings.evening_time}
    for kind, at in schedule.items():
        for chat_id in db.chat_ids():
            key = f"{kind}:{chat_id}"
            if not is_due(now, at, db.get_meta(key)):
                continue
            try:
                await _send_reminder(bot, db, settings, chat_id, kind)
            except TelegramForbiddenError:
                log.info("Чат %s заблокировал бота — больше не пишем туда", chat_id)
                db.remove_chat(chat_id)
                continue
            except TelegramRetryAfter as e:
                log.warning("Telegram просит подождать %s с", e.retry_after)
                await asyncio.sleep(e.retry_after)
                continue  # попробуем ещё раз на следующей проверке
            except Exception:
                log.exception("Не удалось отправить напоминание в чат %s", chat_id)
                continue  # попробуем ещё раз на следующей проверке
            db.set_meta(key, now.date().isoformat())
            await asyncio.sleep(0.05)  # не упираемся в лимиты Telegram


async def run_reminders(bot: Bot, db: Storage, settings: Settings) -> None:
    """Бесконечный цикл: раз в полминуты проверяем, не пора ли что-то отправить.

    Смотрим на часы, а не спим до нужного момента — так рассылка не потеряется,
    если компьютер уходил в спящий режим.
    """
    while True:
        try:
            await check_reminders(bot, db, settings)
        except Exception:
            log.exception("Ошибка при проверке напоминаний")
        await asyncio.sleep(TICK_SECONDS)
