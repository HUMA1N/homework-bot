"""Списки заданий: какие задания показать, текст сообщения и кнопки под ним."""

from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Optional

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .parser import DUE_FALLBACK, DUE_LESSON, DUE_MOVED, ParsedTask
from .storage import Storage, Task

# Виды списков. Код вида хранится в кнопках, чтобы после нажатия
# перерисовать сообщение с тем же заголовком.
MORNING = "m"   # утренняя рассылка
EVENING = "e"   # вечернее напоминание
TODAY = "t"     # /today
TOMORROW = "n"  # /tomorrow
WEEK = "w"      # /week
ALL = "a"       # /all
ADDED = "x"     # ответ на новое задание

TITLES = {
    MORNING: "☀️ Доброе утро! Вот что сдавать сегодня:",
    EVENING: "🌙 Не забудь доделать:",
    TODAY: "📚 Домашка на сегодня",
    TOMORROW: "📚 Домашка на завтра",
    WEEK: "🗓 Домашка на неделю",
    ALL: "📋 Все невыполненные задания",
    ADDED: "📌 Записал!",
}

EMPTY = {
    MORNING: "☀️ Доброе утро! Сегодня ничего сдавать не нужно 🎉",
    EVENING: "🌙 Всё сделано, можно отдыхать 🎉",
    TODAY: "На сегодня заданий нет 🎉",
    TOMORROW: "На завтра заданий нет 🎉",
    WEEK: "На ближайшую неделю заданий нет 🎉",
    ALL: "Невыполненных заданий нет 🎉",
    ADDED: "🗑 Задание удалено. Если нужно — напиши его заново.",
}

ADDED_FOOTER = "<i>Если я что-то понял не так — нажми 🗑 и напиши задание заново.</i>"

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

# Лимиты Telegram: 4096 символов в сообщении и 100 кнопок под ним.
MAX_DESCRIPTION = 200
MAX_TASKS = 40
MAX_TEXT = 3600


class TaskCallback(CallbackData, prefix="task"):
    action: str  # done | undo | del | photo
    task_id: int
    view: str


def collect(view: str, db: Storage, chat_id: int, today: date) -> list[Task]:
    """Задания, которые нужно показать в списке данного вида."""
    tomorrow = today + timedelta(days=1)
    if view in (MORNING, TODAY):
        return db.overdue(chat_id, today) + db.tasks_between(chat_id, today, today)
    if view == TOMORROW:
        return db.tasks_between(chat_id, tomorrow, tomorrow)
    if view == EVENING:
        return db.overdue(chat_id, today) + db.tasks_between(
            chat_id, today, tomorrow, only_undone=True
        )
    if view == WEEK:
        return db.overdue(chat_id, today) + db.tasks_between(
            chat_id, today, today + timedelta(days=6)
        )
    if view == ALL:
        return db.undone(chat_id)
    raise ValueError(f"Неизвестный вид списка: {view!r}")


def due_notes(parsed: list[ParsedTask], has_schedule: bool) -> list[str]:
    """Пояснения под новым заданием: откуда взялся срок, если его не было в сообщении."""
    notes: list[str] = []
    for task in parsed:
        name = escape(task.subject)
        if task.due_rule == DUE_LESSON and not task.due_found:
            note = "Срок не указан — поставил на ближайший урок по расписанию."
        elif task.due_rule == DUE_MOVED:
            note = f"Завтра урока «{name}» нет — поставил на ближайший урок по расписанию."
        elif task.due_rule == DUE_FALLBACK and has_schedule:
            note = f"Урока «{name}» нет в расписании — поставил на завтра."
        elif task.due_rule == DUE_FALLBACK and task.due_found:
            note = ("Расписание уроков ещё не задано — поставил на завтра. "
                    "Задай его командой /schedule, и я буду ставить задания на ближайший урок.")
        elif task.due_rule == DUE_FALLBACK:
            note = "Срок не указан — поставил на завтра."
        else:
            continue
        if note not in notes:
            notes.append(note)
    return [f"<i>{note}</i>" for note in notes]


def format_day(day: date, today: date) -> str:
    """«Завтра — ср, 7 октября», «Пятница, 9 октября», «⚠️ Просрочено — пн, 5 октября»."""
    short = f"{WEEKDAYS_SHORT[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"
    full = f"{WEEKDAYS[day.weekday()].capitalize()}, {day.day} {MONTHS[day.month - 1]}"
    if day.year != today.year:
        short += f" {day.year}"
        full += f" {day.year}"
    delta = (day - today).days
    if delta < 0:
        return f"⚠️ Просрочено — {short}"
    if delta == 0:
        return f"Сегодня — {short}"
    if delta == 1:
        return f"Завтра — {short}"
    if delta == 2:
        return f"Послезавтра — {short}"
    return full


