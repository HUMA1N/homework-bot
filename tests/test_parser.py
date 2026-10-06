from datetime import date

import pytest

from homework_bot.parser import OTHER_SUBJECT, ParsedTask, parse_message, parse_task

# Вторник, 6 октября 2026 года.
TODAY = date(2026, 10, 6)
TOMORROW = date(2026, 10, 7)


def parse_one(text: str, today: date = TODAY) -> ParsedTask:
    task = parse_task(text, today)
    assert task is not None, f"не разобралось: {text!r}"
    return task


# --- примеры из задания ------------------------------------------------------

def test_algebra_for_tomorrow():
    assert parse_one("алгебра №245 на завтра") == ParsedTask(
        subject="Алгебра", description="№245", due=TOMORROW, due_found=True
    )


def test_history_by_friday():
    assert parse_one("история параграф 12 к пятнице") == ParsedTask(
        subject="История", description="параграф 12", due=date(2026, 10, 9), due_found=True
    )


# --- предметы -----------------------------------------------------------------

@pytest.mark.parametrize(
    "text, subject",
    [
        ("Алгебра №245", "Алгебра"),
        ("АЛГЕБРА №245", "Алгебра"),
        ("алг №245", "Алгебра"),
        ("геом задача 5", "Геометрия"),
        ("матеша стр 10", "Математика"),
        ("русский упр 45", "Русский язык"),
        ("русский язык упр 45", "Русский язык"),
        ("рус.яз упр 45", "Русский язык"),
        ("лит-ра стих наизусть", "Литература"),
        ("литература читать Онегина", "Литература"),
        ("русская литература читать Онегина", "Литература"),
        ("литературное чтение стр 15", "Литературное чтение"),
        ("англ стр 34", "Английский язык"),
        ("англ.яз стр 34", "Английский язык"),
        ("английский язык стр 34", "Английский язык"),
        ("немецкий упр 3", "Немецкий язык"),
        ("общага параграф 3", "Обществознание"),
        ("обществознание параграф 3", "Обществознание"),
        ("био параграф 7", "Биология"),
        ("химия задача 2", "Химия"),
        ("физика задача 2", "Физика"),
        ("физра принести форму", "Физкультура"),
        ("физ-ра принести форму", "Физкультура"),
        ("инфа презентация", "Информатика"),
        ("информатика презентация", "Информатика"),
        ("география контурная карта", "География"),
        ("окружайка стр 20", "Окружающий мир"),
        ("изо рисунок осени", "ИЗО"),
        ("обж параграф 1", "ОБЖ"),
        ("вероятность и статистика №12", "Вероятность и статистика"),
        ("тервер №12", "Вероятность и статистика"),
    ],
)
def test_subject_aliases(text, subject):
    assert parse_one(text).subject == subject


@pytest.mark.parametrize(
    "text",
    [
        "дз по алгебре №245",
        "по алгебре №245",
        "задали по алгебре №245",
        "№245 по алгебре",
        "Алгебра: №245",
        "алгебра — №245",
    ],
)
def test_subject_anywhere_and_fillers_removed(text):
    task = parse_one(text)
    assert task.subject == "Алгебра"
    assert task.description == "№245"


def test_first_subject_wins():
    task = parse_one("литература прочитать рассказ, повторить историю")
    assert task.subject == "Литература"
    assert task.description == "прочитать рассказ, повторить историю"


def test_word_inside_other_word_is_not_subject():
    # «Русь» — не «рус», «историческ...» в описании не мешает.
    task = parse_one("история Киевская Русь к пятнице")
    assert task.subject == "История"
    assert task.description == "Киевская Русь"


def test_unknown_subject_taken_from_first_word():
    task = parse_one("хореография растяжка на завтра")
    assert task.subject == "Хореография"
    assert task.description == "растяжка"


@pytest.mark.parametrize(
    "text, description",
    [
        ("прочитать главу 3 к пятнице", "прочитать главу 3"),
        ("завтра контрольная", "контрольная"),
        ("доклад про космос к пятнице", "доклад про космос"),
    ],
)
def test_task_words_are_not_subjects(text, description):
    task = parse_one(text)
    assert task.subject == OTHER_SUBJECT
    assert task.description == description


def test_subject_without_description():
    task = parse_one("алгебра на завтра")
    assert task.subject == "Алгебра"
    assert task.description == ""


# --- сроки: слова --------------------------------------------------------------

@pytest.mark.parametrize(
    "text, due",
    [
        ("алгебра №245 на сегодня", date(2026, 10, 6)),
        ("алгебра №245 сегодня", date(2026, 10, 6)),
        ("алгебра №245 завтра", date(2026, 10, 7)),
        ("алгебра №245 к завтрашнему дню", date(2026, 10, 7)),
        ("алгебра №245 на послезавтра", date(2026, 10, 8)),
        ("алгебра №245 через 3 дня", date(2026, 10, 9)),
        ("алгебра №245 через пару дней", date(2026, 10, 8)),
        ("алгебра №245 через неделю", date(2026, 10, 13)),
        ("алгебра №245 через 2 недели", date(2026, 10, 20)),
    ],
)
def test_relative_dates(text, due):
    task = parse_one(text)
    assert task.due == due
    assert task.due_found
    assert task.description == "№245"


# --- сроки: дни недели ---------------------------------------------------------

