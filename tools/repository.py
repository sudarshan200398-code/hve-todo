"""SQLite-backed task persistence and its typed tool facade.

This module is the application's sole owner of SQLite connections, schema,
transactions, SQL statements, and database row mapping.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Mapping, TypeAlias

Priority: TypeAlias = Literal["low", "normal", "high"]
_PRIORITIES = frozenset({"low", "normal", "high"})
_PATCHABLE_COLUMNS = frozenset({"title", "completed", "priority", "due_date"})
_ORDERABLE_COLUMNS = frozenset(
    {"id", "title", "completed", "priority", "due_date", "created_at", "updated_at"}
)


@dataclass(frozen=True, slots=True)
class Task:
    """A persisted task, with timestamps represented as ISO-8601 strings."""

    id: int
    title: str
    completed: bool
    priority: Priority
    due_date: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_title(title: str) -> str:
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    normalized = title.strip()
    if not normalized:
        raise ValueError("title must not be empty")
    return normalized


def _normalize_priority(priority: str) -> Priority:
    if priority not in _PRIORITIES:
        raise ValueError("priority must be 'low', 'normal', or 'high'")
    return priority  # type: ignore[return-value]


def _normalize_due_date(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise TypeError("due_date must be a date, ISO date string, or None")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise TypeError("due_date must be a date, ISO date string, or None")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError("due_date must be a valid ISO date (YYYY-MM-DD)") from error


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        completed=bool(row["completed"]),
        priority=row["priority"],
        due_date=row["due_date"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


class TaskRepository:
    """Own task persistence in a single SQLite database."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        configured_path = db_path if db_path is not None else os.getenv("TODO_DB_PATH")
        self.db_path = (
            Path(configured_path).expanduser()
            if configured_path is not None
            else Path(__file__).resolve().parent.parent / "tasks.sqlite3"
        )
        self.db_path = self.db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a short-lived connection and always commit or roll back and close."""
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
                    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
                    priority TEXT NOT NULL DEFAULT 'normal'
                        CHECK (priority IN ('low', 'normal', 'high')),
                    due_date TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_completed_due_date "
                "ON tasks (completed, due_date)"
            )

    def create_task(
        self,
        title: str,
        *,
        priority: Priority = "normal",
        due_date: date | str | None = None,
    ) -> Task:
        normalized_title = _normalize_title(title)
        normalized_priority = _normalize_priority(priority)
        normalized_due_date = _normalize_due_date(due_date)
        now = _utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT INTO tasks
                   (title, completed, priority, due_date, created_at, updated_at, completed_at)
                   VALUES (?, 0, ?, ?, ?, ?, NULL)""",
                (normalized_title, normalized_priority, normalized_due_date, now, now),
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            assert row is not None
            return _task_from_row(row)

    def get_task(self, task_id: int) -> Task | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return _task_from_row(row) if row is not None else None

    def list_tasks(
        self,
        *,
        completed: bool | None = None,
        priority: Priority | None = None,
        order_by: str = "created_at",
        descending: bool = False,
    ) -> list[Task]:
        if order_by not in _ORDERABLE_COLUMNS:
            raise ValueError(f"unsupported task ordering: {order_by}")
        if priority is not None:
            _normalize_priority(priority)
        if completed is not None and not isinstance(completed, bool):
            raise TypeError("completed filter must be a bool or None")

        conditions: list[str] = []
        parameters: list[object] = []
        if completed is not None:
            conditions.append("completed = ?")
            parameters.append(int(completed))
        if priority is not None:
            conditions.append("priority = ?")
            parameters.append(priority)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        direction = "DESC" if descending else "ASC"
        query = (
            f"SELECT * FROM tasks{where_clause} "
            f"ORDER BY {order_by} {direction}, id ASC"
        )
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [_task_from_row(row) for row in rows]

    def update_task(self, task_id: int, changes: Mapping[str, object]) -> Task | None:
        unknown = set(changes) - _PATCHABLE_COLUMNS
        if unknown:
            raise ValueError(f"unsupported task fields: {', '.join(sorted(unknown))}")
        normalized: dict[str, object] = {}
        for column, value in changes.items():
            if column == "title":
                normalized[column] = _normalize_title(value)  # type: ignore[arg-type]
            elif column == "priority":
                normalized[column] = _normalize_priority(value)  # type: ignore[arg-type]
            elif column == "due_date":
                normalized[column] = _normalize_due_date(value)  # type: ignore[arg-type]
            elif column == "completed":
                if not isinstance(value, bool):
                    raise TypeError("completed must be a bool")
                normalized[column] = int(value)

        with self._connection() as connection:
            existing = connection.execute(
                "SELECT completed FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if existing is None:
                return None

            if "completed" in normalized:
                now_completed = bool(normalized["completed"])
                was_completed = bool(existing["completed"])
                if now_completed and not was_completed:
                    normalized["completed_at"] = _utc_now()
                elif not now_completed:
                    normalized["completed_at"] = None

            assignments = [f"{column} = ?" for column in normalized]
            values = list(normalized.values())
            assignments.append("updated_at = ?")
            values.append(_utc_now())
            values.append(task_id)
            connection.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?", values
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            assert row is not None
            return _task_from_row(row)

    def complete_task(self, task_id: int) -> Task | None:
        return self.update_task(task_id, {"completed": True})

    def delete_task(self, task_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cursor.rowcount > 0


class TaskTools:
    """Typed, SQL-free interface intended for application agents and services."""

    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def create_task(
        self,
        title: str,
        *,
        priority: Priority = "normal",
        due_date: date | str | None = None,
    ) -> Task:
        return self._repository.create_task(title, priority=priority, due_date=due_date)

    def get_task(self, task_id: int) -> Task | None:
        return self._repository.get_task(task_id)

    def list_tasks(
        self,
        *,
        completed: bool | None = None,
        priority: Priority | None = None,
        order_by: str = "created_at",
        descending: bool = False,
    ) -> list[Task]:
        return self._repository.list_tasks(
            completed=completed,
            priority=priority,
            order_by=order_by,
            descending=descending,
        )

    def update_task(self, task_id: int, changes: Mapping[str, object]) -> Task | None:
        return self._repository.update_task(task_id, changes)

    def complete_task(self, task_id: int) -> Task | None:
        return self._repository.complete_task(task_id)

    def delete_task(self, task_id: int) -> bool:
        return self._repository.delete_task(task_id)