def _task_line(task: Task) -> str:
    text = f"<b>{escape(task.subject)}</b>"
    description = task.description
    if len(description) > MAX_DESCRIPTION:
        description = description[: MAX_DESCRIPTION - 1] + "…"
    if description:
        text += f" — {escape(description)}"
    line = f"✅ <s>{text}</s>" if task.done else f"⬜ {text}"
    if task.photos:
        line += " 📷"
    return line


def render(
    view: str, tasks: list[Task], today: date, note: Optional[str] = None
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Текст сообщения и кнопки «сделано» для списка заданий.

    note — необязательная строка-пояснение под списком.
    """
    if not tasks:
        return EMPTY[view], None

    tasks = sorted(tasks, key=lambda t: (t.due, t.id))
    numbered = len(tasks) > 1
    lines = [f"<b>{TITLES[view]}</b>"]
    length = len(lines[0])
    shown: list[Task] = []
    for task in tasks:
        new_lines = []
        if not shown or shown[-1].due != task.due:
            new_lines += ["", f"<b>{format_day(task.due, today)}</b>"]
        prefix = f"{len(shown) + 1}. " if numbered else ""
        new_lines.append(prefix + _task_line(task))
        added = sum(len(line) + 1 for line in new_lines)
        if len(shown) >= MAX_TASKS or length + added > MAX_TEXT:
            break
        lines += new_lines
        length += added
        shown.append(task)

    hidden = len(tasks) - len(shown)
    if hidden:
        lines += ["", f"…и ещё {hidden} — не поместились в сообщение. Отметь сделанные, "
                      "и в следующем списке будут остальные."]
    if note:
        lines += ["", note]
    if view == ADDED:
        lines += ["", ADDED_FOOTER]
    elif all(t.done for t in tasks):
        lines += ["", "🎉 Всё сделано!"]

    return "\n".join(lines), _keyboard(view, shown)


def _keyboard(view: str, tasks: list[Task]) -> InlineKeyboardMarkup:
    """По ряду кнопок на задание: «сделано», а ещё «удалить» под новым заданием
    и «фото», если к заданию прикреплены фото."""
    builder = InlineKeyboardBuilder()
    numbered = len(tasks) > 1
    for number, task in enumerate(tasks, start=1):
        if numbered:
            name = f"{number}. {task.subject}"
            done_text, undo_text = f"✅ {name}", f"↩️ {name}"
            del_text, photo_text = f"🗑 {number}", f"📷 {number}"
        else:
            done_text, undo_text = "✅ Сделано", "↩️ Не сделано"
            del_text, photo_text = "🗑 Удалить", "📷 Фото"

        def button(text: str, action: str) -> InlineKeyboardButton:
            return InlineKeyboardButton(
                text=text,
                callback_data=TaskCallback(action=action, task_id=task.id, view=view).pack(),
            )

        row = [button(undo_text, "undo") if task.done else button(done_text, "done")]
        if view == ADDED:
            row.append(button(del_text, "del"))
        if task.photos:
            row.append(button(photo_text, "photo"))
        builder.row(*row)
    return builder.as_markup()


def task_ids_from_markup(markup: Optional[InlineKeyboardMarkup]) -> list[int]:
    """Номера заданий, кнопки которых есть под сообщением."""
    ids: list[int] = []
    if markup is None:
        return ids
    for row in markup.inline_keyboard:
        for button in row:
            if not button.callback_data:
                continue
            try:
                data = TaskCallback.unpack(button.callback_data)
            except (TypeError, ValueError):
                continue
            if data.task_id not in ids:
                ids.append(data.task_id)
    return ids


def render_stats(
    done: list[tuple[str, int]], first: date, last: date, undone: int, overdue: int
) -> str:
    """Текст для /stats: сколько сделано за период по предметам."""
    period = f"{first.day} {MONTHS[first.month - 1]} — {last.day} {MONTHS[last.month - 1]}"
    lines = [f"<b>📊 Статистика за неделю</b> ({period})", ""]
    total = sum(n for _, n in done)
    if total:
        lines.append(f"Сделано заданий: <b>{total}</b>")
        lines.append("")
        top = max(n for _, n in done)
        for subject, n in done:
            bar = "▰" * max(1, round(n / top * 10))
            lines.append(f"{bar} <b>{escape(subject)}</b> — {n}")
    else:
        lines.append("За эту неделю пока ничего не отмечено сделанным.")
        lines.append("Нажимай ✅ под заданиями — и здесь появится статистика.")
    lines.append("")
    if undone:
        line = f"Ещё не сделано: <b>{undone}</b>"
        if overdue:
            line += f", из них просрочено: <b>{overdue}</b> ⚠️"
        lines.append(line + " — список: /all")
    else:
        lines.append("Невыполненных заданий нет 🎉")
    return "\n".join(lines)
