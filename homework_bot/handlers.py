"""Обработчики сообщений, команд и кнопок."""

from __future__ import annotations

import logging
from collections import OrderedDict
from contextlib import suppress
from datetime import timedelta
from html import escape
from typing import Any, Awaitable, Callable, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, CallbackQuery, Message

from . import views
from .config import Settings
from .parser import parse_message
from .schedule import CLEAR_WORDS, format_schedule, parse_schedule
from .storage import Photo, Storage, Task

log = logging.getLogger(__name__)
router = Router()

COMMANDS = [
    BotCommand(command="today", description="Домашка на сегодня"),
    BotCommand(command="tomorrow", description="Домашка на завтра"),
    BotCommand(command="week", description="Всё на неделю"),
    BotCommand(command="all", description="Все невыполненные"),
    BotCommand(command="stats", description="Сколько сделано за неделю"),
    BotCommand(command="schedule", description="Расписание уроков"),
    BotCommand(command="help", description="Как пользоваться"),
]


def help_text(settings: Settings) -> str:
    return (
        "Привет! Я записываю домашку и напоминаю о ней.\n\n"
        "<b>Просто напиши задание обычным сообщением:</b>\n"
        "• <code>алгебра №245 на завтра</code>\n"
        "• <code>история параграф 12 к пятнице</code>\n"
        "• <code>англ стр 34 упр 5 до 15.10</code>\n"
        "• <code>физика задачи 3–5 к следующему уроку</code>\n\n"
        "Можно прислать несколько заданий сразу — каждое с новой строки.\n\n"
        "<b>Расписание.</b> Задай его один раз командой /schedule — тогда задание "
        "без срока, «к следующему уроку» или «на завтра», когда завтра этого урока нет, "
        "я поставлю на ближайший урок по предмету. Без расписания ставлю на завтра.\n\n"
        "<b>Фото.</b> Пришли фото задания с подписью, например "
        "<code>геометрия на завтра</code>, — я прикреплю его к записи. "
        "В списках у таких заданий будет 📷 и кнопка, чтобы посмотреть фото.\n\n"
        f"<b>Каждое утро в {settings.morning_time:%H:%M}</b> пришлю список на сегодня, "
        f"<b>вечером в {settings.evening_time:%H:%M}</b> — напомню о невыполненном. "
        "Под списком будут кнопки — отмечай ими, что сделано.\n\n"
        "<b>Команды</b>\n"
        "/today — на сегодня\n"
        "/tomorrow — на завтра\n"
        "/week — всё на неделю\n"
        "/all — все невыполненные\n"
        "/stats — сколько сделано за неделю\n"
        "/schedule — расписание уроков\n"
        "/cancel — отменить ввод расписания или фото\n"
        "/help — эта подсказка"
    )


NOT_UNDERSTOOD = (
    "Не понял, что это за задание 🤔\n"
    "Напиши предмет, что задали и срок, например:\n"
    "<code>алгебра №245 на завтра</code>"
)

SCHEDULE_EXAMPLE = (
    "<code>пн: алгебра, русский, история, англ\n"
    "вт: физика, литература, геометрия\n"
    "ср: химия, алгебра, биология\n"
    "чт: русский, англ, информатика\n"
    "пт: геометрия, история, физра</code>"
)

SCHEDULE_PROMPT = (
    "Пришли расписание одним сообщением — каждый день с новой строки, "
    "уроки через запятую:\n\n"
    f"{SCHEDULE_EXAMPLE}\n\n"
    "Можно и столбиком: строка с днём недели, под ней уроки, по одному на строку.\n"
    "Новое расписание заменит старое. Удалить расписание — напиши <code>очистить</code>, "
    "передумал — /cancel"
)

SCHEDULE_NOT_UNDERSTOOD = (
    "Не нашёл в сообщении дней недели 🤔 Каждая строка должна начинаться с дня, например:\n\n"
    f"{SCHEDULE_EXAMPLE}\n\n"
    "Передумал задавать расписание — /cancel"
)

PHOTO_WAITING = (
    "📷 Фото получил. Теперь напиши, что это за задание, например "
    "<code>алгебра №245 на завтра</code>, — и я прикреплю фото к нему.\n"
    "В следующий раз можно сразу добавить подпись к фото.\n"
    "Передумал — /cancel"
)

UNSUPPORTED_FILE = "Я умею прикреплять к заданиям только фото, картинки и PDF 🙂"


def _schedule_key(chat_id: int) -> str:
    """Ключ в meta: пользователь нажал /schedule, и мы ждём расписание."""
    return f"await_schedule:{chat_id}"


