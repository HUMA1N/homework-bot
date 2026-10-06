"""Хранилище, списки с кнопками и расписание напоминаний (без Telegram)."""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from homework_bot import views
from homework_bot.reminders import is_due
from homework_bot.storage import Storage

TODAY = date(2026, 10, 6)  # вторник
CHAT = 42


@pytest.fixture
def db():
    storage = Storage(":memory:")
    yield storage
    storage.close()


def add(db, subject, due, done=False, chat=CHAT):
    task = db.add_task(chat, subject, "задание", due)
    if done:
        db.set_done(task.id, True)
    return db.get_task(task.id)


def subjects(tasks):
    return [t.subject for t in tasks]


def test_storage_roundtrip(db):
    task = add(db, "Алгебра", TODAY)
    assert db.get_task(task.id) == task
    db.set_done(task.id, True)
    assert db.get_task(task.id).done
    db.delete_task(task.id)
    assert db.get_task(task.id) is None


def test_views_pick_right_tasks(db):
    add(db, "Просрочено", TODAY - timedelta(days=1))
    add(db, "Просрочено, но сделано", TODAY - timedelta(days=1), done=True)
    add(db, "Сегодня", TODAY)
    add(db, "Сегодня, сделано", TODAY, done=True)
    add(db, "Завтра", TODAY + timedelta(days=1))
    add(db, "Завтра, сделано", TODAY + timedelta(days=1), done=True)
    add(db, "Через 6 дней", TODAY + timedelta(days=6))
    add(db, "Через 7 дней", TODAY + timedelta(days=7))
    add(db, "Чужое", TODAY, chat=CHAT + 1)

    assert subjects(views.collect(views.MORNING, db, CHAT, TODAY)) == [
        "Просрочено", "Сегодня", "Сегодня, сделано"
    ]
    assert subjects(views.collect(views.EVENING, db, CHAT, TODAY)) == [
        "Просрочено", "Сегодня", "Завтра"
    ]
    assert subjects(views.collect(views.WEEK, db, CHAT, TODAY)) == [
        "Просрочено", "Сегодня", "Сегодня, сделано", "Завтра", "Завтра, сделано", "Через 6 дней"
    ]
    assert subjects(views.collect(views.ALL, db, CHAT, TODAY)) == [
        "Просрочено", "Сегодня", "Завтра", "Через 6 дней", "Через 7 дней"
    ]


def test_render_groups_by_day_and_has_button_per_task(db):
    first = add(db, "Алгебра", TODAY + timedelta(days=1))
    second = add(db, "История", TODAY + timedelta(days=3), done=True)

    text, keyboard = views.render(views.WEEK, [second, first], TODAY)

    assert "Завтра — ср, 7 октября" in text
    assert "Пятница, 9 октября" in text
    assert "1. ⬜ <b>Алгебра</b>" in text
    assert "2. ✅ <s><b>История</b>" in text
    labels = [row[0].text for row in keyboard.inline_keyboard]
    assert labels == ["✅ 1. Алгебра", "↩️ 2. История"]
    assert views.task_ids_from_markup(keyboard) == [first.id, second.id]


def test_render_escapes_html(db):
    task = db.add_task(CHAT, "Алгебра", "<b>x</b> & y", TODAY)
    text, _ = views.render(views.TODAY, [task], TODAY)
    assert "&lt;b&gt;x&lt;/b&gt; &amp; y" in text


def test_render_empty():
    text, keyboard = views.render(views.WEEK, [], TODAY)
    assert text == views.EMPTY[views.WEEK]
    assert keyboard is None


def test_added_view_has_delete_button(db):
    task = add(db, "Алгебра", TODAY)
    _, keyboard = views.render(views.ADDED, [task], TODAY)
    assert [b.text for b in keyboard.inline_keyboard[0]] == ["✅ Сделано", "🗑 Удалить"]


TZ = timezone(timedelta(hours=3))
MORNING = time(7, 30)


@pytest.mark.parametrize(
    "now, last_sent, expected",
    [
        (datetime(2026, 10, 6, 7, 29, tzinfo=TZ), None, False),  # ещё рано
        (datetime(2026, 10, 6, 7, 30, tzinfo=TZ), None, True),
        (datetime(2026, 10, 6, 9, 0, tzinfo=TZ), "2026-10-05", True),  # проснулись чуть позже
        (datetime(2026, 10, 6, 7, 31, tzinfo=TZ), "2026-10-06", False),  # уже отправили
        (datetime(2026, 10, 6, 15, 0, tzinfo=TZ), None, False),  # слишком поздно для утра
    ],
)
def test_is_due(now, last_sent, expected):
    assert is_due(now, MORNING, last_sent) is expected


def test_render_fits_telegram_limits(db):
    tasks = [db.add_task(CHAT, "Алгебра", "x" * 300, TODAY) for _ in range(120)]
    text, keyboard = views.render(views.ALL, tasks, TODAY)
    buttons = sum(len(row) for row in keyboard.inline_keyboard)
    assert len(text) < 4096
    assert buttons <= views.MAX_TASKS
    assert f"…и ещё {120 - buttons}" in text