@pytest.mark.parametrize(
    "text, due",
    [
        ("история §12 к понедельнику", date(2026, 10, 12)),
        ("история §12 ко вторнику", date(2026, 10, 13)),  # сегодня вторник → следующий
        ("история §12 на среду", date(2026, 10, 7)),
        ("история §12 до среды", date(2026, 10, 7)),
        ("история §12 к среде", date(2026, 10, 7)),
        ("история §12 в четверг", date(2026, 10, 8)),
        ("история §12 к пятнице", date(2026, 10, 9)),
        ("история §12 на субботу", date(2026, 10, 10)),
        ("история §12 к воскресенью", date(2026, 10, 11)),
        ("история §12 к пт", date(2026, 10, 9)),
        ("история §12 на ср.", date(2026, 10, 7)),
        ("история §12 в пн", date(2026, 10, 12)),
        ("История §12 К Пятнице", date(2026, 10, 9)),
    ],
)
def test_weekdays(text, due):
    task = parse_one(text)
    assert task.due == due
    assert task.description == "§12"


def test_next_weekday_means_next_week():
    # «к следующей пятнице» во вторник — пятница следующей недели, а не этой.
    assert parse_one("история §12 к следующей пятнице").due == date(2026, 10, 16)
    assert parse_one("история §12 к след. пятнице").due == date(2026, 10, 16)
    assert parse_one("история §12 к следующему понедельнику").due == date(2026, 10, 12)


def test_this_weekday():
    assert parse_one("история §12 в эту пятницу").due == date(2026, 10, 9)


def test_bare_weekday_at_end():
    task = parse_one("алгебра №245 пятница")
    assert task.due == date(2026, 10, 9)
    assert task.description == "№245"


def test_weekday_word_inside_text_is_not_deadline():
    # «среда обитания» — не среда, срок здесь «на завтра».
    task = parse_one("биология параграф 5, среда обитания, на завтра")
    assert task.due == TOMORROW
    assert task.description == "параграф 5, среда обитания"


# --- сроки: даты -----------------------------------------------------------------

@pytest.mark.parametrize(
    "text, due",
    [
        ("литература читать Онегина к 20 октября", date(2026, 10, 20)),
        ("литература читать Онегина к 20-му октября", date(2026, 10, 20)),
        ("литература читать Онегина 20 окт", date(2026, 10, 20)),
        ("литература читать Онегина до 3 ноября", date(2026, 11, 3)),
        ("литература читать Онегина к 15 января", date(2027, 1, 15)),  # следующий год
        ("литература читать Онегина к 1 сентября 2027 г.", date(2027, 9, 1)),
        ("литература читать Онегина к 15.10", date(2026, 10, 15)),
        ("литература читать Онегина на 15/10", date(2026, 10, 15)),
        ("литература читать Онегина до 05.11", date(2026, 11, 5)),
        ("литература читать Онегина к 12.01", date(2027, 1, 12)),
        ("литература читать Онегина 15.10.2026", date(2026, 10, 15)),
        ("литература читать Онегина 15.10.26", date(2026, 10, 15)),
        ("литература читать Онегина к 15-му", date(2026, 10, 15)),
        ("литература читать Онегина на 3-е", date(2026, 11, 3)),
        ("литература читать Онегина к 20 числу", date(2026, 10, 20)),
    ],
)
def test_explicit_dates(text, due):
    task = parse_one(text)
    assert task.due == due
    assert task.description == "читать Онегина"


def test_recent_past_date_stays_in_this_year():
    # Дата, прошедшая пару дней назад, — опечатка или просрочка, но не через год.
    assert parse_one("алгебра №245 к 1 октября").due == date(2026, 10, 1)


def test_new_year_rollover():
    assert parse_one("алгебра №245 к 12.01", today=date(2026, 12, 25)).due == date(2027, 1, 12)
    assert parse_one("алгебра №245 к пятнице", today=date(2026, 12, 30)).due == date(2027, 1, 1)


def test_exercise_number_with_dot_is_not_date():
    # «упр 12.3» — номер упражнения, а не 12 марта.
    task = parse_one("алгебра упр 12.3 на завтра")
    assert task.due == TOMORROW
    assert task.description == "упр 12.3"


def test_number_sign_is_not_date():
    task = parse_one("алгебра №12 октября")  # абсурдно, но № не должен стать датой
    assert task.description == "№12 октября"
    assert not task.due_found


def test_invalid_date_is_ignored():
    task = parse_one("история параграф 12 к 31.02")
    assert not task.due_found
    assert task.due == TOMORROW
    assert task.description == "параграф 12 к 31.02"


def test_date_in_the_middle():
    task = parse_one("алгебра на завтра №245, №246")
    assert task.due == TOMORROW
    assert task.description == "№245, №246"


def test_first_date_wins():
    task = parse_one("алгебра к пятнице, а повторить к завтра")
    assert task.due == date(2026, 10, 9)


# --- без срока --------------------------------------------------------------------

def test_no_deadline_defaults_to_tomorrow():
    task = parse_one("русский упр 45")
    assert task.due == TOMORROW
    assert not task.due_found
    assert task.description == "упр 45"


# --- не задания ---------------------------------------------------------------------

@pytest.mark.parametrize("text", ["", "   ", "привет", "спасибо!", "ок", "на завтра", "к пятнице"])
def test_not_a_task(text):
    assert parse_task(text, TODAY) is None
    assert parse_message(text, TODAY) == []


# --- несколько заданий в одном сообщении --------------------------------------------

def test_several_tasks_one_per_line():
    tasks = parse_message("алгебра №245 на завтра\n\nистория параграф 12 к пятнице", TODAY)
    assert [(t.subject, t.description, t.due) for t in tasks] == [
        ("Алгебра", "№245", TOMORROW),
        ("История", "параграф 12", date(2026, 10, 9)),
    ]


def test_multiline_single_task():
    # Вторая и третья строки сами по себе не задания — значит, это одно задание.
    tasks = parse_message("литература\nпрочитать стр 10-20\nна пятницу", TODAY)
    assert tasks == [
        ParsedTask("Литература", "прочитать стр 10-20", date(2026, 10, 9), due_found=True)
    ]
