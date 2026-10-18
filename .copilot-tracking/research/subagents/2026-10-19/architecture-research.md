---
title: Greenfield FastAPI Todo App Architecture Research
description: Research findings and implementation recommendations for a SQLite-backed, agentic FastAPI todo application.
ms.date: 2026-10-19
ms.topic: architecture
---

## Research Scope

Assess a practical architecture for a greenfield todo app with a FastAPI `main.py` app object, one root-served `index.html`, SQLite persistence, agent delegation, a unified repository/tool boundary, optional OpenAI integration with a reliable rule-based fallback, REST CRUD, assistant UI, tests, dependencies, ignore rules, and a Uvicorn launch command. Research only; no implementation files are to be changed.

## Research Questions

* What do current authoritative FastAPI and Python SQLite documentation recommend for app setup, serving one HTML page, database access, and lifecycle?
* What current OpenAI Python SDK patterns support optional model use and predictable no-key behavior?
* What pytest practices suit API and repository tests for SQLite?
* What minimal architecture, routes, interfaces, dependencies, test strategy, and run command best fit this app?
* What are the main design risks, alternatives, and unresolved research gaps?

## Workspace Inspection

* The workspace had no application source files, manifests, existing gitignore, or project-local instruction files when inspected. The only initial entry was the tracking directory created for this research.
* No existing architecture or implementation conventions therefore constrain recommendations. The applicable HVE Core markdown and writing-style instructions were consulted; this report uses YAML frontmatter, concise headings, professional tone, and plain lists.
* No code changes were made. The only workspace write is this requested research report and its parent directory.

## Findings

### Recommended minimal structure

```text
main.py
index.html
agents/__init__.py
agents/orchestrator.py
agents/task_agent.py
agents/planner_agent.py
agents/summary_agent.py
tools/__init__.py
tools/repository.py
tests/test_api.py
tests/test_repository.py
requirements.txt
.gitignore
```

Keep the API/app object in the required root `main.py` as `app = FastAPI(...)`. Use small Pydantic request and response models there or in a small `schemas.py` only if the implementation grows. The single root `index.html` should contain its CSS and browser JavaScript inline, call same-origin JSON endpoints with `fetch`, and be served at `/`; no static mount or second frontend page is needed. `FileResponse` with a `Path(__file__).resolve().parent / "index.html"` is the most direct file-serving approach and avoids a working-directory-sensitive relative path. FastAPI also supports returning an `HTMLResponse` and documents `response_class=HTMLResponse`; use that only if reading the HTML into Python rather than serving the actual file is desired.

Keep application layers one-directional:

```text
index.html -> FastAPI routes in main.py
CRUD routes -> tools/repository.py -> TaskRepository -> SQLite
Assistant route -> Orchestrator -> selected agent -> repository tools
```

The user's repository boundary is best made strict: `tools/repository.py` owns all SQL, connection creation, schema setup, transactions, and row conversion. It exports a `TaskRepository` plus a small typed tool facade (for example, list/create/update/delete task functions bound to that repository). REST handlers and every agent call those tools; no other module imports `sqlite3`, executes SQL, or accesses a database file. Agents receive only the tool interface, never a raw connection or unrestricted SQL.

### Persistence and schema

Use the standard-library `sqlite3` module; no separate database service or SQLite package is needed. A minimal `tasks` table should include integer primary-key `id`, required trimmed `title`, optional `description`, boolean-like `completed` constrained to 0/1, and UTC `created_at`/`updated_at` ISO-8601 text values. Define `NOT NULL`, length/validation at the API boundary, and SQL `CHECK` constraints where they protect stored invariants. If planning needs ordering, use an optional `due_date` or `priority`, not a separate planning table until a real feature requires it. Initialize an idempotent schema (`CREATE TABLE IF NOT EXISTS`) once at app startup via FastAPI lifespan or when repository initialization is explicit.

