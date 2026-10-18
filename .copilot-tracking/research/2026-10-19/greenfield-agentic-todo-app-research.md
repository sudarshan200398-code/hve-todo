<!-- markdownlint-disable-file -->
---
title: Greenfield Agentic Todo App Research
description: Architecture and implementation research for a FastAPI, SQLite, and optional-LLM todo application.
ms.date: 2026-10-19
ms.topic: architecture
---

## Scope

Research a greenfield single-page todo application with a root-level FastAPI entry point, a single `index.html`, SQLite, conversational agent delegation, an optional OpenAI integration, deterministic fallback behavior, REST CRUD, and pytest coverage. The requested workspace initially contained no application source, dependency manifest, tests, or local project conventions. This report recommends an implementation; it does not create the application.

## Task Implementation Requests

* Expose a module-level FastAPI `app` from root `main.py` and serve `index.html` at `/`.
* Persist tasks in SQLite, accessed only by agents and routes through `TaskRepository` in `tools/repository.py`.
* Implement an orchestrator delegating task mutations, planning, and summaries to dedicated agents in `agents/`.
* Use `OPENAI_API_KEY` when available and retain useful rule-based behavior without it or when a model call fails.
* Provide plain REST CRUD, a task-list/assistant UI, Suggest next and Daily summary actions, pytest tests, `requirements.txt`, `.gitignore`, and the requested Uvicorn launch configuration.

## Scope and Success Criteria

* Scope: Architecture selection, API and agent flow, SQLite lifecycle and security, no-key degradation, testing, dependencies, static HTML delivery, and launch behavior. This research does not settle UI visual design or implement features.
* Assumptions: The application is a small single-instance proof of concept; its UI and API share an origin; the conversational assistant is desired; direct CRUD remains available without an LLM. SQLite storage must be persistent for the deployment if tasks are expected to survive restarts.
* Success Criteria:
  * One clear, evidence-based implementation approach with responsibilities matching the requested file layout.
  * No agent or API module bypasses `TaskRepository` for database access.
  * Missing credentials or an unavailable model do not prevent startup or core todo usage.
  * Suggestions for deterministic tests, security controls, dependencies, and the specified launch command are actionable.

## Outline

1. Recommended project structure and dependency flow.
2. Repository, API, agent, model and fallback design.
3. Alternatives and evidence-based selection.
4. Test plan, launch notes, unresolved decisions, and references.

## Research Executed

### File Analysis

* Workspace root (`c:\Users\hari2\todo-poc\hve-todo`)
  * Workspace structure was empty at inspection, with no existing code or repo-specific instructions to preserve.
* `.copilot-tracking/research/subagents/2026-10-19/architecture-research.md`
  * Initial broad research on project architecture, persistence, API, dependencies, fallback design, and tests.
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md`
  * Phase 2 comparison of architecture alternatives and verification of Uvicorn flags and `PORT` handling.

### Code Search Results

* No code search was applicable because no application source existed in the workspace.

### External Research

* Official FastAPI documentation: application setup, sync/async behavior, responses, dependencies, and tests.
  * Sources: [First steps](https://fastapi.tiangolo.com/tutorial/first-steps/), [Concurrency](https://fastapi.tiangolo.com/async/), [Custom responses](https://fastapi.tiangolo.com/advanced/custom-response/), [Testing](https://fastapi.tiangolo.com/tutorial/testing/), [dependency overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/).
* Official Python/SQLite documentation: parameter binding, connections, transactions, and row factories.
  * Sources: [sqlite3](https://docs.python.org/3/library/sqlite3.html), [SQLite use cases](https://www.sqlite.org/whentouse.html).
* Official OpenAI documentation: Python SDK, structured outputs, and function calling.
  * Sources: [Python SDK](https://github.com/openai/openai-python), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Function calling](https://developers.openai.com/api/docs/guides/function-calling).
* Official pytest and Uvicorn docs: fixtures, temp paths, environment testing, CLI target and flags.
  * Sources: [pytest](https://docs.pytest.org/en/stable/), [pytest tmp_path](https://docs.pytest.org/en/stable/how-to/tmp_path.html), [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html), [Uvicorn settings](https://www.uvicorn.org/settings/).

### Project Conventions

* Standards referenced: FastAPI, Python `sqlite3`, OpenAI SDK/API, pytest, Uvicorn, and applicable workspace Markdown/writing instructions.
* Instructions followed: Research-only mode restricts workspace writes to `.copilot-tracking/research/`; no app files were modified. No project-specific instructions were present.

## Key Discoveries

### Project Structure

Recommended flat layout, preserving the required root `main.py` module path:

```text
main.py
index.html
agents/
  __init__.py
  orchestrator.py
  task_agent.py
  planner_agent.py
  summary_agent.py
