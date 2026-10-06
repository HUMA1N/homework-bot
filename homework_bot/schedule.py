"""Расписание уроков: разбор текста, который присылает пользователь, и вывод.

Пользователь присылает расписание один раз, например:

    пн: алгебра, русский, история
    вт: физика, англ, литература

или по дню на строку с уроками в столбик:

    Понедельник
    1. Алгебра
    2. Русский язык

Модуль не зависит от Telegram и базы данных.
"""

from __future__ import annotations

import re
from html import escape

from .parser import _SUBJECT_REGEXES, Schedule

WEEKDAY_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

# День недели в начале строки: «пн», «Пн.», «понедельник:», «в среду —», «ПТ)».
_DAY_RE = re.compile(
    r"^\s*(?:(?:в|во)\s+)?"
    r"(?P<day>понедельник\w*|пон|пн|вторник\w*|вт|сред[аеуы]|ср|четверг\w*|чет|чт"
    r"|пятниц\w*|пят|пт|суббот\w*|суб|сб|воскресень\w*|вос|вс)"
    r"(?!\w)\.?\s*[:\-—–)]?\s*",
    re.IGNORECASE,
)
_DAY_PREFIXES = (
    ("пон", 0), ("пн", 0), ("вт", 1), ("ср", 2), ("чет", 3), ("чт", 3),
    ("пят", 4), ("пт", 4), ("суб", 5), ("сб", 5), ("вос", 6), ("вс", 6),
)

# Время и номер урока в начале: «8:30», «8.30-9.15», «1.», «2)», «3 -».
_TIME_PREFIX_RE = re.compile(r"^\d{1,2}[:.]\d{2}(?:\s*[-—–]\s*\d{1,2}[:.]\d{2})?\s*[-—–:]?\s*")
_NUMBER_PREFIX_RE = re.compile(r"^\d{1,2}\s*(?:[.)\-—–:]\s*|\s+)")
# «нет уроков», «выходной», «-» — день без уроков.
_NO_LESSONS_RE = re.compile(r"^(?:-+|—|нет(?:\s+урок\w*)?|выходн\w*|ничего)$", re.IGNORECASE)

# Слова, которыми можно очистить расписание.
CLEAR_WORDS = {"очистить", "удалить", "стереть", "сбросить"}

MAX_LESSONS_PER_DAY = 12
MAX_SUBJECT_LENGTH = 60


def normalize_subject(item: str) -> str:
    """«алг» → «Алгебра», «рус яз» → «Русский язык», «хореография» → «Хореография».

    Если строка начинается с известного предмета, берём его: «История России» и
    «Алгебра (каб. 23)» превращаются в «История» и «Алгебра» — так домашка
    «история §5» найдёт свой урок.
    """
    item = " ".join(item.split()).strip(" .,;:—–-")
    best = None
    for name, regex in _SUBJECT_REGEXES:
        m = regex.match(item)
        if m and (best is None or m.end() > best[0]):
            best = (m.end(), name)
    if best is not None:
        return best[1]
    return (item[:1].upper() + item[1:])[:MAX_SUBJECT_LENGTH]


def _day_of(word: str) -> int:
    word = word.lower()
    return next(idx for prefix, idx in _DAY_PREFIXES if word.startswith(prefix))


def _split_lessons(text: str) -> list[str]:
    lessons = []
    for item in re.split(r"[,;/]", text):
        item = item.strip()
        for regex in (_TIME_PREFIX_RE, _NUMBER_PREFIX_RE, _TIME_PREFIX_RE):
            item = regex.sub("", item)
        item = item.strip(" \t.,;:—–-")
        if item and not _NO_LESSONS_RE.match(item):
            lessons.append(normalize_subject(item))
    return lessons


def parse_schedule(text: str) -> Schedule:
    """Разбирает расписание. Пустой словарь — в тексте не нашлось ни одного дня недели."""
    schedule: Schedule = {}
    day = None
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _DAY_RE.match(line)
        if m:
            day = _day_of(m["day"])
            schedule.setdefault(day, [])
            line = line[m.end():]
        if day is None:
            continue  # строки до первого дня недели («Моё расписание:») пропускаем
        schedule[day].extend(_split_lessons(line))
        schedule[day] = schedule[day][:MAX_LESSONS_PER_DAY]
    return schedule


def format_schedule(schedule: Schedule) -> str:
    """Расписание для сообщения в Telegram (HTML)."""
    lines = []
    for day, name in enumerate(WEEKDAY_NAMES):
        lessons = schedule.get(day)
        if lessons:
            lines.append(f"<b>{name}:</b> {escape(', '.join(lessons))}")
        elif day < 5 or day in schedule:
            lines.append(f"<b>{name}:</b> —")
    return "\n".join(lines)
