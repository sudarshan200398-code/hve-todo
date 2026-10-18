<!-- markdownlint-disable-file -->
---
title: Agentic Todo App Implementation Details
description: File-level implementation steps and validation details for the greenfield todo application.
ms.date: 2026-10-19
ms.topic: how-to
---

# Implementation Details: Agentic Todo App

## Context Reference

Sources: `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md`; `.copilot-tracking/research/subagents/2026-10-19/architecture-research.md`; `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md`; user request on 2026-10-19.

User-defined deployment command is `uvicorn main:app --host 0.0.0.0 --port $PORT` on Render Linux. For local Windows development, use `uvicorn main:app --host 0.0.0.0 --port 8003`. The Render command must use Render's provided `PORT`; do not add `--reload` to the deployment command.

## Implementation Phase 1: Persistence and Contracts

<!-- parallelizable: false -->

### Step 1.1: Create repository and task storage

Implement `TaskRepository` as the only module that imports/uses `sqlite3`. Use a stable app-root database path by default, with a `TODO_DB_PATH` environment override for test and deployment configuration. Use short-lived connections, `sqlite3.Row`, parameterized SQL, explicit connection close and transaction behavior, and an allowlist for patchable columns. No agent or API code may accept SQL or a raw connection.

Use a `tasks` table with `id`, required trimmed `title`, `completed`, `priority` (`low`, `normal`, `high`), nullable ISO date `due_date`, UTC `created_at`, UTC `updated_at`, and nullable UTC `completed_at`. Initialize schema idempotently. Keep due dates date-only and define “tomorrow” and day boundaries in UTC for this initial single-user app.

Files:
* `tools/__init__.py` - Package marker
* `tools/repository.py` - SQLite schema, `TaskRepository`, typed task values, CRUD, and tool facade
* `tests/test_repository.py` - Isolated repository behavior tests

Success criteria:
* Repository covers create/read/list/filter/update/complete/delete, missing IDs, ordering, and persistence.
* User text is bound as SQL values and is not interpreted as SQL.
* Every connection closes on success and failure; writes commit or roll back atomically.
* A forced write failure test verifies that partial changes roll back.
* Tests use per-test on-disk databases under pytest `tmp_path`.

Context references:
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 71-104) - Project shape and repository boundary
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 105-171) - Persistence, agents, API, test, and configuration recommendations
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 51-70) - SQLite versus ORM and safety details

Dependencies:
* None

### Step 1.2: Define runtime configuration and project metadata

Add `requirements.txt` with FastAPI, `uvicorn[standard]`, OpenAI SDK, pytest, and HTTPX. Select a Python 3.10+ runtime compatible with the current OpenAI SDK; verify and pin dependency versions together when implementing. Read `OPENAI_API_KEY` optionally and read `OPENAI_MODEL` for the structured-output model, defaulting to `gpt-4o-mini` and allowing configuration to override it. Verify the selected account/model supports Structured Outputs when implementing. No key must not block import or app startup; model/API failure must use the rule-based path.

Add `.gitignore` entries for `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.sqlite3`, `.env`, Python bytecode, and SQLite `-wal`/`-shm` sidecars. Never place secrets in source control.

Files:
* `requirements.txt` - Runtime and test dependencies
* `.gitignore` - Python environment, test output, secrets, and SQLite artifacts

Success criteria:
* Dependencies install together on the selected Python version, and the default model supports the chosen Structured Outputs call.
* The application can start with both `OPENAI_API_KEY` and `OPENAI_MODEL` unset.
* Requested ignore patterns are present and no real API secret is committed.

Context references:
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 198-210) - Dependency and ignore recommendations
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 29-50) - Structured intent and fallback decisions

Dependencies:
* Step 1.1 for database path and configuration integration

## Implementation Phase 2: Agent Services

<!-- parallelizable: false -->

### Step 2.1: Implement specialist agents and orchestrator

Add `TaskAgent` for create/list/update/complete/delete, `PlannerAgent` for a stable next-task suggestion, `SummaryAgent` for daily counts and status, and `Orchestrator` for intent dispatch. All agents receive only repository functions or a narrow typed tools interface. Planner suggestions do not mutate tasks; they select the next incomplete task by overdue first, then high priority, then earliest due date, then stable ID order. An explicit user command is needed to create tasks from a suggestion.