tools/
  __init__.py
  repository.py
tests/
  test_api.py
  test_repository.py
  test_agents.py
requirements.txt
.gitignore
```

Keep one-directional dependency flow:

```text
index.html -> FastAPI routes in main.py
CRUD routes -> tools/repository.py -> TaskRepository -> SQLite
assistant route -> agents/orchestrator.py -> specialist agent -> repository tools
```

The boundary is strict: `tools/repository.py` owns SQLite imports, connections, schema, transactions, queries, and row mapping. Routes and agents call a repository/tool interface. Agents never receive raw connections, paths, SQL, or unrestricted database capabilities.

### Implementation Patterns

#### API and UI

Use a module-level `app = FastAPI(...)` in root `main.py`. Expose conventional `/api/tasks` CRUD endpoints with Pydantic validation. Serve the fixed, code-owned `index.html` path at `/` using `FileResponse(Path(__file__).resolve().parent / "index.html")`; this is less dependent on the process working directory than a relative path. Keep inline CSS and JavaScript in the one HTML file, use same-origin `fetch`, and render task/assistant text with `textContent` rather than interpolating untrusted values into `innerHTML`.

Suggested endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Serve the single-page UI |
| `GET` | `/api/tasks` | List tasks, with an optional completion filter |
| `POST` | `/api/tasks` | Create a task; return `201` |
| `GET` | `/api/tasks/{task_id}` | Retrieve one task; return `404` if absent |
| `PATCH` | `/api/tasks/{task_id}` | Update allowlisted fields; return `404` if absent |
| `DELETE` | `/api/tasks/{task_id}` | Delete task; return `204` or `404` |
| `POST` | `/api/assistant` | Process natural-language request and return response, agent, mode, and changed-task information |
| `POST` | `/api/assistant/suggest-next` | Return planner recommendation |
| `GET` or `POST` | `/api/assistant/daily-summary` | Return summary; choose method based on whether a date/filter is supplied |

A simpler alternative is one assistant endpoint with an explicit `action` discriminator for chat, suggestion, and summary. Whichever contract is chosen, buttons should call the same Planner/Summary agents as the natural-language orchestrator, not duplicate business logic in JavaScript.

#### Repository and SQLite

Use Python's standard-library `sqlite3`. A minimal task record can include `id`, `title`, `description`, `completed`, `priority`, `due_date`, `created_at`, and `updated_at`; choose only fields actually used by the UI and agents. Store a date (not an implicit timestamp) for “tomorrow” unless reminders/time-of-day are added. Decide a timezone/date policy explicitly. Add a stable default path anchored to `Path(__file__).resolve()` and allow a `TODO_DB_PATH` override for tests/deployment.

Open/close SQLite connections for short operations or a request unit of work; do not share a global connection. Use `sqlite3.Row`, parameter placeholders for all user-provided values, explicit transaction handling, and a code-owned allowlist for patch columns. SQLite connection context managers do not close connections, so close explicitly in `finally` or `contextlib.closing`. `CREATE TABLE IF NOT EXISTS` initializes fresh databases but does not migrate changed schemas. Use a temporary on-disk DB for API tests; isolated `:memory:` databases do not persist across connections.

#### Agents and Orchestration

Implement each requested agent as a small Python class or function with typed inputs and outputs, all depending on a repository tool interface. The orchestrator classifies intent and delegates to one specialist. The Task Agent owns create/update/complete/delete operations. The Planner Agent ranks existing tasks and suggests a next action; a suggestion should not create or mutate tasks unless the user explicitly asks. The Summary Agent reads tasks and produces daily/completion summaries. Keep their natural language decisions separate from deterministic persistence operations.

Recommended request flow:

1. Receive the user's request at `/api/assistant`.
2. If configured, ask the model for a constrained intent object (action, title, due date, priority, task reference, or clarification needed).
3. Validate and normalize the proposed intent in application code.
4. Resolve any task reference against repository results; ask for clarification on ambiguous identity.
5. Route to the appropriate specialist agent.
6. The agent calls only explicit repository tools and returns a structured result.
7. Respond with assistant text plus `agent`, `mode` (`ai` or `fallback`), and any updated task data for UI refresh.

This preserves the user's agent structure without an orchestration framework. It also keeps the model from deciding SQL or directly performing unvalidated writes.

#### LLM and Rule-Based Fallback

The key is optional. Check `OPENAI_API_KEY` before constructing an OpenAI SDK client; missing or blank values must not cause import/startup failure. The no-key path should still handle a documented narrow grammar for common actions such as add, list, complete, update, delete, suggest, and summarize. Unsupported or ambiguous commands should explain supported actions or ask a question without mutating data.

When a model is enabled, prefer one Structured Outputs intent-extraction call over model tool calling for this small app. The server owns dispatch, tool selection, validation, and CRUD. Catch model/network/schema failures and run the deterministic parser. Bound model-call timeout and retries to avoid long waits. Return the effective mode so the UI can explain whether rule-based parsing was used. Never expose or log API keys, raw provider errors, or unnecessary task content.

Example (illustrative intent shape):

```python
from typing import Literal
from pydantic import BaseModel

