from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agents import AssistantIntent, Orchestrator, PlannerAgent, SummaryAgent, TaskAgent
from tools import TaskRepository, TaskTools


@pytest.fixture
def repository(tmp_path):
    return TaskRepository(tmp_path / "agent-tasks.sqlite3")


@pytest.fixture
def tools(repository):
    return TaskTools(repository)


@pytest.fixture
def orchestrator(tools):
    return Orchestrator(tools, api_key="", today_provider=lambda: date(2026, 10, 19))


def test_fallback_add_example_extracts_title_tomorrow_and_priority(orchestrator, tools):
    result = orchestrator.handle("add buy milk tomorrow, high priority")

    assert result["agent"] == "task"
    assert result["mode"] == "fallback"
    assert result["task"].title == "buy milk"
    assert result["task"].due_date == "2026-10-20"
    assert result["task"].priority == "high"
    assert tools.list_tasks() == [result["task"]]


def test_task_agent_edits_completes_and_deletes_by_id(tools):
    agent = TaskAgent(tools)
    original = agent.create("Initial task")

    edited = agent.update(original.id, {"title": "Updated task", "priority": "high"})
    assert edited.title == "Updated task"
    assert edited.priority == "high"
    assert agent.complete(original.id).completed is True
    assert agent.delete(original.id) is True
    assert agent.list() == []


def test_orchestrator_complete_update_delete_and_list_routes(orchestrator, tools):
    task = tools.create_task("Buy milk")

    updated = orchestrator.handle(f"rename task {task.id} to Buy oat milk")
    assert updated["task"].title == "Buy oat milk"
    completed = orchestrator.handle(f"complete task {task.id}")
    assert completed["task"].completed is True
    listed = orchestrator.handle("list completed tasks")
    assert [item.id for item in listed["tasks"]] == [task.id]
    deleted = orchestrator.handle(f"delete task {task.id}")
    assert deleted["task"] is None
    assert tools.get_task(task.id) is None


def test_ambiguous_and_unknown_requests_do_not_mutate(orchestrator, tools):
    one = tools.create_task("Duplicate")
    two = tools.create_task("Duplicate")

    ambiguous = orchestrator.handle("complete Duplicate")
    unknown = orchestrator.handle("maybe take care of something")

    assert "more than one" in ambiguous["message"]
    assert "not sure" in unknown["message"]
    assert tools.get_task(one.id).completed is False
    assert tools.get_task(two.id).completed is False
    assert len(tools.list_tasks()) == 2


def test_unknown_create_request_never_writes(orchestrator, tools):
    result = orchestrator.handle("add tomorrow")

    assert result["task"] is None
    assert tools.list_tasks() == []


def test_planner_orders_overdue_then_priority_due_date_and_id(tools):
    today = date(2026, 10, 19)
    future_high = tools.create_task("Future high", priority="high", due_date="2026-10-20")
    overdue_low = tools.create_task("Overdue low", priority="low", due_date="2026-10-18")
    overdue_high_later = tools.create_task("Overdue high later", priority="high", due_date="2026-10-17")
    overdue_high_earlier = tools.create_task("Overdue high earlier", priority="high", due_date="2026-10-16")
    completed = tools.create_task("Already done", priority="high", due_date="2026-10-15")
    tools.complete_task(completed.id)

    planner = PlannerAgent(tools, today_provider=lambda: today)
    assert planner.suggest() == overdue_high_earlier
    assert [task.id for task in tools.list_tasks(completed=False)] == [
        future_high.id,
        overdue_low.id,
        overdue_high_later.id,
        overdue_high_earlier.id,
    ]


def test_planner_uses_high_priority_then_due_date_and_stable_id(tools):
    today = date(2026, 10, 19)
    tools.create_task("Normal earliest", priority="normal", due_date="2026-10-20")
    high_later = tools.create_task("High later", priority="high", due_date="2026-10-21")
    high_earlier = tools.create_task("High earlier", priority="high", due_date="2026-10-20")
    high_same_rank_later_id = tools.create_task(
        "High same rank later ID", priority="high", due_date="2026-10-20"
    )
    assert PlannerAgent(tools, today_provider=lambda: today).suggest() == high_earlier
    assert high_earlier.id < high_same_rank_later_id.id
    assert high_later.id < high_earlier.id