Open and close a connection per repository operation (or per request unit of work), set `row_factory = sqlite3.Row`, and use the connection context manager for commit/rollback while explicitly closing the connection. This respects sqlite3's default `check_same_thread=True` and avoids a single cross-request connection. The standard `sqlite3` is synchronous; use ordinary `def` FastAPI route handlers so FastAPI dispatches blocking DB and synchronous SDK work through its threadpool, or make the complete persistence/model stack async only if there is a demonstrated need. Keep transactions short. Bind user-supplied values with `?`/named placeholders, never SQL string interpolation. For task updates, allowlist mutable fields and build SQL only from those fixed column names; bind all values. Treat missing task IDs as not found and check `rowcount` when updating/deleting.

Use a stable database path anchored at the application directory rather than the current working directory; optionally support a `TODO_DB_PATH` override for tests/deployment. The override is especially useful for `tmp_path` integration tests. Do not use `:memory:` across independent per-operation connections unless a single shared-memory URI and connection lifetime are deliberately managed; file-based temp databases avoid that trap. SQLite can serialize writes but is not a high-write-concurrency/server database, which is acceptable for a local proof of concept.

### Agentic behavior with useful no-key operation

Implement the named agents as ordinary Python classes/functions, not a multi-agent framework. Have `Orchestrator` classify the request to a narrow intent and delegate to one specialist:

* `TaskAgent`: create, list, complete, update, or delete tasks through repository tools.
* `PlannerAgent`: turn a planning request into a proposed ordered set of concrete tasks, and create tasks only when the user explicitly requests creation. It can use deterministic priority/date rules in fallback mode.
* `SummaryAgent`: read repository results and return deterministic counts, remaining tasks, or a concise summary.
* `Orchestrator`: dispatch based on explicit intent, enforce an allowlisted tool set, call the selected agent, and compose a stable response including which agent handled the request and whether AI or rule-based mode was used.

The agent classes should have the same input/output contract in both modes. The optional OpenAI-backed path can use the official `openai` Python SDK's `OpenAI` client and Responses API; keep model invocation in one adapter/helper and expose only validated repository functions to the model if implementing model tool calling. Do not let the model supply SQL, arbitrary tool names, or unchecked task IDs/fields. An even simpler first iteration can use OpenAI for intent extraction or wording while the application itself decides and executes the validated repository operation. This reduces tool-loop failure modes and keeps database behavior deterministic.

Critically, no key must not mean failed startup, import failure, or disabled assistant. Do not instantiate a default `OpenAI()` client unconditionally: the SDK reads `OPENAI_API_KEY` and construction may fail without credentials. Read the environment value first; if missing or blank, select a local `RuleBasedAssistant`/fallback path without importing the SDK on request (or lazily import it when configured). If a key is present, attempt the configured model call with a bounded timeout and limited retries; on connection, timeout, rate-limit, authentication/configuration, or response-validation failure, log a sanitized warning and run the same deterministic fallback rather than returning a 500. Avoid repeated retries in the application on top of SDK defaults; configure a short request timeout and lower SDK `max_retries` if the desired user-facing fallback latency is strict. Return a mode field such as `"ai"` or `"fallback"` so the UI can make the behavior transparent. Never return secrets, raw SDK exception payloads, or prompts containing unnecessary task data to the browser/logs.

The fallback must be a complete behavior implementation, not a generic “AI unavailable” message. Use a small explicit command grammar (e.g. add/create, list/show, complete/done, delete/remove, plan, summarize/count) with conservative parsing and clear clarification responses for ambiguous requests. It should perform real task CRUD through the same repository tools, produce reproducible planning (for example, prioritize overdue/urgent then stable creation order), and summarize repository state. Unknown requests should explain supported commands without mutating data. Test these paths with the key absent, and test that a mocked OpenAI failure falls back without network access.

### REST API and assistant UI

