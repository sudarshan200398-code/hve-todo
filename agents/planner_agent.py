"""Read-only deterministic next-task recommendations."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable

from tools.repository import Task, TaskTools


class PlannerAgent:
    """Recommend an incomplete task without changing persisted state."""

    def __init__(self, tools: TaskTools, *, today_provider: Callable[[], date] | None = None):
        self._tools = tools
        self._today_provider = today_provider or (lambda: datetime.now(timezone.utc).date())

    def suggest(self) -> Task | None:
        today = self._today_provider().isoformat()
        tasks = self._tools.list_tasks(completed=False)
        priority_order = {"high": 0, "normal": 1, "low": 2}

        def rank(task: Task) -> tuple[bool, int, bool, str, int]:
            overdue = task.due_date is not None and task.due_date < today
            return (
                not overdue,
                priority_order[task.priority],
                task.due_date is None,
                task.due_date or "",
                task.id,
            )

        return min(tasks, key=rank) if tasks else None