The model adapter can make one Structured Outputs intent-extraction request. The application validates fields/action, resolves references using repository reads, then dispatches to the agent. On missing/blank key or extraction/network/timeout/response validation errors, use a deterministic parser for documented common commands. Unknown or ambiguous input asks for clarification and must not mutate data. Model calls occur outside write transactions, with bounded timeout and retry settings. Return response text, agent name, mode (`ai`/`fallback`), and changed task/list payload as applicable.

Default product rules for this implementation:
* “Tomorrow” and daily-summary boundaries use UTC.
* Daily summary reports total open/completed tasks, tasks due today, and tasks completed today (using `completed_at`).
* An explicit, unambiguous delete command deletes immediately; the UI's delete button uses `window.confirm`.
* A planner suggestion is advisory only and never creates a task.
* Duplicate titles are allowed; task IDs are authoritative. Ambiguous natural-language references require clarification.

Files:
* `agents/__init__.py` - Package marker and exports if useful
* `agents/orchestrator.py` - Intent resolution, specialist selection, and response contract
* `agents/task_agent.py` - Task CRUD use cases through repository tools
* `agents/planner_agent.py` - Deterministic task prioritization and suggestions
* `agents/summary_agent.py` - UTC daily summary from repository data
* `tests/test_agents.py` - Deterministic routing and fallback tests

Success criteria:
* Task, planner, and summary agent responsibilities are isolated and route through injected repository tools only.
* Key-missing and model-error cases work without network and report fallback mode.
* Ambiguous/unknown instructions do not mutate task data.
* Tests cover example “add buy milk tomorrow, high priority”, task resolution, planner tie-breaking, daily summary, and mocked OpenAI success/failure.

Context references:
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 117-171) - Agent roles, model/fallback, and test coverage
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 18-50) - Plain Python and structured extraction alternatives

Dependencies:
* Implementation Phase 1 completion

### Step 2.2: Validate agent phase

Run focused tests after implementing the agent modules. Test with environment variables absent; mock the OpenAI client for configured and failed responses. Do not call the live API.

Validation commands:
* `pytest tests/test_repository.py tests/test_agents.py` - Repository and agent tests
* Static checks available in the implementation environment - Run if configured; do not add a linter solely for this proof of concept

## Implementation Phase 3: HTTP API and Single-Page UI

<!-- parallelizable: true -->

Phase 3 work may proceed in parallel across API and UI files because the endpoint contract below is fixed. The UI must not depend on implementation details beyond that contract.

### Step 3.1: Add FastAPI app and REST API

Create root `main.py` with `app = FastAPI()` and an injectable `create_app` or repository dependency for tests. Serve the code-owned `index.html` at `/` using `FileResponse`. Implement synchronous routes because SQLite and the OpenAI SDK are synchronous. Use this fixed API contract so API and UI tasks can proceed independently:

* `GET /api/tasks?completed={true|false}` returns `{"tasks": [Task, ...]}`; omit `completed` to list all.
* `POST /api/tasks` accepts `{"title": str, "priority": "low"|"normal"|"high", "due_date": "YYYY-MM-DD"|null}` and returns one `Task` with HTTP 201.
* `GET /api/tasks/{task_id}` returns one `Task`.
* `PATCH /api/tasks/{task_id}` accepts one or more of `title`, `completed`, `priority`, `due_date` and returns the updated `Task`.
* `DELETE /api/tasks/{task_id}` returns an empty HTTP 204 response.
* `POST /api/assistant` accepts `{"message": str}` and returns `{"message": str, "agent": str, "mode": "ai"|"fallback", "task": Task|null, "tasks": [Task, ...]|null, "suggestion": Task|null, "summary": Summary|null}`.
* `POST /api/assistant/suggest-next` accepts an empty JSON object and returns the assistant result shape with `agent="planner"` and populated `suggestion`.
* `GET /api/assistant/daily-summary` returns the assistant result shape with `agent="summary"` and populated `summary`.

Each `Task` contains `id`, `title`, `completed`, `priority`, `due_date`, `created_at`, `updated_at`, and `completed_at`. `Summary` contains `open_count`, `completed_count`, `due_today_count`, and `completed_today_count`. All three assistant endpoints call the same agent implementations. Return HTTP 404 when a referenced task does not exist and a consistent error body for validation/not-found errors.

Use Pydantic request/response schemas, trim/reject empty titles, validate priority/date fields, reject empty or unknown PATCH fields, return 201 for create, 404 for missing records, and 204 for successful delete. Return consistent assistant result data including mode and agent. Initialize the database through app lifespan or explicit repository setup without creating multiple schema implementations.

