"""Разбор сообщений вида «алгебра №245 на завтра» на предмет, задание и срок.

Модуль не зависит от Telegram и базы данных, поэтому его легко тестировать:
на вход — текст и «сегодняшняя» дата, на выходе — список ParsedTask.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

# Если предмет не удалось определить, задание попадает сюда.
OTHER_SUBJECT = "Другое"


@dataclass(frozen=True)
class ParsedTask:
    subject: str
    description: str
    due: date
    # False — срок в сообщении не нашёлся и подставлен по умолчанию (завтра).
    due_found: bool


# --------------------------------------------------------------------------
# Предметы
# --------------------------------------------------------------------------
# Каноническое название → регулярные выражения для вариантов написания
# (полные названия в любом падеже, сокращения, школьный сленг).
# Если в тексте на одной позиции подходят несколько вариантов, побеждает
# самый длинный: «литературное чтение» сильнее, чем «литература».
SUBJECTS: dict[str, list[str]] = {
    "Алгебра": [r"алгебр\w*", r"алг"],
    "Геометрия": [r"геометри\w*", r"геом"],
    "Математика": [r"математик\w*", r"матем", r"матеш\w*"],
    "Вероятность и статистика": [
        r"вероятност\w*(?:\s+и\s+статистик\w*)?",
        r"теори\w*\s+вероятност\w*",
        r"тер\.?\s*вер\w*",
        r"статистик\w*",
        r"вис",
    ],
    "Русский язык": [r"русск\w*(?:\s+яз\w*)?", r"рус\.?\s*яз\w*", r"русяз\w*", r"рус"],
    "Литература": [r"(?:русск\w*\s+)?литератур\w*", r"лит-?р[аеуы]", r"лит"],
    "Литературное чтение": [r"литературн\w*\s+чтени\w*", r"лит\.?\s*чтени\w*", r"чтени[еяю]"],
    "Родной язык": [r"родн\w*\s+(?:русск\w*\s+)?яз\w*"],
    "Родная литература": [r"родн\w*\s+литер\w*"],
    "Английский язык": [r"английск\w*(?:\s+яз\w*)?", r"англ\w*(?:\s*\.?\s*яз\w*)?", r"инглиш\w*"],
    "Немецкий язык": [r"немецк\w*(?:\s+яз\w*)?", r"нем\.?\s*яз\w*"],
    "Французский язык": [r"французск\w*(?:\s+яз\w*)?", r"фр\.?\s*яз\w*"],
    "Испанский язык": [r"испанск\w*(?:\s+яз\w*)?"],
    "Китайский язык": [r"китайск\w*(?:\s+яз\w*)?"],
    "История": [r"истори\w*", r"ист"],
    "Обществознание": [r"обществознани\w*", r"обществ\w*", r"общаг\w*", r"общ"],
    "Право": [r"право"],
    "Экономика": [r"экономик\w*"],
    "География": [r"географи\w*", r"геогр"],
    "Биология": [r"биологи\w*", r"биол", r"био"],
    "Химия": [r"хими\w*", r"хим"],
    "Физика": [r"физик\w*"],
    "Астрономия": [r"астрономи\w*"],
    "Информатика": [r"информатик\w*", r"информ", r"инф[аеуы]?"],
    "Окружающий мир": [r"окружающ\w*(?:\s+мир\w*)?", r"окружайк\w*", r"окр\.?\s*мир\w*"],
    "Физкультура": [r"физкульт\w*", r"физ-?культ\w*", r"физ-?р[аеуы]", r"физическ\w*\s+культур\w*"],
    "ОБЖ": [r"обж"],
    "ОБЗР": [r"обзр"],
    "Музыка": [r"музык\w*"],
    "ИЗО": [r"изо", r"изобразительн\w*(?:\s+искусств\w*)?", r"рисовани\w*"],
    "Технология": [r"технологи\w*"],
    "Труд": [r"труд[аеуы]?"],
    "Черчение": [r"черчени\w*"],
    "МХК": [r"мхк"],
    "ОРКСЭ": [r"орксэ"],
    "ОДНКНР": [r"однкнр"],
    "Индивидуальный проект": [r"индивидуальн\w*\s+проект\w*", r"инд\.?\s*проект\w*"],
}

# «дз по алгебре» — предлог «по» удаляем вместе с предметом.
_SUBJECT_REGEXES: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(rf"(?<!\w)(?:по\s+)?(?:{pattern})(?!\w)", re.IGNORECASE))
    for name, patterns in SUBJECTS.items()
    for pattern in patterns
]

# Слова, с которых обычно начинается само задание, а не название предмета.
# Если предмет не из словаря, первое слово сообщения считаем предметом,
# но только если это не одно из этих слов и не глагол («прочитать», «выучить»).
_TASK_WORDS = {
    "п", "пар", "параграф", "параграфы", "упр", "упражнение", "упражнения",
    "номер", "номера", "задача", "задачи", "задачу", "задание", "задания",
    "стр", "страница", "страницы", "тест", "проект", "доклад", "реферат",
    "презентация", "презентацию", "сочинение", "изложение", "конспект",
    "стих", "стихотворение", "пересказ", "контрольная", "контрольную", "кр",
    "самостоятельная", "самостоятельную", "лабораторная", "лабораторную",
    "практическая", "практическую", "вопросы", "правило", "правила", "словарь",
    "выучи", "прочитай", "сделай", "напиши", "реши", "повтори", "подготовь",
    "перескажи", "нарисуй", "принеси", "сдать",
}
_INFINITIVE_RE = re.compile(r"(?:ть|ться|ти|тись|чь|чься)$", re.IGNORECASE)

# Служебные слова в начале задания, которые не несут смысла.
_FILLER_RE = re.compile(
    r"^(?:(?:дз|д/з|д\.з\.?|домашк[аиуе]|домашнее\s+задание|задали|задано|надо|нужно)"
    r"(?!\w)[\s,.:;—–-]*)+",
    re.IGNORECASE,
)

_STRIP_CHARS = " \t,.;:—–-"


# --------------------------------------------------------------------------
# Сроки
# --------------------------------------------------------------------------
_PREP = r"(?:к|ко|на|до|в|во)"

_WEEKDAYS = (
    r"понедельник\w*|пн|вторник\w*|вт|сред[аеуы]|ср|четверг\w*|чт"
    r"|пятниц\w*|пт|суббот\w*|сб|воскресень\w*|вс"
)
_WEEKDAY_PREFIXES = (
    ("пон", 0), ("пн", 0), ("вт", 1), ("ср", 2), ("чет", 3), ("чт", 3),
    ("пят", 4), ("пт", 4), ("суб", 5), ("сб", 5), ("вос", 6), ("вс", 6),
)

_MONTHS = (
    r"январ[ьяе]|янв|феврал[ьяе]|февр?|март[ае]?|мар|апрел[ьяе]|апр|ма[йяе]"
    r"|июн[ьяе]|июн|июл[ьяе]|июл|август[ае]?|авг|сентябр[ьяе]|сент?"
    r"|октябр[ьяе]|окт|ноябр[ьяе]|нояб?|декабр[ьяе]|дек"
)
_MONTH_PREFIXES = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5, "мае": 5,
    "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}

_NUMBER_WORDS = {
    "пару": 2, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7,
}

_DAY_SUFFIX = r"(?:-?(?:е|ое|го|му))"

_RELATIVE_RE = re.compile(
    rf"(?<!\w)(?:{_PREP}\s+)?"
    r"(?P<word>сегодня|послезавтра|завтра|завтрашн\w*(?:\s+д(?:ень|ню|ня))?)(?!\w)",
    re.IGNORECASE,
)
_IN_DAYS_RE = re.compile(
    r"(?<!\w)через\s+(?:(?P<n>\d{1,2}|пару|два|две|три|четыре|пять|шесть|семь)\s+)?"
    r"(?P<unit>день|дня|дней|неделю|недели|недель)(?!\w)",
    re.IGNORECASE,
)
_WEEKDAY_RE = re.compile(
    rf"(?<!\w)(?:(?P<prep>{_PREP})\s+)?"
    r"(?:(?P<mod>эт[уоаи]\w*|следующ\w*|ближайш\w*|след)\.?\s+)?"
    rf"(?P<wd>{_WEEKDAYS})(?!\w)\.?",
    re.IGNORECASE,
)
_DAY_MONTH_RE = re.compile(
    rf"(?<![\w№./-])(?:{_PREP}\s+)?(?P<d>\d{{1,2}}){_DAY_SUFFIX}?\s+(?P<m>{_MONTHS})(?!\w)\.?"
    r"(?:\s+(?P<y>\d{4})(?:\s*(?:года|год|г)(?!\w)\.?)?)?",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(
    rf"(?<![\w№./-])(?:(?P<prep>{_PREP})\s+)?"
    r"(?P<d>\d{1,2})[./](?P<m>\d{1,2})(?:[./](?P<y>\d{4}|\d{2}))?(?!\d)(?![./]\d)",
    re.IGNORECASE,
)
_DAY_OF_MONTH_RE = re.compile(
    rf"(?<!\w){_PREP}\s+(?P<d>\d{{1,2}})(?:{_DAY_SUFFIX}|\s+числ[ауо])(?!\w)",
    re.IGNORECASE,
)


def _resolve_relative(m: re.Match[str], today: date) -> Optional[date]:
    word = m["word"].lower()
    if word.startswith("послезавтра"):
        return today + timedelta(days=2)
    if word.startswith("завтр"):
        return today + timedelta(days=1)
    return today


def _resolve_in_days(m: re.Match[str], today: date) -> Optional[date]:
    raw = (m["n"] or "1").lower()
    n = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
    days = n * 7 if m["unit"].lower().startswith("недел") else n
    return today + timedelta(days=days)


def _resolve_weekday(m: re.Match[str], today: date) -> Optional[date]:
    rest = m.string[m.end():].strip(" .!")
    # «среда обитания», «пт» внутри текста — не срок. Без предлога и без
    # «следующий/этот» день недели считаем сроком, только если он стоит в конце.
    if not m["prep"] and not m["mod"] and rest:
        return None

    wd_text = m["wd"].lower()
    weekday = next(idx for prefix, idx in _WEEKDAY_PREFIXES if wd_text.startswith(prefix))

    if m["mod"] and m["mod"].lower().startswith("след"):
        # «к следующей пятнице» — пятница следующей календарной недели.
        next_monday = today + timedelta(days=7 - today.weekday())
        return next_monday + timedelta(days=weekday)

    # «к пятнице» — ближайшая пятница после сегодняшнего дня
    # (если сегодня пятница — то через неделю).
    delta = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=delta)


def _date_without_year(today: date, day: int, month: int) -> Optional[date]:
    """Ближайшая такая дата: в этом году, а если она давно прошла — в следующем."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today - timedelta(days=7):
            return candidate
    return None


