"""Бот целиком: обновления от «Telegram» проходят через aiogram и обработчики.

Вместо настоящего Telegram — FakeSession: она запоминает, что бот пытался
отправить, и отвечает так, будто всё отправилось.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import count
from pathlib import Path

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    SendDocument,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    Document,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    Update,
    User,
)

from homework_bot import handlers
from homework_bot.config import Settings
from homework_bot.storage import Storage

TODAY = date(2026, 10, 6)  # вторник
CHAT = 42
USER = User(id=CHAT, is_bot=False, first_name="Маша")
BOT_USER = User(id=1, is_bot=True, first_name="Домашка", username="homework_bot")
TZ = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class FixedSettings(Settings):
    """Настройки, в которых «сегодня» всегда TODAY."""

    def now(self) -> datetime:
        return datetime.combine(TODAY, time(12, 0), tzinfo=TZ)


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._ids = count(1000)

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendPhoto, SendDocument, EditMessageText)):
            return Message(
                message_id=next(self._ids),
                date=datetime.now(TZ),
                chat=Chat(id=method.chat_id or CHAT, type="private"),
                from_user=BOT_USER,
                text=getattr(method, "text", None),
                reply_markup=method.reply_markup,
            )
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self) -> None:
        pass


@pytest.fixture(scope="module")
def dispatcher():
    dp = Dispatcher()
    dp.include_router(handlers.router)
    return dp


class Client:
    """Пишет боту от имени пользователя и смотрит, что бот ответил."""

    def __init__(self, dp: Dispatcher, db: Storage) -> None:
        self.dp = dp
        self.db = db
        self.session = FakeSession()
        self.bot = Bot("1:TEST", session=self.session,
                       default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self._ids = count(1)
        dp["db"] = db
        dp["settings"] = FixedSettings(
            bot_token="1:TEST", morning_time=time(7, 30), evening_time=time(20, 0),
            timezone=TZ, db_path=Path(":memory:"),
        )

    async def _feed(self, **kwargs) -> list[TelegramMethod]:
        before = len(self.session.calls)
        await self.dp.feed_update(self.bot, Update(update_id=next(self._ids), **kwargs))
        return self.session.calls[before:]

    def _message(self, **kwargs) -> Message:
        return Message(
            message_id=next(self._ids), date=datetime.now(TZ),
            chat=Chat(id=CHAT, type="private"), from_user=USER, **kwargs,
        )

    async def send(self, text: str) -> list[TelegramMethod]:
        return await self._feed(message=self._message(text=text))

    async def send_photo(self, file_id: str, caption=None, **kwargs) -> list[TelegramMethod]:
        sizes = [
            PhotoSize(file_id=f"{file_id}-small", file_unique_id="s", width=90, height=90),
            PhotoSize(file_id=file_id, file_unique_id="b", width=1280, height=960),
        ]
        return await self._feed(message=self._message(photo=sizes, caption=caption, **kwargs))

    async def press(self, reply: SendMessage, button_text: str) -> list[TelegramMethod]:
        buttons = [b for row in reply.reply_markup.inline_keyboard for b in row]
        button = next(b for b in buttons if b.text == button_text)
        message = Message(
            message_id=next(self._ids), date=datetime.now(TZ),
            chat=Chat(id=CHAT, type="private"), from_user=BOT_USER,
            text=reply.text, reply_markup=reply.reply_markup,
        )
        query = CallbackQuery(id="q", from_user=USER, chat_instance="c",
                              data=button.callback_data, message=message)
        return await self._feed(callback_query=query)


@pytest.fixture
def client(dispatcher):
    db = Storage(":memory:")
    yield Client(dispatcher, db)
    db.close()


def only_reply(calls) -> SendMessage:
    assert len(calls) == 1, calls
    assert isinstance(calls[0], SendMessage)
    return calls[0]


def button_texts(reply) -> list[list[str]]:
    markup: InlineKeyboardMarkup = reply.reply_markup
    return [[b.text for b in row] for row in markup.inline_keyboard]


# --- расписание --------------------------------------------------------------

async def test_homework_without_schedule_goes_to_tomorrow(client):
    reply = only_reply(await client.send("алгебра №245"))
    assert "Завтра — ср, 7 октября" in reply.text
    assert "Срок не указан — поставил на завтра." in reply.text


async def test_schedule_then_homework_goes_to_next_lesson(client):
    reply = only_reply(await client.send("/schedule"))
    assert "ещё не задано" in reply.text

    reply = only_reply(await client.send("пн: алгебра, история\nчт: физика"))
    assert "Расписание сохранено" in reply.text
    assert "<b>Понедельник:</b> Алгебра, История" in reply.text
    assert client.db.get_schedule(CHAT) == {0: ["Алгебра", "История"], 3: ["Физика"]}

    reply = only_reply(await client.send("алгебра №245"))
    assert "Понедельник, 12 октября" in reply.text
    assert "поставил на ближайший урок по расписанию" in reply.text

    reply = only_reply(await client.send("физика задачи 1-3 на завтра"))
    assert "Послезавтра — чт, 8 октября" in reply.text
    assert "Завтра урока «Физика» нет" in reply.text

    reply = only_reply(await client.send("/schedule"))
    assert "Твоё расписание" in reply.text


async def test_schedule_in_one_message_with_command(client):
    reply = only_reply(await client.send("/schedule\nср: химия"))
    assert "Расписание сохранено" in reply.text
    assert client.db.get_schedule(CHAT) == {2: ["Химия"]}


async def test_homework_after_viewing_schedule_is_still_homework(client):
    await client.send("/schedule")
    reply = only_reply(await client.send("история §12 к пятнице"))
    assert "Записал" in reply.text
    assert "Расписание не менял" in reply.text
    # Режим ввода расписания закончился.
    assert "Расписание не менял" not in only_reply(await client.send("химия №1")).text


async def test_bad_schedule_and_cancel(client):
    await client.send("/schedule")
    reply = only_reply(await client.send("ну вот"))
    assert "Не нашёл в сообщении дней недели" in reply.text
    assert "Отменил" in only_reply(await client.send("/cancel")).text
    assert "Не понял" in only_reply(await client.send("ну вот")).text


async def test_other_command_leaves_schedule_input(client):
    await client.send("/schedule")
    await client.send("/today")
    assert "Не понял" in only_reply(await client.send("ну вот")).text


async def test_clear_schedule(client):
    await client.send("/schedule\nпн: алгебра")
    await client.send("/schedule")
    reply = only_reply(await client.send("Очистить"))
    assert "Расписание удалено" in reply.text
    assert client.db.get_schedule(CHAT) == {}


# --- фото ----------------------------------------------------------------------

async def test_photo_with_caption_is_attached_and_shown(client):
    reply = only_reply(await client.send_photo("photo-1", caption="геометрия №12 на завтра"))
    assert "<b>Геометрия</b> — №12 📷" in reply.text
    assert button_texts(reply) == [["✅ Сделано", "🗑 Удалить", "📷 Фото"]]

    week = only_reply(await client.send("/week"))
    assert "📷" in week.text
    assert button_texts(week) == [["✅ Сделано", "📷 Фото"]]

    calls = await client.press(week, "📷 Фото")
    photos = [c for c in calls if isinstance(c, SendPhoto)]
    assert [p.photo for p in photos] == ["photo-1"]  # самый большой размер
    assert "Геометрия" in photos[0].caption
    assert any(isinstance(c, AnswerCallbackQuery) for c in calls)


async def test_photo_without_caption_waits_for_text(client):
    reply = only_reply(await client.send_photo("photo-1"))
    assert reply.text == handlers.PHOTO_WAITING
    reply = only_reply(await client.send("химия задача 3 к пятнице"))
    assert "📷" in reply.text
    task = client.db.undone(CHAT)[0]
    assert [p.file_id for p in client.db.task_photos(task.id)] == ["photo-1"]


async def test_cancel_forgets_pending_photo(client):
    await client.send_photo("photo-1")
    assert "Отменил" in only_reply(await client.send("/cancel")).text
    reply = only_reply(await client.send("химия задача 3"))
    assert "📷" not in reply.text


async def test_album_goes_to_one_task_with_one_reply(client):
    calls = await client.send_photo("p1", caption="физика стр 5", media_group_id="album")
    only_reply(calls)
    assert await client.send_photo("p2", media_group_id="album") == []
    task = client.db.undone(CHAT)[0]
    assert [p.file_id for p in client.db.task_photos(task.id)] == ["p1", "p2"]


async def test_album_without_caption_asks_once(client):
    only_reply(await client.send_photo("p1", media_group_id="album2"))
    assert await client.send_photo("p2", media_group_id="album2") == []
    await client.send("биология §3")
    task = client.db.undone(CHAT)[0]
    assert [p.file_id for p in client.db.task_photos(task.id)] == ["p1", "p2"]


async def test_photo_as_reply_to_task_message(client):
    added = only_reply(await client.send("алгебра №245 на завтра"))
    bot_message = Message(
        message_id=500, date=datetime.now(TZ), chat=Chat(id=CHAT, type="private"),
        from_user=BOT_USER, text=added.text, reply_markup=added.reply_markup,
    )
    reply = only_reply(await client.send_photo("photo-9", reply_to_message=bot_message))
    assert "Прикрепил фото" in reply.text
    task = client.db.undone(CHAT)[0]
    assert [p.file_id for p in client.db.task_photos(task.id)] == ["photo-9"]


async def test_pdf_document_is_attached(client):
    document = Document(file_id="doc-1", file_unique_id="d", mime_type="application/pdf")
    message = client._message(document=document, caption="литература стихи к пятнице")
    reply = only_reply(await client._feed(message=message))
    assert "📷" in reply.text
    task = client.db.undone(CHAT)[0]
    calls = await client.press(only_reply(await client.send("/all")), "📷 Фото")
    assert [c.document for c in calls if isinstance(c, SendDocument)] == ["doc-1"]
    assert task.photos == 1


async def test_unsupported_document(client):
    document = Document(file_id="z", file_unique_id="z", mime_type="application/zip")
    reply = only_reply(await client._feed(message=client._message(document=document)))
    assert reply.text == handlers.UNSUPPORTED_FILE


# --- кнопки и статистика -------------------------------------------------------

async def test_done_button_and_stats(client):
    added = only_reply(await client.send("алгебра №1 на завтра\nалгебра №2 к пятнице\nистория §3"))
    calls = await client.press(added, "✅ 1. Алгебра")
    edit = next(c for c in calls if isinstance(c, EditMessageText))
    assert "✅ <s><b>Алгебра</b>" in edit.text
    await client.press(added, "✅ 2. История")
    await client.press(added, "✅ 3. Алгебра")

    stats = only_reply(await client.send("/stats"))
    assert "Статистика за неделю" in stats.text
    assert "30 сентября — 6 октября" in stats.text
    assert "Сделано заданий: <b>3</b>" in stats.text
    assert stats.text.index("Алгебра</b> — 2") < stats.text.index("История</b> — 1")
    assert "Невыполненных заданий нет" in stats.text


async def test_stats_empty(client):
    await client.send("алгебра №1 к пятнице")
    stats = only_reply(await client.send("/stats"))
    assert "пока ничего не отмечено" in stats.text
    assert "Ещё не сделано: <b>1</b>" in stats.text


async def test_help_lists_new_commands(client):
    text = only_reply(await client.send("/help")).text
    for command in ("/stats", "/schedule", "/cancel"):
        assert command in text


async def test_unknown_command(client):
    assert "Не знаю такой команды" in only_reply(await client.send("/foo")).text
