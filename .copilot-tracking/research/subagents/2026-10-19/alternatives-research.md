---
title: Phase 2 Alternatives Research
description: Evidence-based technology decisions for a greenfield todo application
ms.date: 2026-10-19
ms.topic: reference
---

## Research Scope

Evaluate and select one implementation approach for each requested design choice: agent architecture, intent parsing, persistence, HTTP response, route execution model, test-time database injection, and behavior when an OpenAI key is absent or unreliable. Verify the official Uvicorn CLI import target and host, port, reload, and environment-variable behavior, including Windows portability.

## Findings

### Executive recommendation

Use plain Python orchestration classes/functions, one model-assisted intent extraction call using OpenAI Structured Outputs, standard-library `sqlite3`, synchronous FastAPI routes, and `FileResponse` for a checked-in static HTML entry point. Keep task execution and all database writes deterministic. If the API key is absent or the model request fails, use a small deterministic parser for supported commands; if parsing is ambiguous, ask the user to clarify instead of guessing. This assumes a small, single-process proof of concept with conversational todo commands and a locally hosted/static UI.

### Agent framework or plain Python

**Recommendation: plain Python classes/functions; do not add an agent framework in Phase 2.** Model the domain explicitly, for example `IntentParser`, `TodoService`, and repository functions. Keep orchestration as a short testable sequence: parse request, validate intent, resolve any referenced todo against the database, apply the operation, then format a response.

| Option | Advantages | Costs and pitfalls |
| --- | --- | --- |
| Agent framework (such as OpenAI Agents SDK) | Supplies a managed run loop, tool execution, handoffs, guardrails, sessions, and tracing when needed | Adds dependencies and runtime concepts, state handling, and another abstraction boundary. It does not remove the need to enforce authorization, validate identifiers, or control writes. |
| Plain Python classes/functions | Minimal dependencies; explicit control flow; deterministic tests; natural integration with FastAPI dependencies and `sqlite3` | The application owns the request/response sequence and any future retries, memory, or tracing. |

The official Agents SDK distinguishes its higher-level runtime, which manages turns, tool execution, guardrails, handoffs, and sessions, from direct Responses API use when a workflow is short-lived and the application wants to own the loop. The todo scope has no evident handoffs, persistent conversation memory, or long-running plans, so these features do not justify framework overhead. Revisit an SDK if requirements grow to approval flows, resumable multi-step tasks, or multi-agent delegation.

### Intent extraction: function calling, structured extraction, or rules

**Recommendation: model-assisted structured intent extraction as the primary path, not function calling.** Ask the model for a constrained intent object, such as an enum `action` (`create`, `list`, `complete`, `delete`, `unknown`), a `title`, an optional natural-language todo reference, and a clarification indicator. Use OpenAI Structured Outputs through `client.responses.parse(..., text_format=IntentModel)` or strict JSON Schema with `responses.create` where supported. Validate and normalize again at the application boundary. The model proposes intent and fields only; it does not execute tools, choose SQL, or provide trusted database identity.

| Option | Advantages | Costs and pitfalls |
| --- | --- | --- |
| OpenAI function calling | Strict schemas constrain tool arguments; model can choose among tools; useful when the application genuinely exposes callable capabilities | It is a multi-step tool-call/execute/tool-output conversation when a final model answer is needed. For todo CRUD the server already knows permitted operations and should control writes, so dispatch and possible extra model round trips are unnecessary. Schema conformance is not authorization or confirmation. |
| Model-assisted structured intent extraction | Handles varied phrasing while returning bounded, typed intent; one extraction result can feed deterministic logic; strict structured output improves shape adherence | Requires network/key, incurs latency/cost, and remains semantically fallible. Supported JSON Schema is a subset; refusals, incomplete output, API errors, and schema-valid but wrong fields need handling. Resolve references against real rows and clarify ambiguity. |
| Deterministic rule parser | No API, cost, secret, or network dependency; repeatable and easy to test; reliable for deliberately narrow syntax | Natural-language coverage is limited; rules and synonyms grow brittle; unsupported phrases must be reported rather than silently interpreted. |

Function calling is intended to bridge model output to application functionality. Its documented flow includes receiving a tool call, executing application code, returning output, and possibly making a follow-up model request. Structured Outputs are for schema-shaped model responses; strict mode requires all fields to be required and objects to set `additionalProperties: false`. Use nullable fields to represent optional values under strict schema. Handle refusal and incomplete responses explicitly; schema adherence does not guarantee semantic correctness.