def _date_with_year(year: int, month: int, day: int) -> Optional[date]:
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve_day_month(m: re.Match[str], today: date) -> Optional[date]:
    month = _MONTH_PREFIXES.get(m["m"].lower()[:3])
    if month is None:
        return None
    day = int(m["d"])
    if m["y"]:
        return _date_with_year(int(m["y"]), month, day)
    return _date_without_year(today, day, month)


def _resolve_numeric(m: re.Match[str], today: date) -> Optional[date]:
    # «упр 12.3» — это номер упражнения, а не 12 марта. Короткую дату
    # без года принимаем только с предлогом: «к 12.03», «на 12.03».
    if not m["y"] and not m["prep"]:
        return None
    day, month = int(m["d"]), int(m["m"])
    if m["y"]:
        return _date_with_year(int(m["y"]), month, day)
    return _date_without_year(today, day, month)


def _resolve_day_of_month(m: re.Match[str], today: date) -> Optional[date]:
    """«к 15-му», «на 15 число» — ближайшее 15-е число, начиная с сегодня."""
    day = int(m["d"])
    year, month = today.year, today.month
    for _ in range(13):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = None
        if candidate is not None and candidate >= today:
            return candidate
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return None


_Resolver = Callable[[re.Match[str], date], Optional[date]]

