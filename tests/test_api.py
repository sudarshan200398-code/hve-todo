import pytest
from fastapi.testclient import TestClient

import main
from tools import TaskRepository


class FakeModelAdapter:
    def __init__(self):
        self.calls = []

    def extract_intent(self, message):
        self.calls.append(message)
        return None


class FakeOrchestrator:
    def __init__(self, model_adapter):
        self.model_adapter = model_adapter

    def handle(self, message):
        self.model_adapter.calls.append(message)
        return {
            "message": f"Received literally: {message}",
            "agent": "task",
            "mode": "fallback",
        }


class FakePlannerAgent:
    def suggest(self):
        return {
            "message": "Suggested one task.",
            "mode": "fallback",
            "suggestion": {
                "id": 14,
                "title": "Plan the release",
                "completed": False,
                "priority": "high",
                "due_date": None,
                "created_at": "2026-10-19T00:00:00+00:00",
                "updated_at": "2026-10-19T00:00:00+00:00",
                "completed_at": None,
            },
        }


class FakeSummaryAgent:
    def summarize(self):
        return {
            "message": "Daily totals.",
            "mode": "fallback",
            "summary": {
                "open_count": 2,
                "completed_count": 1,
                "due_today_count": 1,
                "completed_today_count": 0,
            },
        }


@pytest.fixture
def client(tmp_path):
    adapter = FakeModelAdapter()
    app = main.create_app(
        repository=TaskRepository(tmp_path / "api.sqlite3"),
        orchestrator=FakeOrchestrator(adapter),
        planner_agent=FakePlannerAgent(),
        summary_agent=FakeSummaryAgent(),
        model_adapter=adapter,
    )
    return TestClient(app), adapter


def test_root_serves_code_owned_html_file(client, tmp_path, monkeypatch):
    test_html = tmp_path / "index.html"
    test_html.write_text("<main>Todo app</main>", encoding="utf-8")
    monkeypatch.setattr(main, "INDEX_FILE", test_html)

    response = client[0].get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == "<main>Todo app</main>"


def test_task_crud_and_completed_filter(client):
    http = client[0]
    create_response = http.post(
        "/api/tasks",
        json={"title": "  Write API tests  ", "priority": "high", "due_date": "2026-10-20"},
    )
    assert create_response.status_code == 201
    task = create_response.json()
    assert task["title"] == "Write API tests"
    assert task["completed"] is False
    assert task["priority"] == "high"
    assert task["due_date"] == "2026-10-20"
    assert set(task) == {
        "id", "title", "completed", "priority", "due_date", "created_at", "updated_at", "completed_at"
    }

    task_id = task["id"]
    assert http.get(f"/api/tasks/{task_id}").json() == task
    assert http.get("/api/tasks").json() == {"tasks": [task]}
    assert http.get("/api/tasks?completed=true").json() == {"tasks": []}

    patch_response = http.patch(
        f"/api/tasks/{task_id}", json={"title": "Ship", "completed": True}
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["title"] == "Ship"
    assert patch_response.json()["completed"] is True
    assert http.get("/api/tasks?completed=true").json()["tasks"][0]["id"] == task_id

    delete_response = http.delete(f"/api/tasks/{task_id}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert http.get(f"/api/tasks/{task_id}").status_code == 404


def test_validation_is_strict_and_errors_have_consistent_shape(client):
    http = client[0]
    bad_requests = [
        http.post("/api/tasks", json={"title": "  "}),
        http.post("/api/tasks", json={"title": "Valid", "priority": "urgent"}),
        http.post("/api/tasks", json={"title": "Valid", "due_date": "2026-02-30"}),
        http.post("/api/tasks", json={"title": "Valid", "unknown": True}),
    ]
    for response in bad_requests:
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    task_id = http.post("/api/tasks", json={"title": "Patch me"}).json()["id"]
    for patch in ({}, {"invalid": "field"}, {"title": None}, {"completed": "true"}):
        response = http.patch(f"/api/tasks/{task_id}", json=patch)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_missing_task_responses_use_consistent_not_found_shape(client):
    http = client[0]
    responses = [
        http.get("/api/tasks/98765"),
        http.patch("/api/tasks/98765", json={"title": "Missing"}),
        http.delete("/api/tasks/98765"),
    ]
    for response in responses:
        assert response.status_code == 404
        assert response.json() == {
            "error": {"code": "not_found", "message": "Task not found"}
        }


def test_assistant_routes_use_injected_services_and_fixed_response_shapes(client):
    http, adapter = client
    hostile_message = "<img src=x onerror=alert(1)>"
    response = http.post("/api/assistant", json={"message": hostile_message})

    assert response.status_code == 200
    assert response.json() == {
        "message": f"Received literally: {hostile_message}",
        "agent": "task",
        "mode": "fallback",
        "task": None,
        "tasks": None,
        "suggestion": None,
        "summary": None,
    }
    assert adapter.calls == [hostile_message]

    suggestion = http.post("/api/assistant/suggest-next", json={})
    assert suggestion.status_code == 200
    assert suggestion.json()["agent"] == "planner"
    assert suggestion.json()["mode"] == "fallback"
    assert suggestion.json()["suggestion"]["title"] == "Plan the release"

    summary = http.get("/api/assistant/daily-summary")
    assert summary.status_code == 200
    assert summary.json()["agent"] == "summary"
    assert summary.json()["summary"] == {
        "open_count": 2,
        "completed_count": 1,
        "due_today_count": 1,
        "completed_today_count": 0,
    }


def test_hostile_task_title_is_returned_as_literal_json(client):
    http = client[0]
    hostile_title = "<script>alert('x')</script>"

    response = http.post("/api/tasks", json={"title": hostile_title})

    assert response.status_code == 201
    assert response.json()["title"] == hostile_title
    assert hostile_title in response.text