Recommended fallback contract:

1. If `OPENAI_API_KEY` is missing or blank, do not instantiate an OpenAI client; continue serving deterministic supported commands and disclose that natural-language interpretation is limited.
2. If extraction is enabled but times out, is rate-limited, or has a transient server/network error, run only the documented deterministic parser against that same command.
3. If fallback cannot identify one supported operation and its required fields unambiguously, ask for clarification and do not mutate data.
4. Validate after either parser: normalize title length, reject empty titles, constrain action to an allowlist, fetch todos by actual database identity, and require explicit confirmation for destructive operations if product requirements call for it.
5. Keep model calls outside any SQLite write transaction. Do not re-run the whole command after a write starts; this avoids duplicate effects on retry.

This is graceful degradation, not equivalent behavior: fallback only promises its explicitly tested grammar. The official SDK documents automatic retries for connection errors, HTTP 408/409/429 and 5xx (two retries by default), and a ten-minute default timeout. For interactive requests, configure a bounded timeout (for example 8-15 seconds) and a small retry budget or zero retries, then handle SDK `APIError` subclasses. Avoid stacking broad application retries atop SDK retries because this multiplies latency and can repeat operations.

### Persistence: standard-library SQLite or ORM

**Recommendation: Python standard-library `sqlite3` with parameterized SQL.** A small todo table and handful of queries do not warrant ORM mapping/session machinery. Use explicit schema initialization, `sqlite3.Row`, `?` placeholders for every user value, short transactions, explicit commit/rollback behavior, and deterministic connection closure.

| Option | Advantages | Costs and pitfalls |
| --- | --- | --- |
| `sqlite3` standard library | No ORM dependency; direct visibility into schema and SQL; simple for a small fixed schema; SQLite is a single-file database | Manual SQL/schema evolution and row mapping; transaction/connection lifetime are application-owned; string interpolation is an SQL injection risk; one writer at a time per database file. |
| ORM (SQLAlchemy/SQLModel) | Typed mappings, relationships, unit-of-work behavior, portable dialects, higher-level query/session patterns | Extra dependencies and concepts; session lifecycle and transaction scope need correct setup; likely more abstraction than this schema needs. ORM sessions are stateful and must not be shared among concurrent threads/tasks. |

Python `sqlite3` documentation requires parameter binding rather than interpolating values into SQL, describes transaction controls and context managers, and notes default `check_same_thread=True`. SQLite guidance identifies low-to-medium traffic sites and local application storage as good fits; it allows many readers but only one writer at a time. Move to a client/server database if write concurrency or multi-server deployment becomes a requirement.

Implementation precautions:

* Anchor the DB path to `Path(__file__).resolve()`, not the process working directory, to avoid reload/deployment writing different files.
* Bind all values with placeholders. SQL identifiers cannot be bound, so dynamic identifiers must come from code-owned allowlists.
* Make state changes atomic and commit them. Roll back on failures; do not leave transactions open during a remote model call.
* `with connection:` commits/rolls back a transaction but does **not** close the connection. Close it explicitly, for example with `contextlib.closing()` around the connection context or a `try/finally`.
* Enable foreign keys per connection (`PRAGMA foreign_keys = ON`) if the schema needs them.
* Add a schema version/migration plan before migrating persistent data; `CREATE TABLE IF NOT EXISTS` alone does not migrate columns.

### HTTP response: `FileResponse` or `HTMLResponse`

**Recommendation: `FileResponse` for a fixed static frontend entry file; use `HTMLResponse` only when the response is generated in memory.** Keep the file location as a code-owned `Path` constant, not a request parameter. `FileResponse` streams the file and supplies length, last-modified, and ETag headers. `HTMLResponse` is suitable for a short dynamically generated string and sets `text/html` content type.

Never accept an arbitrary filename/path from the client and pass it to `FileResponse`, which can become arbitrary file disclosure. For dynamic HTML, escape user-provided data. To preserve OpenAPI media-type documentation, declare `response_class=HTMLResponse`; FastAPI notes that a returned `Response` bypasses normal response conversion and automatic media-type documentation unless a response class is declared.

### Synchronous FastAPI routes with synchronous SDK and `sqlite3`

