"""Хранение заданий в SQLite."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from .parser import Schedule

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id    INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    subject     TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    due_date    TEXT    NOT NULL,           -- ГГГГ-ММ-ДД
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    done_at     TEXT                        -- ГГГГ-ММ-ДД, когда отметили «сделано»
);
CREATE INDEX IF NOT EXISTS idx_tasks_chat_due ON tasks (chat_id, due_date);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Фото (или файлы), прикреплённые к заданиям. Сами картинки хранит Telegram,
-- у нас только их file_id.
CREATE TABLE IF NOT EXISTS task_photos (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    file_id TEXT    NOT NULL,
    kind    TEXT    NOT NULL DEFAULT 'photo'   -- photo | document
);
CREATE INDEX IF NOT EXISTS idx_task_photos_task ON task_photos (task_id);
-- Фото без подписи ждут, пока пользователь напишет, что это за задание.
CREATE TABLE IF NOT EXISTS pending_photos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    file_id    TEXT    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'photo',
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Расписание уроков: день недели (0 — понедельник), номер урока, предмет.
CREATE TABLE IF NOT EXISTS lessons (
    chat_id  INTEGER NOT NULL,
    weekday  INTEGER NOT NULL,
    position INTEGER NOT NULL,
    subject  TEXT    NOT NULL,
    PRIMARY KEY (chat_id, weekday, position)
);
"""

# Столбцы, которых не было в первой версии бота: добавляем их в старую базу.
MIGRATIONS = {
    ("tasks", "done_at"): "ALTER TABLE tasks ADD COLUMN done_at TEXT",
}

# Задание вместе с числом прикреплённых фото.
TASK_SELECT = (
    "SELECT tasks.*,"
    " (SELECT COUNT(*) FROM task_photos WHERE task_photos.task_id = tasks.id) AS photos"
    " FROM tasks"
)

# Фото без подписи, которые так и не привязали к заданию, забываем через сутки.
PENDING_PHOTOS_TTL = "-1 day"
MAX_PHOTOS_PER_TASK = 10


@dataclass(frozen=True)
class Task:
    id: int
    chat_id: int
    subject: str
    description: str
    due: date
    done: bool
    photos: int = 0  # сколько фото прикреплено


@dataclass(frozen=True)
class Photo:
    file_id: str
    kind: str = "photo"  # photo — сжатое фото, document — картинка или PDF файлом


def _to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        chat_id=row["chat_id"],
        subject=row["subject"],
        description=row["description"],
        due=date.fromisoformat(row["due_date"]),
        done=bool(row["done"]),
        photos=row["photos"],
    )