_DATE_RULES: list[tuple[re.Pattern[str], _Resolver]] = [
    (_RELATIVE_RE, _resolve_relative),
    (_IN_DAYS_RE, _resolve_in_days),
    (_WEEKDAY_RE, _resolve_weekday),
    (_DAY_MONTH_RE, _resolve_day_month),
    (_NUMERIC_RE, _resolve_numeric),
    (_DAY_OF_MONTH_RE, _resolve_day_of_month),
]


# --------------------------------------------------------------------------
# Разбор
# --------------------------------------------------------------------------
def _cut(text: str, start: int, end: int) -> str:
    return f"{text[:start]} {text[end:]}"


def _extract_date(text: str, today: date) -> tuple[Optional[date], str]:
    """Находит самое левое упоминание срока и вырезает его из текста."""
    best: Optional[tuple[int, int, date]] = None
    for regex, resolve in _DATE_RULES:
        for m in regex.finditer(text):
            due = resolve(m, today)
            if due is None:
                continue
            if best is None or (m.start(), -m.end()) < (best[0], -best[1]):
                best = (m.start(), m.end(), due)
            break  # для этого правила нашли самое левое совпадение
    if best is None:
        return None, text
    start, end, due = best
    return due, _cut(text, start, end)


def _extract_subject(text: str) -> tuple[Optional[str], str]:
    """Находит самое левое упоминание предмета и вырезает его из текста."""
    best: Optional[tuple[int, int, str]] = None
    for name, regex in _SUBJECT_REGEXES:
        m = regex.search(text)
        if m and (best is None or (m.start(), -m.end()) < (best[0], -best[1])):
            best = (m.start(), m.end(), name)
    if best is None:
        return None, text
    start, end, name = best
    return name, _cut(text, start, end)