@router.message.outer_middleware()
async def _leave_schedule_input(
    handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
    event: Message,
    data: dict[str, Any],
) -> Any:
    """Любая другая команда отменяет ожидание расписания (/cancel разбирается сам)."""
    text = event.text or ""
    db: Optional[Storage] = data.get("db")
    if db is not None and text.startswith("/") and not text.startswith(("/schedule", "/cancel")):
        db.delete_meta(_schedule_key(event.chat.id))
    return await handler(event, data)


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


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Storage, settings: Settings) -> None:
    db.add_chat(message.chat.id)
    today = settings.today()
    first = today - timedelta(days=6)
    done = db.done_by_subject(message.chat.id, first, today)
    undone = db.undone(message.chat.id)
    overdue = sum(1 for t in undone if t.due < today)
    await message.answer(views.render_stats(done, first, today, len(undone), overdue))


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, command: CommandObject, db: Storage) -> None:
    chat_id = message.chat.id
    db.add_chat(chat_id)
    if command.args:
        # «/schedule» и расписание в том же сообщении.
        await _save_schedule(message, command.args, db)
        return
    schedule = db.get_schedule(chat_id)
    if schedule:
        text = "<b>🗓 Твоё расписание</b>\n\n" + format_schedule(schedule) + "\n\n"
        text += "Чтобы изменить его, " + SCHEDULE_PROMPT[0].lower() + SCHEDULE_PROMPT[1:]
    else:
        text = "<b>🗓 Расписание уроков ещё не задано.</b>\n\n" + SCHEDULE_PROMPT
    db.set_meta(_schedule_key(chat_id), "1")
    await message.answer(text)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, db: Storage) -> None:
    key = _schedule_key(message.chat.id)
    waited_schedule = db.get_meta(key) is not None
    db.delete_meta(key)
    photos = db.pop_pending_photos(message.chat.id)
    text = "Отменил." if photos or waited_schedule else "Отменять нечего 🙂"
    await message.answer(text + " Список команд — /help")


async def _save_schedule(message: Message, text: str, db: Storage) -> None:
    chat_id = message.chat.id
    if _is_clear_command(text):
        db.set_schedule(chat_id, {})
        db.delete_meta(_schedule_key(chat_id))
        await message.answer("🗑 Расписание удалено. Задания без срока буду ставить на завтра.")
        return

    schedule = parse_schedule(text)
    if not any(schedule.values()):
        await message.answer(SCHEDULE_NOT_UNDERSTOOD)
        return
    db.set_schedule(chat_id, schedule)
    db.delete_meta(_schedule_key(chat_id))
    await message.answer(
        "✅ <b>Расписание сохранено</b>\n\n"
        + format_schedule(schedule)
        + "\n\nТеперь задания без срока и «к следующему уроку» ставлю на ближайший урок "
        "по предмету. Посмотреть или изменить расписание — /schedule"
    )


def _is_clear_command(text: str) -> bool:
    return text.strip().strip(".!").lower() in CLEAR_WORDS


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer("Не знаю такой команды. Список команд — /help")


def _create_tasks(
    chat_id: int, text: str, db: Storage, settings: Settings, photos: list[Photo]
) -> tuple[list[Task], list[str]]:
    """Записывает задания из текста и прикрепляет к ним фото.

    Возвращает задания и пояснения к сроку. Пустой список — текст не похож на задание.
    """
    schedule = db.get_schedule(chat_id)
    parsed = parse_message(text, settings.today(), schedule)
    if not parsed:
        return [], []

    db.add_chat(chat_id)
    photos = photos + db.pop_pending_photos(chat_id)
    ids = []
    for p in parsed:
        task = db.add_task(chat_id, p.subject, p.description, p.due)
        for photo in photos:
            db.add_photo(task.id, photo)
        ids.append(task.id)

    notes = views.due_notes(parsed, has_schedule=bool(schedule))
    if photos:
        notes.append("📷 Фото прикреплено — посмотреть его можно кнопкой 📷.")
    return db.get_tasks(chat_id, ids), notes