Recommended compact endpoints:

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/` | Serve the single `index.html` |
| `GET` | `/api/tasks` | List tasks; optional `completed` filter |
| `POST` | `/api/tasks` | Create task; return `201 Created` |
| `GET` | `/api/tasks/{task_id}` | Read one; return `404` if missing |
| `PATCH` | `/api/tasks/{task_id}` | Partial update of allowlisted fields; return `404` if missing |
| `DELETE` | `/api/tasks/{task_id}` | Delete; return `204 No Content`, or `404` if missing |
| `POST` | `/api/assistant` | Accept a message and return response, agent, mode, and any changed task/list payload |

Pydantic models validate request bodies and response shape. Require non-empty titles after trimming; reject empty patch bodies and reject fields outside the update contract rather than silently ignoring them. Use explicit status codes and a consistent JSON error shape. Keep the assistant route separate from CRUD so the UI can refresh the task list after a tool operation. A one-page UI can offer an add form, task list with complete/edit/delete actions, and chat panel. Render user/model-provided strings with DOM `textContent`/safe element construction, not `innerHTML`; use accessible labels, pending/error indicators, and a visible fallback/AI status. No CORS configuration is needed when the page and API share the same origin.

### Dependencies and commands

`sqlite3`, `pathlib`, and `os` come from Python's standard library. A small `requirements.txt` should include direct runtime dependencies `fastapi`, `uvicorn[standard]`, and `openai`; testing dependencies can be included as `pytest` and `httpx` or split into a documented dev requirements file. FastAPI's `TestClient` requires HTTPX. Pin versions after choosing a supported Python runtime and verifying installation together; do not copy the current latest version numbers blindly into a long-lived project. Python 3.10+ is supported by the current OpenAI SDK. A `.gitignore` should exclude `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.env`, SQLite database and journal files (`*.db`, `*.sqlite`, `*.sqlite3`, `-wal`, `-shm`), and generated coverage artifacts as applicable. Keep `.env.example` limited to variable names and safe placeholders if added; never commit a real API key.

From the workspace root, use the Uvicorn ASGI import target `uvicorn main:app --reload` for local development. The standard default binds to `127.0.0.1:8000`; explicitly supply `--host 0.0.0.0` only when exposure to other interfaces is intended. For production, do not use reload; use the deployment platform's process configuration and consider multiple workers only after evaluating SQLite write concurrency and deployment storage semantics.

### Test plan

Use `pytest` and FastAPI `TestClient` for synchronous route tests, with tests in `tests/` and `test_*.py` names. Design `create_app(...)` or an overridable dependency so tests can inject a repository pointed at a per-test `tmp_path` database and a fake assistant. Keep the required module-level `app` for Uvicorn. Enter `TestClient(app)` as a context manager if lifespan startup initializes the database. Cover:

* Repository create/read/list/filter/update/delete, persistence, validation constraints, missing IDs, rollback, and parameterized handling of hostile input text.
* API home page content type and root response, CRUD status codes and payload validation, not-found behavior, and assistant response contract.
* Agent routing to task/planner/summary behavior and validation that all mutations/read requests go through injected tools.
* Key missing/blank fallback, deterministic task operations and explanations, malformed/ambiguous assistant text, configured model success with a mock, and model errors/timeouts falling back. Tests must not require an API key, spend API credits, or use network access.
* If model-generated structured data is accepted, invalid/unknown tool calls and malformed arguments must not mutate the database.

For tests, `tmp_path` is function-scoped and isolates each database file; pytest fixtures with `yield` can close/clean up resources. `monkeypatch.setenv`/`delenv` can test key-present and missing environments and restores the prior environment automatically. Prefer dependency injection and a mocked client over globally patching broad library internals.

## References

Official documentation consulted on 2026-10-19. Web docs are cited by section URL/anchor because their rendered HTML is not line-numbered. No local source files existed to cite with source line anchors.

### FastAPI

* [First Steps](https://fastapi.tiangolo.com/tutorial/first-steps/), create `FastAPI()` and a module-level `app`, HTTP path operations, normal versus async endpoint functions, Uvicorn-backed local server, and OpenAPI/docs.
* [Custom Response: HTML and FileResponse](https://fastapi.tiangolo.com/advanced/custom-response/#html-response), `HTMLResponse` and media type/OpenAPI behavior; [FileResponse](https://fastapi.tiangolo.com/advanced/custom-response/#fileresponse) streams the named file and supplies content metadata.
* [Lifespan Events](https://fastapi.tiangolo.com/advanced/events/#lifespan), recommended async context manager for startup/shutdown; old event handlers are deprecated.
* [Request Body](https://fastapi.tiangolo.com/tutorial/body/#results), Pydantic body parsing, validation, editor types, and generated JSON schema.
* [Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/#about-http-status-codes), use `201` for creation and body-less `204` for no-content response.
* [Testing](https://fastapi.tiangolo.com/tutorial/testing/#using-testclient), TestClient usage, HTTPX dependency, and ordinary synchronous pytest tests.
* [Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/) and [Testing Dependencies with Overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/), useful patterns for injecting a temporary repository/fake assistant.

### Python SQLite

* [Python `sqlite3` tutorial](https://docs.python.org/3/library/sqlite3.html#tutorial), connection creation, transactions, commit, and parameter placeholders.
* [Placeholders to bind values](https://docs.python.org/3/library/sqlite3.html#how-to-use-placeholders-to-bind-values-in-sql-queries), bind runtime values rather than interpolate to prevent SQL injection.
* [Connection objects](https://docs.python.org/3/library/sqlite3.html#connection-objects), `connect`, default `check_same_thread=True`, execute, commit, rollback, close, and connection attributes.
* [Connection context manager](https://docs.python.org/3/library/sqlite3.html#how-to-use-the-connection-context-manager), commits on success/rolls back on error but does not close the connection.
* [Row factories](https://docs.python.org/3/library/sqlite3.html#how-to-create-and-use-row-factories), recommended `sqlite3.Row` with named access.
* [Transaction control](https://docs.python.org/3/library/sqlite3.html#transaction-control), current docs recommend explicit `autocommit` control, with Python 3.12+ semantics. If supporting older Python, prefer code compatible with the chosen minimum runtime and explicitly commit/rollback.

### OpenAI SDK and API

* [OpenAI Python SDK README](https://github.com/openai/openai-python#usage), supported Python 3.10+, SDK installation, environment API key usage, Responses API example, timeout/retry controls, and exception classes.
* [OpenAI developer quickstart](https://developers.openai.com/api/docs/quickstart#create-and-export-an-api-key), Windows `OPENAI_API_KEY` setup and SDK auto-read; Python SDK install and Responses API call.
* [Text generation](https://developers.openai.com/api/docs/guides/text#choosing-models-and-apis), Responses API recommendation, and prompt tests/evaluations/model snapshot stability.
* [Function calling](https://developers.openai.com/api/docs/guides/function-calling#how-it-works), model tool-call flow, application-side execution, strict schemas, and allowlisted local function dispatch. The model requests a function; application code performs it and passes a result back.

### pytest and Uvicorn

* [pytest getting started](https://docs.pytest.org/en/stable/getting-started.html#run-multiple-tests), standard `test_*.py` discovery and `pytest` invocation.
* [pytest `tmp_path`](https://docs.pytest.org/en/stable/how-to/tmp_path.html#the-tmp-path-fixture), unique temporary directory per test.
* [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html#teardown-cleanup-aka-fixture-finalization), fixture scopes and yield-based cleanup.
* [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html#monkeypatching-environment-variables), safely set/delete environment variables and automatic restoration.
* [Uvicorn settings](https://www.uvicorn.org/settings/), authoritative CLI options; the fetcher could not extract this page in this session. The command syntax `uvicorn main:app --reload` follows Uvicorn's documented `<module>:<attribute>` application import-string form. Verify actual install/launch as part of implementation.

## Design Risks and Alternatives

* **Fallback completeness is the key product risk.** Keyword matching alone can misread natural requests or execute an unexpected mutation. Restrict supported phrases/intents, ask for clarification when ambiguous, and test that unrecognized text never mutates tasks. Keep direct CRUD fully usable even if assistant parsing is limited.
* **“Agentic” can become ceremony.** Three named agent files add structural clarity, but a framework or LLM-to-LLM handoffs would add latency, opaque behavior, more external dependency, and costs without a clear benefit for this proof of concept. Plain deterministic agents behind the same interfaces are the recommended starting point. Introduce a framework only if tracing, complex handoffs, or more tools become requirements.
* **LLM tool calls can produce unsafe/incorrect operations.** All tool arguments need schema and application validation, tool names must be allowlisted, and model output should not be trusted as authorization. A deterministic orchestrator can choose agent first; let the model only help parse or phrase. If giving the model repository tools, require explicit user intent before destructive operations and validate every operation server-side.
* **Fallback after a slow request is not reliable unless latency is bounded.** SDK defaults include retries and a long default timeout in the current README. Configure a modest timeout/retry budget and convert exceptions to local fallback; test the adapter with mocked failures. A key's presence does not guarantee validity, funding, model access, or network availability.
* **SQLite path and connection lifecycle can cause flaky data/tests.** Relative paths depend on process CWD; `:memory:` disappears across separate connections; a shared connection conflicts with default thread checking and concurrent calls. Anchor the default path and inject a temporary file path in tests; keep transaction scope short.
* **SQLite deployment boundaries.** SQLite suits a single-process/local POC. Multiple workers, network filesystems, container ephemeral filesystems, or concurrent writers can cause lock/content persistence problems. For deployment beyond a small single-instance app, document volume backup/persistence and consider PostgreSQL with an ORM/repository adapter.
* **Sync I/O in async routes.** Calling synchronous SQLite/OpenAI calls directly inside `async def` can block the event loop. Use sync FastAPI path functions for this POC or use async clients and offload SQLite explicitly; do not mix casually.
* **Single-file UI security.** Even without auth, task content and assistant output are untrusted. Avoid `innerHTML`, keep API and UI same-origin, cap message/title lengths, and do not expose `OPENAI_API_KEY` to browser code.
* **HTTP contract edge cases.** Decide whether blank title is rejected, whether PATCH null clears optional values, whether repeated creates are allowed, task ordering, delete of unknown ID, and what the assistant response returns when it has mutated state. Encode these decisions in models and tests.
* **Dependency/version drift.** Current docs change quickly and SDK model availability/identifier can differ by account. Select and test a model available to the user's account, configure it (e.g. `OPENAI_MODEL`) without requiring it for fallback, and pin dependency versions after implementation verification.

Alternatives considered:

* **Inline HTMLResponse vs `FileResponse`:** both support root serving. `FileResponse` is clearer for the explicit single file and safer across CWD changes when using an absolute path. `HTMLResponse` suits tiny embedded HTML or tests but duplicates/loads file content into application code.
* **Direct `sqlite3` vs SQLModel/SQLAlchemy:** standard library minimizes install and makes the one-table POC straightforward, though repository code owns mapping and migrations. SQLModel/SQLAlchemy becomes attractive for several entities, richer relationships, migrations, or database portability; using an ORM must not bypass the repository/tools boundary.
* **OpenAI Responses function calling vs local intent extraction:** model function calling is more agentic and can interpret diverse phrasing but adds one or more network round trips, schema dispatch, costs, and failure surface. Local intent rules plus optional model text assistance is safer and cheapest. If tool calling is used, keep tool implementation in repository facade and enforce strict input schemas.
* **`OPENAI_API_KEY` required vs optional:** requiring it makes development inaccessible and violates requested no-key behavior. Optional key + full rule fallback is the recommended design; missing key selects fallback at startup/request time, while a configured-but-broken AI service falls back per call.
* **Uvicorn CLI vs FastAPI CLI:** `uvicorn main:app --reload` is familiar and meets the user's explicit request; current FastAPI also offers `fastapi dev main.py`. Do not list both as the canonical command.

## Open Research Gaps

* Project-specific Python version, expected deployment topology, and whether the app is only a local demo are unspecified; select these before freezing dependency versions or deciding database concurrency settings.
* Desired assistant command language, destructive-action confirmation, due-date/timezone rules, multi-step plan confirmation, and whether planning should create tasks or only propose them require product decisions. Recommendation: plan-only by default and only persist with an explicit create instruction.
* The current Uvicorn site could not be parsed by the page-fetch service. The import-string CLI pattern is well-established, but confirm exact flags against current Uvicorn settings docs when implementation begins.
* The precise OpenAI model ID and account access cannot be inferred from public docs or workspace inspection; make it configurable and test without live credentials.
* No browser test framework was researched. Initial UI validation can use manual checks plus API tests; add browser automation only if end-to-end interaction regression is required.