def _clean(text: str) -> str:
    text = " ".join(text.split())
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)  # «№245 ,» → «№245,»
    text = re.sub(r"([,;:])[,;:]+", r"\1", text)  # «,,» → «,»
    text = text.strip(_STRIP_CHARS)
    text = _FILLER_RE.sub("", text)
    return text.strip(_STRIP_CHARS)


def _guess_subject(text: str) -> tuple[str, str]:
    """Предмета нет в словаре: берём первое слово, если оно похоже на название."""
    m = re.match(r"([^\W\d_][\w-]*)", text)
    if m:
        word = m[1]
        lower = word.lower()
        if len(word) >= 3 and lower not in _TASK_WORDS and not _INFINITIVE_RE.search(lower):
            return word[0].upper() + word[1:], text[m.end():]
    return OTHER_SUBJECT, text


def parse_task(text: str, today: date) -> Optional[ParsedTask]:
    """Разбирает одно задание. Возвращает None, если это не похоже на домашку."""
    text = " ".join(text.split())
    if not text:
        return None

    due, rest = _extract_date(text, today)
    subject, rest = _extract_subject(rest)

    if subject is None:
        # Ни предмета, ни срока («привет», «спасибо») — это не задание.
        if due is None:
            return None
        subject, rest = _guess_subject(_clean(rest))

    description = _clean(rest)
    if subject == OTHER_SUBJECT and not description:
        return None

    return ParsedTask(
        subject=subject,
        description=description,
        due=due if due is not None else today + timedelta(days=1),
        due_found=due is not None,
    )


def parse_message(text: str, today: date) -> list[ParsedTask]:
    """Разбирает сообщение целиком.

    Если каждая строка сообщения — отдельное задание («алгебра №245 на завтра»
    и ниже «история §12 к пятнице»), вернёт несколько заданий. Иначе считает
    всё сообщение одним заданием, записанным в несколько строк.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        tasks = [parse_task(line, today) for line in lines]
        if all(tasks):
            return tasks  # type: ignore[return-value]
    task = parse_task(text, today)
    return [task] if task else []
