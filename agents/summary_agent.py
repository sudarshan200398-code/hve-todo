"""UTC daily task counts assembled through the typed task tools."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TypedDict

from tools.repository import TaskTools


class DailySummary(TypedDict):
    open_count: int
    completed_count: int
    due_today_count: int
    completed_today_count: int


class SummaryAgent:
    """Report total status counts and UTC date-specific counts."""

    def __init__(self, tools: TaskTools) -> None:
        self._tools = tools

    def summarize(self, on_date: date | None = None) -> DailySummary:
        today = (on_date or datetime.now(timezone.utc).date()).isoformat()
        tasks = self._tools.list_tasks()
        return {
            "open_count": sum(not task.completed for task in tasks),
            "completed_count": sum(task.completed for task in tasks),
            "due_today_count": sum(task.due_date == today for task in tasks),
            "completed_today_count": sum(
                task.completed
                and task.completed_at is not None
                and task.completed_at[:10] == today
                for task in tasks
            ),
        }