class AssistantIntent(BaseModel):
    action: Literal["create", "update", "complete", "delete", "list", "suggest", "summary", "unknown"]
    title: str | None = None
    due_date: str | None = None
    priority: Literal["low", "normal", "high"] | None = None
    task_reference: str | None = None
    needs_clarification: bool = False
```

For “add buy milk tomorrow, high priority,” parsing should yield a create action with title “buy milk”, the next calendar date as the due date under the chosen timezone policy, and high priority. Model output remains a proposal: the server validates the result and invokes the Task Agent. In fallback, support the same example only if the deterministic parser can extract it unambiguously; otherwise ask for clarification, never guess and write.

### Complete Examples

A repository facade should provide narrowly scoped operations rather than SQL access. The shape below is illustrative; it is not a workspace implementation:

```python
class TaskRepository:
    def create_task(self, *, title: str, due_date: str | None, priority: str) -> Task: ...
    def list_tasks(self, *, completed: bool | None = None) -> list[Task]: ...
    def get_task(self, task_id: int) -> Task | None: ...
    def update_task(self, task_id: int, changes: TaskChanges) -> Task | None: ...
    def delete_task(self, task_id: int) -> bool: ...
```

All agents should receive this interface (or a similarly constrained tools facade). Avoid exposing generic `execute(sql, params)` to agents, since that weakens the promised repository boundary.

### API and Schema Documentation

* FastAPI module-level app and routing: [First steps](https://fastapi.tiangolo.com/tutorial/first-steps/).
* Synchronous endpoints with blocking libraries: [FastAPI concurrency](https://fastapi.tiangolo.com/async/). Use normal `def` route handlers for synchronous `sqlite3` and SDK calls; do not directly block inside `async def` handlers.
* Static files: [FastAPI FileResponse and HTMLResponse](https://fastapi.tiangolo.com/advanced/custom-response/).
* Pydantic request validation: [FastAPI request bodies](https://fastapi.tiangolo.com/tutorial/body/).
* SQLite connections, transactions, and parameter binding: [Python sqlite3 docs](https://docs.python.org/3/library/sqlite3.html) and [SQLite workload guidance](https://www.sqlite.org/whentouse.html).
* Structured model outputs: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Schema conformance does not guarantee the extracted intent is semantically correct; validate it again.
* Model tool execution mechanics: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling). It adds dispatch and usually additional round trips, not needed when application code owns the flow.
* Test dependencies with overrides: [FastAPI dependency overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/).

### Configuration Examples

Recommended direct dependencies in `requirements.txt` are `fastapi`, `uvicorn[standard]`, and `openai`. Add `pytest` and `httpx` for tests, either in the same file for a compact POC or a documented dev requirements file. Pin compatible versions after selecting Python version and testing the environment; do not hardcode unverified “latest” versions. `sqlite3`, `pathlib`, and `os` are in the Python standard library.

The requested `.gitignore` entries must include `.venv/`, `__pycache__/`, `.pytest_cache/`, and `*.sqlite3`. Also ignore `.env`, `*.py[cod]`, and SQLite sidecar files (`*-wal`, `*-shm`). Never commit a real `OPENAI_API_KEY`.

Run the requested launch command in a POSIX shell with `PORT` set:

```bash
uvicorn main:app --host 0.0.0.0 --port "$PORT"
```

For local Windows shells, `$PORT` is not portable Uvicorn syntax. PowerShell uses `$env:PORT`, while cmd.exe uses `%PORT%`. The most portable deployment pattern is a small Python entry point that reads `int(os.environ.get("PORT", "8000"))` and calls `uvicorn.run("main:app", host="0.0.0.0", port=port)`. For local development, use a fixed `--port 8000`; use `--reload` only in development. The required root import target is `main:app`, not `app.main:app`.

## Technical Scenarios

### Natural-language task command and assistant actions

**Requirements:** Interpret common user phrasing, including due dates and priorities; delegate to task/planner/summary agents; keep all database access inside the repository module; preserve useful operation without a key; expose Suggest next and Daily summary actions.

**Preferred Approach:** Use plain Python agent classes with one orchestrator. Make optional OpenAI Structured Outputs extract a constrained intent; keep the server responsible for validation, agent routing, and repository calls. Use a deliberately narrow deterministic parser when no key exists or model calls fail. This fits the requested files while avoiding extra framework/runtime state and prevents model-generated tool names or SQL from being trusted.

```text
POST /api/assistant
  -> Orchestrator
       -> intent parser (OpenAI structured extraction, else deterministic rules)
       -> validation and task reference resolution
       -> TaskAgent | PlannerAgent | SummaryAgent
            -> repository tools
                 -> TaskRepository
                      -> SQLite