Files:
* `main.py` - Module-level FastAPI app, root response, dependency injection, CRUD and assistant routes
* `tests/test_api.py` - Root, HTTP status, schema validation, CRUD, and assistant contract tests

Success criteria:
* `uvicorn main:app` imports the app and `GET /` serves the single HTML file.
* All REST operations return their documented status and payload; missing IDs return 404.
* Routes use `TaskRepository` and agent APIs without direct SQL or raw connection access.
* Test app uses a temporary DB and fake model adapter; no test makes a live network call.
* Hostile task titles and assistant response strings remain literal text in API/UI rendering and cannot inject markup or alter page structure.

Context references:
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 105-171) - Endpoints, response semantics, and test injection
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 71-90) - FileResponse, sync routes, and test dependency injection

Dependencies:
* Implementation Phase 1 and Phase 2 completion

### Step 3.2: Build the single-file task UI

Create one `index.html` with inline styles and JavaScript. Display open/completed tasks and due date/priority; provide add/edit/complete/delete actions, an assistant request box, Suggest next, and Daily summary controls. Use same-origin `fetch` calls to the API, safe DOM construction/`textContent`, accessible labels, visible loading/error feedback, and the API response's mode to indicate whether AI or fallback handled a request. Refresh the list after CRUD or assistant mutations.

Files:
* `index.html` - Single-page task list and assistant interactions

Success criteria:
* No additional HTML page or frontend build system is introduced.
* All requested UI actions reach the corresponding API behavior and show returned task/assistant state.
* User and assistant strings are rendered without unsafe `innerHTML` insertion.
* UI degrades with clear status/errors when API calls fail and indicates fallback mode when used.
* A UI/API test or documented browser smoke test uses hostile markup-like task and assistant content and verifies it is rendered as text.

Context references:
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 105-116) - Root file delivery and API route choices
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 130-145) - Safe UI behavior and assistant status

Dependencies:
* The fixed API contract above; implementation does not depend on Step 3.1 completing first

## Implementation Phase 4: Launch and Final Validation

<!-- parallelizable: false -->

### Step 4.1: Configure Render and local launch commands

Set the Render Linux Start Command exactly to `uvicorn main:app --host 0.0.0.0 --port $PORT`. Do not substitute a Python launcher or append reload. Confirm Render injects `PORT` and that the working directory contains root `main.py`. For local Windows execution, use `uvicorn main:app --host 0.0.0.0 --port 8003`; optionally add `--reload` for local-only development.

Success criteria:
* Render start command exactly preserves the user-specified form and binds the provided port.
* Local launch works on port 8003.
* SQLite path and storage behavior are understood for Render. Configure a Render persistent disk if tasks must survive redeploys/restarts; use the default writable app directory for ephemeral demo data only.

Context references:
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 198-210) - User command and dependencies
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 91-112) - Verified Uvicorn import target, flags, and PORT shell expansion

Dependencies:
* Implementation Phase 3 completion

### Step 4.2: Run full validation

Install dependencies, run all tests, verify required file structure and ignore patterns, and launch locally at port 8003. Make an HTTP smoke check for `/`, CRUD, and assistant fallback, then verify Render's configured start command text. Do not require an API key or make billable external calls.

Validation commands:
* `python -m pip install -r requirements.txt` - Install app and test dependencies
* `pytest` - Run complete test suite
* `uvicorn main:app --host 0.0.0.0 --port 8003` - Local runtime smoke test
* Render dashboard/configuration check - Confirm exact deployment start command and persistent-storage choice

### Step 4.3: Fix minor issues and report blockers

Fix isolated validation failures. After any fix, rerun the failing check, the full `pytest` suite, and affected HTTP/UI smoke checks. If tests reveal a need for broad architectural changes, additional research, or a database migration, stop and document the blocker and next action rather than expanding scope silently.

## Dependencies

* Python 3.10 or later, compatible with selected FastAPI/OpenAI package versions
* FastAPI, `uvicorn[standard]`, OpenAI Python SDK, pytest, and HTTPX
* Render Linux service with a writable working directory and the supplied `PORT`; persistent disk when preserving tasks is required
* No API key for startup, CRUD, tests, or deterministic fallback

## Success Criteria

* The application satisfies the user's requested root app, single-page UI, SQLite-only repository boundary, named agent delegation, REST CRUD, optional LLM, fallback, tests, requirements, and ignore file.
* The deployment launch command is exactly `uvicorn main:app --host 0.0.0.0 --port $PORT`; local launch uses port 8003.
* Repository/API/agent/UI validation passes with no live model calls and with credentials absent.
