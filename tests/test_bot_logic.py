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


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            subject TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            due_date TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO tasks (chat_id, subject, due_date, done) VALUES (42, 'Алгебра', '2026-10-05', 1);
        """
    )
    conn.commit()
    conn.close()

    db = Storage(path)
    task = db.get_task(1)
    assert task.done and task.photos == 0
    # Отмеченное до обновления задание попадает в статистику по сроку сдачи.
    assert db.done_by_subject(CHAT, TODAY - timedelta(days=6), TODAY) == [("Алгебра", 1)]
    db.close()


def test_done_by_subject_counts_by_done_day(db):
    week_ago = TODAY - timedelta(days=7)
    for subject, done_on in [
        ("Алгебра", TODAY), ("Алгебра", TODAY - timedelta(days=6)),
        ("История", TODAY), ("Физика", week_ago),
    ]:
        task = db.add_task(CHAT, subject, "", TODAY + timedelta(days=30))
        db.set_done(task.id, True, on=done_on)
    undone = db.add_task(CHAT, "Химия", "", TODAY)
    db.set_done(undone.id, True, on=TODAY)
    db.set_done(undone.id, False)

    assert db.done_by_subject(CHAT, TODAY - timedelta(days=6), TODAY) == [
        ("Алгебра", 2), ("История", 1)
    ]


def test_photos_are_counted_and_deleted_with_task(db):
    from homework_bot.storage import MAX_PHOTOS_PER_TASK, Photo

    task = db.add_task(CHAT, "Алгебра", "", TODAY)
    db.add_photo(task.id, Photo("a"))
    db.add_photo(task.id, Photo("b", "document"))
    assert db.get_task(task.id).photos == 2
    assert db.task_photos(task.id) == [Photo("a"), Photo("b", "document")]
    for _ in range(MAX_PHOTOS_PER_TASK - 2):
        assert db.add_photo(task.id, Photo("x"))
    assert not db.add_photo(task.id, Photo("too many"))

    db.delete_task(task.id)
    assert db.task_photos(task.id) == []


def test_pending_photos(db):
    from homework_bot.storage import Photo

    db.add_pending_photo(CHAT, Photo("a"))
    db.add_pending_photo(CHAT + 1, Photo("other chat"))
    assert db.pop_pending_photos(CHAT) == [Photo("a")]
    assert db.pop_pending_photos(CHAT) == []
    # Старые фото без подписи забываются.
    db._conn.execute(
        "INSERT INTO pending_photos (chat_id, file_id, created_at)"
        " VALUES (?, 'old', datetime('now', '-2 days'))", (CHAT,)
    )
    assert db.pop_pending_photos(CHAT) == []


def test_schedule_roundtrip(db):
    db.set_schedule(CHAT, {0: ["Алгебра", "История"], 4: ["Физика"], 5: []})
    assert db.get_schedule(CHAT) == {0: ["Алгебра", "История"], 4: ["Физика"]}
    db.set_schedule(CHAT, {2: ["Химия"]})
    assert db.get_schedule(CHAT) == {2: ["Химия"]}
    assert db.get_schedule(CHAT + 1) == {}


def test_list_shows_photo_button(db):
    from homework_bot.storage import Photo

    plain = db.add_task(CHAT, "Алгебра", "", TODAY)
    with_photo = db.add_task(CHAT, "История", "", TODAY)
    db.add_photo(with_photo.id, Photo("a"))
    text, keyboard = views.render(views.TODAY, db.get_tasks(CHAT, [plain.id, with_photo.id]), TODAY)
    assert "<b>История</b> 📷" in text
    assert [[b.text for b in row] for row in keyboard.inline_keyboard] == [
        ["✅ 1. Алгебра"], ["✅ 2. История", "📷 2"]
    ]
    assert views.task_ids_from_markup(keyboard) == [plain.id, with_photo.id]


def test_render_stats():
    text = views.render_stats([("Алгебра", 4), ("История", 1)], TODAY - timedelta(days=6), TODAY, 3, 1)
    assert "30 сентября — 6 октября" in text
    assert "Сделано заданий: <b>5</b>" in text
    assert "▰▰▰▰▰▰▰▰▰▰ <b>Алгебра</b> — 4" in text
    assert "▰▰ <b>История</b> — 1" in text
    assert "Ещё не сделано: <b>3</b>, из них просрочено: <b>1</b>" in text