```

**Implementation Details:**

* Use exact allowlisted action values and field constraints. Reject blank titles, invalid priorities, malformed dates, empty PATCH bodies, and unknown update fields.
* For dates, establish whether “tomorrow” uses the server timezone or a configured user timezone. Date-only storage avoids accidental reminder time semantics.
* Do not start a write transaction before the model call. Resolve ambiguity before mutation; require explicit confirmation if the product chooses that for deletion.
* Planner should rank deterministically (for example, overdue first, then high priority, then due date, then stable creation/id order). Document tie-breaking.
* Summary should use repository data and a stable calculation boundary for “daily”; define whether that means created today, due today, or completed today.
* Return typed response data that the UI can use to refresh task state without interpreting free-form assistant prose.

#### Considered Alternatives

* OpenAI Agents SDK: reconsider only if persistent sessions, multi-step approvals, tracing, or genuinely complex handoffs become necessary. For this flow, plain classes keep behavior transparent and tests lightweight. See [Agents SDK overview](https://openai.github.io/openai-agents-python/) and the alternative analysis in `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md`.
* OpenAI function calling for CRUD: useful when the model genuinely must choose callable capabilities, but unnecessary here because deterministic server orchestration already knows the requested action. It adds a tool-call loop and further failure surface. If later adopted, allowlist tool names and validate all arguments server-side.
* Rules-only parsing: excellent for no-key reliability, but too narrow as the only parser if natural-language coverage is a core feature. Keep it as the fallback and fail closed for ambiguous phrases.

### HTTP, persistence, and tests

**Requirements:** Plain REST CRUD, a root-served HTML page, safe SQLite storage, independent tests, and no credential or network requirement for the test suite.

**Preferred Approach:** Use FastAPI with normal synchronous route handlers, a code-owned `FileResponse`, standard-library SQLite behind `TaskRepository`, and an injected repository/database path for tests. Use parameterized SQL and short connection/transaction lifetimes. This matches the blocking SQLite/OpenAI client stack and avoids an ORM dependency for a single-table POC.

**Implementation Details:**

* Keep `app = FastAPI()` importable from `main.py`; schema initialization should be idempotent at startup or repository initialization.
* Make task ordering explicit and stable. Check update/delete affected rows to return 404 accurately.
* Use temporary on-disk SQLite files under pytest `tmp_path`; inject the DB path/repository through a FastAPI dependency override or app factory.
* Cover CRUD status codes, validation, persistence, hostile text, agent delegation, no-key fallback, mocked model success/failure, and unknown-command non-mutation.
* Use `TestClient` as a context manager when lifespan initialization is used; tests must not spend tokens or contact the network.

#### Considered Alternatives

* SQLModel/SQLAlchemy: useful as relationships, schema migrations, or multiple database backends become important; extra dependency and session management are not justified by this small schema. Regardless of ORM, keep persistence behind the required repository interface.
* `HTMLResponse`: appropriate for dynamically generated in-memory markup. `FileResponse` better matches the explicit `index.html` file and absolute code-owned path.
* Async routes: suitable when all I/O uses async clients/drivers or blocking work is offloaded. Direct synchronous SQLite/OpenAI calls inside an async handler can block the event loop. Plain `def` routes are the lower-complexity match now.

## Selected Approach Summary

Use root `main.py` plus one `index.html`; expose synchronous FastAPI CRUD and assistant endpoints. Store todos in standard-library SQLite through `tools/repository.py` only. Build an orchestrator and three small specialist agents as ordinary Python modules. Make OpenAI structured intent extraction optional; keep deterministic rule parsing as a complete, safe fallback and never let either parser bypass server-side validation. Use `FileResponse`, per-test database injection, pytest/TestClient, and a deployment launcher that maps `PORT` to the Uvicorn integer port.

This is the smallest approach that honors the requested agent boundaries and natural-language behavior while preserving deterministic CRUD and no-key operation. The main trade-offs are limited fallback grammar and SQLite's single-writer/single-instance suitability.

## Potential Next Research

* Due-date/timezone policy and daily-summary definition
  * Reasoning: “tomorrow” and “daily” need an explicit calendar boundary to avoid inconsistent output.
  * Reference: Open questions below; no product timezone was supplied.
* Deployment storage and concurrency
  * Reasoning: SQLite persistence depends on the platform retaining a local writable file, and multi-worker deployments increase locking risk.
  * Reference: [SQLite appropriate uses](https://www.sqlite.org/whentouse.html).
* OpenAI model choice and dependency pin set
  * Reasoning: Model availability is account-specific; tested versions depend on the selected Python runtime.
  * Reference: [OpenAI Python SDK](https://github.com/openai/openai-python).

## Open Decisions

* Define which timezone determines “tomorrow” and the date boundary for daily summaries.
* Define delete confirmation behavior, task-reference disambiguation, and whether the assistant can create tasks from a planner suggestion.
* Confirm Python minimum version, deployment provider, and whether the target provides a persistent disk. A multi-instance service should likely replace local SQLite with a server database.
* Choose an OpenAI model configurable through `OPENAI_MODEL`; the app must not require it to start or run fallback behavior.
* The original requested command uses `$PORT`, which is POSIX shell expansion, not portable Windows syntax. Choose either a Python launcher that reads the environment or document per-shell commands.

## Evidence Log

* `.copilot-tracking/research/subagents/2026-10-19/architecture-research.md` records broad architecture research, the workspace inspection, and API/database/test recommendations.
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` records the alternative comparison and Uvicorn CLI/port verification.
* Official docs cited in the relevant sections above; web documentation has section links because the sources are not line-numbered. No application source line citations exist because the workspace was empty.