**Recommendation: use regular `def` path operations and regular `def` database dependencies for this all-synchronous stack.** FastAPI executes synchronous path operations and dependencies in an external thread pool. The synchronous OpenAI client and `sqlite3` are blocking APIs, so synchronous routes are the direct fit. Do not write `async def` routes that directly call blocking `sqlite3` or the synchronous SDK; that blocks the event loop. If an endpoint must be async, offload blocking work or use truly async clients throughout that path.

`sqlite3.connect()` defaults to `check_same_thread=True`. FastAPI may run sync dependencies and the endpoint via thread-pool execution, so do not assume the same worker thread is selected at every sync boundary. For the conventional per-request SQLite pattern, set `check_same_thread=False`, create a fresh connection per request, and never share one connection concurrently. Alternatively inject a connection factory/database path and open/close inside one synchronous operation. Disabling the thread check is not permission to share one global connection.

Use a request connection only for short DB operations. Parse before opening a write transaction, never hold a transaction during the OpenAI network call, and commit/close promptly. Sync model calls occupy a worker thread until completion; bounded timeouts and low retries are necessary. If concurrency grows beyond this model, assess async clients/persistence or server DB rather than mixing event-loop blocking calls.

### Database dependency injection and tests

**Recommendation: inject DB configuration at the FastAPI dependency boundary, with a per-request connection lifecycle.** A `get_db` dependency can yield a request-scoped connection and close it in `finally`; tests override it through `app.dependency_overrides` to supply a test database or connection factory. Alternatively inject a `Database`/repository configured with a temporary DB path. Keep the dependency callable at module scope so the override key is stable, and clear overrides after each test.

Use a temporary on-disk SQLite file for API integration tests when worker-thread behavior matters. `:memory:` belongs to one connection, so another request connection sees an empty DB. A shared-memory URI works only while a keeper connection remains open and requires URI mode; a temporary file is usually less surprising. Unit-test service/repository operations separately. Inject a fake extractor so tests require no key, network, latency, or billable call. Verify key-absent and model-error fallback paths.

### Uvicorn CLI import target, flags, and `PORT`

**Verified target and syntax:** Uvicorn CLI `APP` is `"<module>:<attribute>"`. Given `app/main.py` defining `app = FastAPI()`, run from project root with `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`. `--host` binds the socket (default `127.0.0.1`); `0.0.0.0` exposes it on interfaces. `--port` accepts an integer and defaults to 8000. `--reload` enables autoreload and is for development; `--reload` and `--workers` are mutually exclusive. For a flat root `main.py`, use `main:app`, not `app.main:app`.

Uvicorn documents CLI flags, programmatic `uvicorn.run()`, and `UVICORN_*` environment variables; CLI/programmatic values take precedence. `--env-file` configures the ASGI app, not Uvicorn's own `UVICORN_*` settings. Uvicorn does not document a special `$PORT` token. `$PORT` is shell expansion, not a Uvicorn option; a shell that does not expand it passes a non-integer literal.

Portable handling:

* For fixed local development, use `--port 8000` and avoid shell-specific expansion.
* For deployment where the platform supplies `PORT`, prefer a Python entry point that reads `int(os.environ.get("PORT", "8000"))` and calls `uvicorn.run("app.main:app", host="0.0.0.0", port=port)`. Guard it with `if __name__ == "__main__":`; Uvicorn requires this guard when programmatically using `reload=True` or `workers`.
* If keeping CLI launch, set/expand in the invoking shell: PowerShell `$env:PORT = '8000'; uvicorn app.main:app --host 0.0.0.0 --port $env:PORT`; cmd.exe `set PORT=8000` followed by `uvicorn app.main:app --host 0.0.0.0 --port %PORT%`; POSIX shell `export PORT=8000` followed by `uvicorn app.main:app --host 0.0.0.0 --port "$PORT"`. These syntaxes are shell-specific. In production, prefer platform process/environment configuration and no reload.
* Uvicorn also accepts `UVICORN_HOST`/`UVICORN_PORT`; a generic `PORT` is not automatically equivalent. Map it in the launcher or Python entry point.

### Implementation-grade scenario

