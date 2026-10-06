"""Хранение заданий в SQLite."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

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
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tasks_chat_due ON tasks (chat_id, due_date);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Task:
    id: int
    chat_id: int
    subject: str
    description: str
    due: date
    done: bool


def _to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        chat_id=row["chat_id"],
        subject=row["subject"],
        description=row["description"],
        due=date.fromisoformat(row["due_date"]),
        done=bool(row["done"]),
    )


class Storage:
    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(SCHEMA)

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
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _to_task(row) if row else None

    def get_tasks(self, chat_id: int, task_ids: Iterable[int]) -> list[Task]:
        ids = list(task_ids)
        if not ids:
            return []
        placeholders = ", ".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT * FROM tasks WHERE chat_id = ? AND id IN ({placeholders})"
            " ORDER BY due_date, id",
            (chat_id, *ids),
        )
        return [_to_task(row) for row in rows]

    def set_done(self, task_id: int, done: bool) -> None:
        with self._conn:
            self._conn.execute("UPDATE tasks SET done = ? WHERE id = ?", (int(done), task_id))

    def delete_task(self, task_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def tasks_between(
        self, chat_id: int, first: date, last: date, *, only_undone: bool = False
    ) -> list[Task]:
        """Задания со сроком с first по last включительно."""
        query = "SELECT * FROM tasks WHERE chat_id = ? AND due_date BETWEEN ? AND ?"
        if only_undone:
            query += " AND done = 0"
        rows = self._conn.execute(
            query + " ORDER BY due_date, id", (chat_id, first.isoformat(), last.isoformat())
        )
        return [_to_task(row) for row in rows]

    def overdue(self, chat_id: int, today: date) -> list[Task]:
        """Невыполненные задания, срок которых уже прошёл."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE chat_id = ? AND due_date < ? AND done = 0"
            " ORDER BY due_date, id",
            (chat_id, today.isoformat()),
        )
        return [_to_task(row) for row in rows]

    def undone(self, chat_id: int) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE chat_id = ? AND done = 0 ORDER BY due_date, id",
            (chat_id,),
        )
        return [_to_task(row) for row in rows]

    # --- служебные значения (когда последний раз слали напоминание) ----------
    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
