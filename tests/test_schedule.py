"""Расписание уроков и сроки «к ближайшему уроку»."""

from datetime import date

import pytest

from homework_bot.parser import (
    DUE_DATE,
    DUE_FALLBACK,
    DUE_LESSON,
    DUE_MOVED,
    next_lesson,
    parse_message,
    parse_task,
)
from homework_bot.schedule import format_schedule, normalize_subject, parse_schedule

TODAY = date(2026, 10, 6)  # вторник
FRIDAY = date(2026, 10, 9)

SCHEDULE = parse_schedule(
    """
    пн: алгебра, русский, история
    вт: физика, англ, литература
    ср: алгебра, геометрия
    чт: русский, хореография
    пт: история, физра
    """
)


def test_parse_inline_schedule():
    assert SCHEDULE == {
        0: ["Алгебра", "Русский язык", "История"],
        1: ["Физика", "Английский язык", "Литература"],
        2: ["Алгебра", "Геометрия"],
        3: ["Русский язык", "Хореография"],
        4: ["История", "Физкультура"],
    }


def test_parse_column_schedule_with_numbers_and_times():
    text = (
        "Моё расписание:\n"
        "Понедельник\n"
        "1. 8:30-9:15 Алгебра\n"
        "2) рус яз\n"
        "3 История России\n"
        "\n"
        "В среду —\n"
        "8.30 информатика\n"
        "Суббота: выходной\n"
    )
    assert parse_schedule(text) == {
        0: ["Алгебра", "Русский язык", "История"],
        2: ["Информатика"],
        5: [],
    }


@pytest.mark.parametrize(
    "line, weekday",
    [
        ("Пн. алгебра", 0), ("ВТ - алгебра", 1), ("среда: алгебра", 2), ("Чт) алгебра", 3),
        ("пятница — алгебра", 4), ("сб алгебра", 5), ("воскресенье: алгебра", 6),
    ],
)
def test_weekday_spellings(line, weekday):
    assert parse_schedule(line) == {weekday: ["Алгебра"]}


def test_text_without_weekdays_is_not_schedule():
    assert parse_schedule("алгебра, физика, химия") == {}
    assert parse_schedule("привет") == {}


@pytest.mark.parametrize(
    "item, subject",
    [
        ("алг", "Алгебра"),
        ("Алгебра и начала анализа", "Алгебра"),
        ("физика (каб. 23)", "Физика"),
        ("хореография", "Хореография"),
        ("разговоры о важном", "Разговоры о важном"),
    ],
)
def test_normalize_subject(item, subject):
    assert normalize_subject(item) == subject


def test_format_schedule_escapes_and_shows_weekdays():
    text = format_schedule({0: ["Алгебра", "<b>Кружок</b>"], 5: ["Физика"]})
    assert "<b>Понедельник:</b> Алгебра, &lt;b&gt;Кружок&lt;/b&gt;" in text
    assert "<b>Вторник:</b> —" in text
    assert "<b>Суббота:</b> Физика" in text
    assert "Воскресенье" not in text


def test_next_lesson():
    assert next_lesson(SCHEDULE, "Алгебра", TODAY) == date(2026, 10, 7)  # среда
    assert next_lesson(SCHEDULE, "Физика", TODAY) == date(2026, 10, 13)  # через неделю
    assert next_lesson(SCHEDULE, "хореография", TODAY) == date(2026, 10, 8)
    assert next_lesson(SCHEDULE, "Химия", TODAY) is None
    assert next_lesson({}, "Алгебра", TODAY) is None


@pytest.mark.parametrize(
    "text, today, due, rule",
    [
        # без срока — ближайший урок
        ("алгебра №245", TODAY, date(2026, 10, 7), DUE_LESSON),
        ("история §12", TODAY, FRIDAY, DUE_LESSON),
        ("история §12", FRIDAY, date(2026, 10, 12), DUE_LESSON),
        # «к следующему уроку»
        ("физика задачи 3-5 к следующему уроку", TODAY, date(2026, 10, 13), DUE_LESSON),
        ("геом №12 на след. урок", TODAY, date(2026, 10, 7), DUE_LESSON),
        ("хореография растяжка к уроку", TODAY, date(2026, 10, 8), DUE_LESSON),
        # «на завтра», а завтра урока нет — ближайший урок
        ("история §12 на завтра", TODAY, FRIDAY, DUE_MOVED),
        ("алгебра №1 на завтра", FRIDAY, date(2026, 10, 12), DUE_MOVED),
        # «на завтра», и завтра урок есть — завтра
        ("алгебра №1 на завтра", TODAY, date(2026, 10, 7), DUE_DATE),
        # явная дата важнее расписания
        ("алгебра №1 к пятнице", TODAY, FRIDAY, DUE_DATE),
        ("история §1 послезавтра", TODAY, date(2026, 10, 8), DUE_DATE),
        # предмета нет в расписании — завтра
        ("химия задача 3", TODAY, date(2026, 10, 7), DUE_FALLBACK),
        ("химия задача 3 к следующему уроку", TODAY, date(2026, 10, 7), DUE_FALLBACK),
        ("химия задача 3 на завтра", TODAY, date(2026, 10, 7), DUE_DATE),
    ],
)
def test_due_by_schedule(text, today, due, rule):
    task = parse_task(text, today, SCHEDULE)
    assert (task.due, task.due_rule) == (due, rule)


def test_next_lesson_phrase_is_removed_from_description():
    task = parse_task("физика задачи 3-5 к следующему уроку", TODAY, SCHEDULE)
    assert task.subject == "Физика"
    assert task.description == "задачи 3-5"
    assert task.due_found


def test_without_schedule_falls_back_to_tomorrow():
    task = parse_task("алгебра №245", TODAY)
    assert (task.due, task.due_found, task.due_rule) == (date(2026, 10, 7), False, DUE_FALLBACK)
    task = parse_task("алгебра №245 к следующему уроку", TODAY)
    assert (task.due, task.due_found, task.due_rule) == (date(2026, 10, 7), True, DUE_FALLBACK)


def test_multiline_message_uses_schedule():
    tasks = parse_message("алгебра №245\nистория §12", TODAY, SCHEDULE)
    assert [t.due for t in tasks] == [date(2026, 10, 7), FRIDAY]
