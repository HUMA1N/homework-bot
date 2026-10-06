"""Обработчики сообщений, команд и кнопок."""

from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, CallbackQuery, Message

from . import views
from .config import Settings
from .parser import parse_message
from .storage import Storage

log = logging.getLogger(__name__)
router = Router()

COMMANDS = [
    BotCommand(command="today", description="Домашка на сегодня"),
    BotCommand(command="tomorrow", description="Домашка на завтра"),
    BotCommand(command="week", description="Всё на неделю"),
    BotCommand(command="all", description="Все невыполненные"),
    BotCommand(command="help", description="Как пользоваться"),
]


def help_text(settings: Settings) -> str:
    return (
        "Привет! Я записываю домашку и напоминаю о ней.\n\n"
        "<b>Просто напиши задание обычным сообщением:</b>\n"
        "• <code>алгебра №245 на завтра</code>\n"
        "• <code>история параграф 12 к пятнице</code>\n"
        "• <code>англ стр 34 упр 5 до 15.10</code>\n"
        "• <code>литература читать Онегина к 20 октября</code>\n\n"
        "Можно прислать несколько заданий сразу — каждое с новой строки.\n"
        "Если срок не указан, ставлю на завтра.\n\n"
        f"<b>Каждое утро в {settings.morning_time:%H:%M}</b> пришлю список на сегодня, "
        f"<b>вечером в {settings.evening_time:%H:%M}</b> — напомню о невыполненном. "
        "Под списком будут кнопки — отмечай ими, что сделано.\n\n"
        "<b>Команды</b>\n"
        "/today — на сегодня\n"
        "/tomorrow — на завтра\n"
        "/week — всё на неделю\n"
        "/all — все невыполненные\n"
        "/help — эта подсказка"
    )


NOT_UNDERSTOOD = (
    "Не понял, что это за задание 🤔\n"
    "Напиши предмет, что задали и срок, например:\n"
    "<code>алгебра №245 на завтра</code>"
)


@router.message(CommandStart())
async def cmd_start(message: Message, db: Storage, settings: Settings) -> None:
    db.add_chat(message.chat.id)
    await message.answer(help_text(settings))


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    await message.answer(help_text(settings))


async def _show(message: Message, view: str, db: Storage, settings: Settings) -> None:
    db.add_chat(message.chat.id)
    today = settings.today()
    tasks = views.collect(view, db, message.chat.id, today)
    text, keyboard = views.render(view, tasks, today)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("today"))
async def cmd_today(message: Message, db: Storage, settings: Settings) -> None:
    await _show(message, views.TODAY, db, settings)


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, db: Storage, settings: Settings) -> None:
    await _show(message, views.TOMORROW, db, settings)


@router.message(Command("week"))
async def cmd_week(message: Message, db: Storage, settings: Settings) -> None:
    await _show(message, views.WEEK, db, settings)


@router.message(Command("all"))
async def cmd_all(message: Message, db: Storage, settings: Settings) -> None:
    await _show(message, views.ALL, db, settings)


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer("Не знаю такой команды. Список команд — /help")


@router.message(F.text)
async def add_homework(message: Message, db: Storage, settings: Settings) -> None:
    today = settings.today()
    parsed = parse_message(message.text, today)
    if not parsed:
        await message.answer(NOT_UNDERSTOOD)
        return

    db.add_chat(message.chat.id)
    tasks = [db.add_task(message.chat.id, p.subject, p.description, p.due) for p in parsed]
    note = None
    if not all(p.due_found for p in parsed):
        note = "<i>Срок не указан — поставил на завтра.</i>"
    text, keyboard = views.render(views.ADDED, tasks, today, note=note)
    await message.answer(text, reply_markup=keyboard)


@router.message()
async def other_message(message: Message) -> None:
    await message.answer("Я понимаю только текст. " + NOT_UNDERSTOOD)


@router.callback_query(views.TaskCallback.filter())
async def on_task_button(
    callback: CallbackQuery, callback_data: views.TaskCallback, db: Storage, settings: Settings
) -> None:
    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    task = db.get_task(callback_data.task_id)

    if task is None or task.chat_id != chat_id:
        answer = "Этого задания уже нет"
    elif callback_data.action == "done":
        db.set_done(task.id, True)
        answer = "Отмечено ✅"
    elif callback_data.action == "undo":
        db.set_done(task.id, False)
        answer = "Вернул в невыполненные"
    elif callback_data.action == "del":
        db.delete_task(task.id)
        answer = "Удалено 🗑"
    else:
        answer = "Неизвестная кнопка"

    # Перерисовываем сообщение: те же задания, но с обновлёнными отметками.
    # Если Telegram не прислал содержимое сообщения (удалено или недоступно),
    # просто отвечаем на нажатие.
    if isinstance(callback.message, Message):
        ids = views.task_ids_from_markup(callback.message.reply_markup)
        tasks = db.get_tasks(chat_id, ids)
        view = callback_data.view if callback_data.view in views.TITLES else views.ALL
        text, keyboard = views.render(view, tasks, settings.today())
        with suppress(TelegramBadRequest):  # «message is not modified» и т.п.
            await callback.message.edit_text(text, reply_markup=keyboard)

    await callback.answer(answer)