async def _reply_added(
    message: Message, tasks: list[Task], notes: list[str], settings: Settings
) -> None:
    text, keyboard = views.render(
        views.ADDED, tasks, settings.today(), note="\n".join(notes) or None
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(F.text)
async def on_text(message: Message, db: Storage, settings: Settings) -> None:
    chat_id = message.chat.id
    waiting_schedule = db.get_meta(_schedule_key(chat_id)) is not None
    if waiting_schedule and (
        _is_clear_command(message.text) or any(parse_schedule(message.text).values())
    ):
        await _save_schedule(message, message.text, db)
        return

    tasks, notes = _create_tasks(chat_id, message.text, db, settings, photos=[])
    if not tasks:
        await message.answer(SCHEDULE_NOT_UNDERSTOOD if waiting_schedule else NOT_UNDERSTOOD)
        return
    if waiting_schedule:
        # Посмотрел расписание и просто пишет домашку — не мешаем.
        db.delete_meta(_schedule_key(chat_id))
        notes.append(
            "<i>Расписание не менял: в сообщении нет дней недели. Изменить — /schedule</i>"
        )
    await _reply_added(message, tasks, notes, settings)


# --------------------------------------------------------------------------
# Фото заданий
# --------------------------------------------------------------------------
# Несколько фото, отправленных разом (альбом), приходят отдельными сообщениями
# с одинаковым media_group_id, а подпись есть только у одного из них.
# Запоминаем, куда ушли первые фото альбома: список заданий или None —
# «ждут подписи» (и мы уже попросили её написать).
_albums: OrderedDict[str, Optional[list[int]]] = OrderedDict()
MAX_ALBUMS = 500


def _remember_album(group_id: Optional[str], task_ids: Optional[list[int]]) -> None:
    if group_id is None:
        return
    _albums[group_id] = task_ids
    while len(_albums) > MAX_ALBUMS:
        _albums.popitem(last=False)


def _photo_from(message: Message) -> Optional[Photo]:
    if message.photo:
        return Photo(message.photo[-1].file_id, "photo")  # самый большой размер
    document = message.document
    if document and (document.mime_type or "").startswith(("image/", "application/pdf")):
        return Photo(document.file_id, "document")
    return None


def _replied_task(message: Message, db: Storage) -> Optional[Task]:
    """Задание, на сообщение бота о котором ответили фото (если оно там одно)."""
    reply = message.reply_to_message
    if reply is None or reply.from_user is None or not reply.from_user.is_bot:
        return None
    tasks = db.get_tasks(message.chat.id, views.task_ids_from_markup(reply.reply_markup))
    return tasks[0] if len(tasks) == 1 else None


@router.message(F.photo | F.document)
async def on_photo(message: Message, db: Storage, settings: Settings) -> None:
    photo = _photo_from(message)
    if photo is None:
        await message.answer(UNSUPPORTED_FILE)
        return
    chat_id = message.chat.id
    group_id = message.media_group_id

    if group_id is not None and group_id in _albums:
        # Следующее фото альбома — туда же, куда первое, и без лишних ответов.
        task_ids = _albums[group_id]
        if task_ids is None:
            db.add_pending_photo(chat_id, photo)
        for task_id in task_ids or []:
            db.add_photo(task_id, photo)
        return

    # Альбом запоминаем до ответа пользователю, чтобы остальные фото альбома
    # точно знали, куда им идти.
    if message.caption and message.caption.strip():
        tasks, notes = _create_tasks(chat_id, message.caption, db, settings, photos=[photo])
        if tasks:
            _remember_album(group_id, [t.id for t in tasks])
            await _reply_added(message, tasks, notes, settings)
            return

    task = _replied_task(message, db)
    if task is not None:
        if not db.add_photo(task.id, photo):
            await message.answer("К этому заданию уже прикреплено слишком много фото.")
            return
        _remember_album(group_id, [task.id])
        text, keyboard = views.render(
            views.ADDED, db.get_tasks(chat_id, [task.id]), settings.today(),
            note="📷 Прикрепил фото к заданию.",
        )
        await message.answer(text, reply_markup=keyboard)
        return

    db.add_pending_photo(chat_id, photo)
    _remember_album(group_id, None)
    await message.answer(PHOTO_WAITING)


@router.message()
async def other_message(message: Message) -> None:
    await message.answer("Я понимаю только текст и фото. " + NOT_UNDERSTOOD)


async def _send_photos(bot: Bot, chat_id: int, task: Task, db: Storage, settings: Settings) -> bool:
    photos = db.task_photos(task.id)
    caption = f"📷 <b>{escape(task.subject)}</b>"
    if task.description:
        caption += f" — {escape(task.description[: views.MAX_DESCRIPTION])}"
    caption += f"\n{views.format_day(task.due, settings.today())}"
    sent = False
    for number, photo in enumerate(photos):
        send = bot.send_photo if photo.kind == "photo" else bot.send_document
        try:
            await send(chat_id, photo.file_id, caption=caption if number == 0 else None)
            sent = True
        except TelegramBadRequest:
            log.warning("Не удалось отправить фото задания %s", task.id, exc_info=True)
    return sent


@router.callback_query(views.TaskCallback.filter())
async def on_task_button(
    callback: CallbackQuery,
    callback_data: views.TaskCallback,
    db: Storage,
    settings: Settings,
    bot: Bot,
) -> None:
    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    task = db.get_task(callback_data.task_id)

    if task is None or task.chat_id != chat_id:
        answer = "Этого задания уже нет"
    elif callback_data.action == "photo":
        sent = await _send_photos(bot, chat_id, task, db, settings)
        await callback.answer(None if sent else "Не получилось показать фото 😕")
        return
    elif callback_data.action == "done":
        db.set_done(task.id, True, on=settings.today())
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
