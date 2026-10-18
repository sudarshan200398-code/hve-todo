"""Deterministic task use cases backed only by the typed TaskTools facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from tools.repository import Priority, Task, TaskTools


@dataclass(frozen=True, slots=True)
class TaskReference:
    task: Task | None
    ambiguous: bool = False


class TaskAgent:
    """Perform task CRUD and resolve unambiguous user-facing references."""

    def __init__(self, tools: TaskTools) -> None:
        self._tools = tools

    def create(
        self, title: str, *, priority: Priority = "normal", due_date: str | None = None
    ) -> Task:
        return self._tools.create_task(title, priority=priority, due_date=due_date)

    def list(self, *, completed: bool | None = None) -> list[Task]:
        return self._tools.list_tasks(completed=completed, order_by="id")

    def update(self, task_id: int, changes: Mapping[str, object]) -> Task | None:
        return self._tools.update_task(task_id, changes)

    def complete(self, task_id: int) -> Task | None:
        return self._tools.complete_task(task_id)

    def delete(self, task_id: int) -> bool:
        return self._tools.delete_task(task_id)

    def resolve_reference(self, reference: str) -> TaskReference:
        """Resolve only by ID or exact title; duplicate titles are ambiguous."""
        normalized = reference.strip()
        if normalized.startswith("#"):
            normalized = normalized[1:].strip()
        if normalized.isdecimal():
            return TaskReference(self._tools.get_task(int(normalized)))

        matches = [
            task
            for task in self._tools.list_tasks(order_by="id")
            if task.title.casefold() == normalized.casefold()
        ]
        if len(matches) > 1:
            return TaskReference(None, ambiguous=True)
        return TaskReference(matches[0] if matches else None)