def test_planner_suggestion_is_advisory(orchestrator, tools):
    task = tools.create_task("Do not change me")
    result = orchestrator.suggest_next()

    assert result["agent"] == "planner"
    assert result["suggestion"] == task
    assert tools.get_task(task.id) == task


def test_daily_summary_counts_open_completed_due_and_completed_today(tools):
    today = datetime.now(timezone.utc).date().isoformat()
    due = tools.create_task("Due open", due_date=today)
    done_today = tools.create_task("Done today", due_date=today)
    tools.complete_task(done_today.id)
    tools.create_task("Other open")

    summary = SummaryAgent(tools).summarize()

    assert summary == {
        "open_count": 2,
        "completed_count": 1,
        "due_today_count": 2,
        "completed_today_count": 1,
    }
    assert tools.get_task(due.id).completed is False


def test_no_api_key_uses_fallback_without_constructing_openai(tools, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def unexpected_client(*args, **kwargs):
        raise AssertionError("OpenAI client should not be constructed")

    monkeypatch.setattr("openai.OpenAI", unexpected_client, raising=False)
    result = Orchestrator(tools).handle("add a task to call home")

    assert result["mode"] == "fallback"
    assert result["task"].title == "call home"


def test_mocked_structured_model_success_uses_ai_mode(tools):
    intent = AssistantIntent(
        action="create",
        title="Model-created task",
        due_date=None,
        priority="normal",
        task_reference=None,
        needs_clarification=False,
    )
    parse = Mock(return_value=SimpleNamespace(output_parsed=intent))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = Orchestrator(tools, api_key="test-key", model_client=client).handle("Please create a task")

    assert result["mode"] == "ai"
    assert result["task"].title == "Model-created task"
    parse.assert_called_once()
    assert parse.call_args.kwargs["model"] == "gpt-4o-mini"
    assert parse.call_args.kwargs["text_format"] is AssistantIntent


def test_model_error_falls_back_without_repeating_a_write(tools):
    parse = Mock(side_effect=TimeoutError("private provider detail"))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = Orchestrator(tools, api_key="test-key", model_client=client).handle(
        "add call home tomorrow"
    )

    assert result["mode"] == "fallback"
    assert result["task"].title == "call home"
    assert len(tools.list_tasks()) == 1
    parse.assert_called_once()
    assert "private provider detail" not in result["message"]


def test_invalid_model_intent_falls_back_and_openai_configuration_is_bounded(tools):
    invalid = SimpleNamespace(output_parsed={"action": "create", "title": ""})
    client = SimpleNamespace(responses=SimpleNamespace(parse=Mock(return_value=invalid)))
    result = Orchestrator(tools, api_key="test-key", model_client=client).handle("add task buy bread")

    assert result["mode"] == "fallback"
    assert result["task"].title == "buy bread"

    # The SDK client constructor is exercised only for real configured calls; its
    # bounded timeout and zero SDK retries are fixed in Orchestrator.
    assert Orchestrator.MODEL_TIMEOUT_SECONDS <= 15


def test_sdk_client_uses_bounded_timeout_and_disables_retries(tools, monkeypatch):
    intent = AssistantIntent(
        action="unknown",
        title=None,
        due_date=None,
        priority=None,
        task_reference=None,
        needs_clarification=True,
    )
    parse = Mock(return_value=SimpleNamespace(output_parsed=intent))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    constructor = Mock(return_value=client)
    monkeypatch.setattr("openai.OpenAI", constructor)

    result = Orchestrator(tools, api_key="configured-key").handle("unclear request")

    assert result["mode"] == "ai"
    constructor.assert_called_once_with(
        api_key="configured-key",
        timeout=Orchestrator.MODEL_TIMEOUT_SECONDS,
        max_retries=0,
    )
    parse.assert_called_once()