1. FastAPI serves a known static `index.html` using `FileResponse`; JSON API routes are synchronous `def` operations.
2. A natural-language todo command arrives. If a usable key/client is configured, one structured-output call maps it to a small Pydantic intent schema. The model is an extractor, not a privileged DB tool.
3. If the key is missing or extraction fails, a deterministic parser recognizes a documented narrow grammar. Unknown or ambiguous intent returns clarification without a write.
4. Validate title/action, resolve references against actual rows with parameterized `sqlite3` queries, then call deterministic todo service functions. Use a fresh request-scoped connection, short explicit transactions, rollback on errors, and close in all paths.
5. Tests inject a temporary DB factory/path and fake extractor; include missing-key, timeout/error, unknown intent, duplicate, nonexistent reference, and rollback cases.
6. Use fixed-port CLI for local development; use a Python environment-reading entry point for deployment `PORT` so startup is not tied to PowerShell, cmd.exe, or POSIX shell syntax.

## References

### Official FastAPI and Starlette documentation

* [Concurrency and async/await](https://fastapi.tiangolo.com/async/): sync path operations/dependencies run in a thread pool; blocking-library guidance.
* [Custom Response: HTML, File, and others](https://fastapi.tiangolo.com/advanced/custom-response/): `HTMLResponse`, `FileResponse`, file headers, direct-response documentation caveat.
* [Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/): dependency injection and database connections.
* [Testing dependencies with overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/): `app.dependency_overrides` mapping and reset.
* [Testing](https://fastapi.tiangolo.com/tutorial/testing/): `TestClient` API test pattern.
* [SQL databases](https://fastapi.tiangolo.com/tutorial/sql-databases/): SQLite/SQLModel reference pattern, `check_same_thread=False`, per-request session, migration note.

### Python and SQLite

* [Python `sqlite3`](https://docs.python.org/3/library/sqlite3.html): connection defaults, transactions/context manager, row factories, `:memory:`, parameter binding, thread checks.
* [SQLite appropriate uses](https://www.sqlite.org/whentouse.html): workload fit, write serialization, when client/server DB is appropriate.

### OpenAI

* [Function calling](https://developers.openai.com/api/docs/guides/function-calling): tool-call loop, schema/strict mode requirements, tool choice.
* [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs): strict schema, Pydantic parsing, supported subset, refusal/incomplete handling, semantic edge cases.
* [OpenAI Python SDK](https://github.com/openai/openai-python): `OpenAI`/`AsyncOpenAI`, environment key, sync/async clients, exceptions, default retries and timeouts.
* [Agents SDK overview](https://openai.github.io/openai-agents-python/): framework primitives and direct Responses API choice.
* [Agents SDK agent concepts](https://openai.github.io/openai-agents-python/agents/): `Agent`, context, output types, tools, runtime loop, orchestration.
* [OpenAI agent runtime comparison](https://developers.openai.com/api/docs/guides/agents): managed Agents API, in-process Agents SDK, and direct Responses API distinctions.

### Uvicorn and shell environment behavior

* [Uvicorn settings](https://www.uvicorn.org/settings/): CLI import target, `--host`, `--port`, `--reload`, configuration/precedence, reload-worker incompatibility. Official repository copy: [Uvicorn settings on GitHub](https://github.com/Kludex/uvicorn/blob/main/docs/settings.md).
* [Python `os.environ`](https://docs.python.org/3/library/os.html#os.environ): process environment mapping.
* [PowerShell environment variables](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_environment_variables): `$Env:NAME` and process-scope inheritance.
* [Windows cmd `set`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/set_1): cmd environment assignment and `%NAME%` expansion.
* [Bash parameter expansion](https://www.gnu.org/software/bash/manual/html_node/Shell-Parameter-Expansion.html): shell `$NAME`/`${NAME}` expansion.

### ORM comparison

* [SQLAlchemy ORM quickstart](https://docs.sqlalchemy.org/en/20/orm/quickstart.html): mappings, engine, session, unit-of-work, and query features.
* [SQLAlchemy session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html): session transaction/resource lifecycle and one session per thread/task.

## Unresolved Gaps

* The Phase 1 requirements were not present in the empty workspace/context. The recommendation assumes conversational natural-language commands; confirm whether the app requires natural language, which CRUD operations exist, and whether delete needs confirmation. If requests are standard form submissions only, deterministic route/body validation should replace model extraction entirely.
* Exact columns, uniqueness semantics, multi-user ownership/authentication, and deployment host are unspecified. These determine constraints, authorization, and whether local SQLite is persistent/deployable on the target platform.
* The Uvicorn docs website did not yield extracted content. The official Uvicorn repository's `docs/settings.md` page was readable and corroborates the CLI contract; conclusions are not based solely on an unofficial source.

## Research Status

Complete for the stated alternatives. Follow-on implementation decisions require the unresolved product and deployment details above.