class Storage:
    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(SCHEMA)
            for (table, column), sql in MIGRATIONS.items():
                columns = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    self._conn.execute(sql)

    def close(self) -> None:
        self._conn.close()

    # --- чаты, которым присылаем напоминания ---------------------------------
    def add_chat(self, chat_id: int) -> None:
        with self._conn:
            self._conn.execute("INSERT OR IGNORE INTO chats (chat_id) VALUES (?)", (chat_id,))

    def remove_chat(self, chat_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))

    def chat_ids(self) -> list[int]:
        rows = self._conn.execute("SELECT chat_id FROM chats ORDER BY chat_id")
        return [row["chat_id"] for row in rows]

    # --- задания -------------------------------------------------------------
    def add_task(self, chat_id: int, subject: str, description: str, due: date) -> Task:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO tasks (chat_id, subject, description, due_date) VALUES (?, ?, ?, ?)",
                (chat_id, subject, description, due.isoformat()),
            )
        return Task(cur.lastrowid, chat_id, subject, description, due, False)

    def get_task(self, task_id: int) -> Optional[Task]:
        row = self._conn.execute(TASK_SELECT + " WHERE id = ?", (task_id,)).fetchone()
        return _to_task(row) if row else None

    def get_tasks(self, chat_id: int, task_ids: Iterable[int]) -> list[Task]:
        ids = list(task_ids)
        if not ids:
            return []
        placeholders = ", ".join("?" * len(ids))
        rows = self._conn.execute(
            f"{TASK_SELECT} WHERE chat_id = ? AND id IN ({placeholders})"
            " ORDER BY due_date, id",
            (chat_id, *ids),
        )
        return [_to_task(row) for row in rows]

    def set_done(self, task_id: int, done: bool, on: Optional[date] = None) -> None:
        """Отмечает задание сделанным (on — в какой день, для /stats) или снимает отметку."""
        done_at = (on or date.today()).isoformat() if done else None
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET done = ?, done_at = ? WHERE id = ?", (int(done), done_at, task_id)
            )

    def delete_task(self, task_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM task_photos WHERE task_id = ?", (task_id,))
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def tasks_between(
        self, chat_id: int, first: date, last: date, *, only_undone: bool = False
    ) -> list[Task]:
        """Задания со сроком с first по last включительно."""
        query = TASK_SELECT + " WHERE chat_id = ? AND due_date BETWEEN ? AND ?"
        if only_undone:
            query += " AND done = 0"
        rows = self._conn.execute(
            query + " ORDER BY due_date, id", (chat_id, first.isoformat(), last.isoformat())
        )
        return [_to_task(row) for row in rows]

    def overdue(self, chat_id: int, today: date) -> list[Task]:
        """Невыполненные задания, срок которых уже прошёл."""
        rows = self._conn.execute(
            TASK_SELECT + " WHERE chat_id = ? AND due_date < ? AND done = 0"
            " ORDER BY due_date, id",
            (chat_id, today.isoformat()),
        )
        return [_to_task(row) for row in rows]

    def undone(self, chat_id: int) -> list[Task]:
        rows = self._conn.execute(
            TASK_SELECT + " WHERE chat_id = ? AND done = 0 ORDER BY due_date, id",
            (chat_id,),
        )
        return [_to_task(row) for row in rows]

    # --- статистика ----------------------------------------------------------
    def done_by_subject(self, chat_id: int, first: date, last: date) -> list[tuple[str, int]]:
        """Сколько заданий по каждому предмету отмечено сделанными с first по last.

        У заданий, отмеченных до появления /stats, дня отметки нет — для них
        берём срок сдачи.
        """
        rows = self._conn.execute(
            "SELECT subject, COUNT(*) AS n FROM tasks"
            " WHERE chat_id = ? AND done = 1 AND COALESCE(done_at, due_date) BETWEEN ? AND ?"
            " GROUP BY subject ORDER BY n DESC, subject",
            (chat_id, first.isoformat(), last.isoformat()),
        )
        return [(row["subject"], row["n"]) for row in rows]

    # --- фото заданий --------------------------------------------------------
    def add_photo(self, task_id: int, photo: Photo) -> bool:
        """Прикрепляет фото к заданию. False — у задания уже слишком много фото."""
        count = self._conn.execute(
            "SELECT COUNT(*) FROM task_photos WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
        if count >= MAX_PHOTOS_PER_TASK:
            return False
        with self._conn:
            self._conn.execute(
                "INSERT INTO task_photos (task_id, file_id, kind) VALUES (?, ?, ?)",
                (task_id, photo.file_id, photo.kind),
            )
        return True

    def task_photos(self, task_id: int) -> list[Photo]:
        rows = self._conn.execute(
            "SELECT file_id, kind FROM task_photos WHERE task_id = ? ORDER BY id", (task_id,)
        )
        return [Photo(row["file_id"], row["kind"]) for row in rows]

    def add_pending_photo(self, chat_id: int, photo: Photo) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO pending_photos (chat_id, file_id, kind) VALUES (?, ?, ?)",
                (chat_id, photo.file_id, photo.kind),
            )

    def pop_pending_photos(self, chat_id: int) -> list[Photo]:
        """Забирает фото, которые ждут подписи (и забывает их)."""
        with self._conn:
            rows = self._conn.execute(
                "SELECT file_id, kind FROM pending_photos"
                " WHERE chat_id = ? AND created_at >= datetime('now', ?) ORDER BY id",
                (chat_id, PENDING_PHOTOS_TTL),
            ).fetchall()
            self._conn.execute("DELETE FROM pending_photos WHERE chat_id = ?", (chat_id,))
        return [Photo(row["file_id"], row["kind"]) for row in rows]

    # --- расписание уроков ---------------------------------------------------
    def get_schedule(self, chat_id: int) -> Schedule:
        schedule: Schedule = {}
        rows = self._conn.execute(
            "SELECT weekday, subject FROM lessons WHERE chat_id = ? ORDER BY weekday, position",
            (chat_id,),
        )
        for row in rows:
            schedule.setdefault(row["weekday"], []).append(row["subject"])
        return schedule

    def set_schedule(self, chat_id: int, schedule: Schedule) -> None:
        """Заменяет расписание целиком (пустой словарь — удалить расписание)."""
        with self._conn:
            self._conn.execute("DELETE FROM lessons WHERE chat_id = ?", (chat_id,))
            self._conn.executemany(
                "INSERT INTO lessons (chat_id, weekday, position, subject) VALUES (?, ?, ?, ?)",
                [
                    (chat_id, weekday, position, subject)
                    for weekday, subjects in schedule.items()
                    for position, subject in enumerate(subjects)
                ],
            )

    # --- служебные значения (когда последний раз слали напоминание) ----------
    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def delete_meta(self, key: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM meta WHERE key = ?", (key,))

    def set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
