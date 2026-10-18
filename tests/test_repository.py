from datetime import date

import pytest

from tools import Task, TaskRepository, TaskTools
import tools.repository as repository_module


@pytest.fixture
def repository(tmp_path):
    return TaskRepository(tmp_path / "tasks.sqlite3")


def test_create_read_and_persist_task(repository, tmp_path):
    task = repository.create_task(
        "  Write tests  ", priority="high", due_date=date(2026, 10, 20)
    )

    assert isinstance(task, Task)
    assert task.title == "Write tests"
    assert task.completed is False
    assert task.priority == "high"
    assert task.due_date == "2026-10-20"
    assert task.completed_at is None
    assert task.created_at.endswith("+00:00")
    assert repository.get_task(task.id) == task
    assert TaskRepository(tmp_path / "tasks.sqlite3").get_task(task.id) == task


def test_create_validates_title_priority_and_due_date(repository):
    with pytest.raises(ValueError, match="title"):
        repository.create_task("  ")
    with pytest.raises(ValueError, match="priority"):
        repository.create_task("Task", priority="urgent")
    with pytest.raises(ValueError, match="ISO date"):
        repository.create_task("Task", due_date="2026-02-30")


def test_user_text_is_stored_as_a_value_not_sql(repository):
    injected_title = "Task'); DROP TABLE tasks; --"
    created = repository.create_task(injected_title)

    assert repository.get_task(created.id).title == injected_title
    assert [task.id for task in repository.list_tasks()] == [created.id]


def test_list_filters_and_orders_tasks(repository):
    late = repository.create_task("Zulu", priority="low", due_date="2026-10-30")
    early = repository.create_task("Alpha", priority="high", due_date="2026-10-20")
    repository.complete_task(early.id)

    assert [task.title for task in repository.list_tasks(order_by="title")] == [
        "Alpha",
        "Zulu",
    ]
    assert [task.id for task in repository.list_tasks(completed=True)] == [early.id]
    assert [task.id for task in repository.list_tasks(priority="low")] == [late.id]
    assert [task.id for task in repository.list_tasks(order_by="due_date")] == [
        early.id,
        late.id,
    ]
    assert [task.id for task in repository.list_tasks(order_by="id", descending=True)] == [
        early.id,
        late.id,
    ]


def test_update_and_complete_manage_timestamps(repository):
    task = repository.create_task("Initial")
    updated = repository.update_task(
        task.id, {"title": " Renamed ", "priority": "high", "due_date": "2026-11-01"}
    )

    assert updated.title == "Renamed"
    assert updated.priority == "high"
    assert updated.due_date == "2026-11-01"
    assert updated.updated_at >= task.updated_at

    completed = repository.complete_task(task.id)
    assert completed.completed is True
    assert completed.completed_at is not None
    reopened = repository.update_task(task.id, {"completed": False, "due_date": None})
    assert reopened.completed is False
    assert reopened.completed_at is None
    assert reopened.due_date is None


def test_missing_ids_and_delete(repository):
    assert repository.get_task(999) is None
    assert repository.update_task(999, {"title": "Missing"}) is None
    assert repository.complete_task(999) is None
    assert repository.delete_task(999) is False

    task = repository.create_task("Delete me")
    assert repository.delete_task(task.id) is True
    assert repository.get_task(task.id) is None


def test_update_fields_and_ordering_are_allowlisted(repository):
    task = repository.create_task("Safe")
    with pytest.raises(ValueError, match="unsupported task fields"):
        repository.update_task(task.id, {"created_at": "forged"})
    with pytest.raises(ValueError, match="unsupported task ordering"):
        repository.list_tasks(order_by="title; DROP TABLE tasks")
    assert repository.get_task(task.id).title == "Safe"


def test_failed_write_rolls_back_insert(repository, monkeypatch):
    def fail_mapping(_row):
        raise RuntimeError("forced failure after insert")

    monkeypatch.setattr(repository_module, "_task_from_row", fail_mapping)
    with pytest.raises(RuntimeError, match="forced failure"):
        repository.create_task("Must roll back")

    monkeypatch.undo()
    assert repository.list_tasks() == []


def test_typed_task_tools_facade(repository):
    tools = TaskTools(repository)
    task = tools.create_task("Facade task", priority="normal")

    assert tools.get_task(task.id) == task
    assert tools.list_tasks() == [task]
    assert tools.complete_task(task.id).completed is True
    assert tools.delete_task(task.id) is True