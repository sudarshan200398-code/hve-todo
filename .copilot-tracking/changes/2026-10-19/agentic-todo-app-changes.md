<!-- markdownlint-disable-file -->
# Release Changes: Agentic Todo App

**Related Plan**: agentic-todo-app-plan.instructions.md
**Implementation Date**: 2026-10-19

## Summary

Implemented the approved greenfield plan: SQLite persistence, specialist agents, a FastAPI REST API, a single-page UI, optional OpenAI intent extraction with rule-based fallback, and offline tests.

## Changes

### Added

* `tools/__init__.py` - Repository package marker
* `tools/repository.py` - SQLite task schema, repository, validation, transaction lifecycle, and typed `TaskTools` facade
* `tests/test_repository.py` - Isolated repository CRUD, validation, parameterization, persistence, and rollback tests
* `requirements.txt` - Pinned FastAPI, Uvicorn, OpenAI, pytest, and HTTPX dependencies
* `.gitignore` - Python environment/cache, secrets, and SQLite database/sidecar ignore patterns
* `agents/__init__.py` - Agent package exports
* `agents/orchestrator.py` - Intent extraction, fallback parsing, validation, and specialist dispatch
* `agents/task_agent.py` - Task CRUD use cases via repository tools
* `agents/planner_agent.py` - Deterministic advisory next-task selection
* `agents/summary_agent.py` - UTC daily summary calculations
* `tests/test_agents.py` - Agent routing, fallback, planner, summary, and mocked model tests
* `main.py` - Injectable FastAPI application, root file route, REST CRUD, and assistant endpoints
* `tests/test_api.py` - Root, CRUD, validation, assistant contract, and hostile-text API tests
* `index.html` - Responsive single-page task dashboard and natural-language assistant UI

### Modified

* None

### Removed

* None

## Additional or Deviating Changes

* Phase 1 completed: repository tests passed (9 passed); forced rollback, CRUD, persistence, input binding, and ignore entries were verified. Direct `pytest` collection initially failed because that invocation did not place the workspace root on the import path; `python -m pytest` worked.
* Phase 2 completed: repository and agent tests passed (23 passed); configured and failed model calls were mocked and no live API was called.
* Phase 3 completed: API/repository tests passed (15 passed), then all three test files passed (29 passed). Root serving returned 200 with `text/html`; browser checks exercised task creation, natural-language fallback, Suggest next, Daily summary, and hostile markup-like task/assistant text. Hostile text remained literal and no injected image elements appeared.
* Phase 4 completed: installed the pinned `requirements.txt` into `.venv`; `python -m pytest -q` passed (29 passed, one third-party AnyIO deprecation warning). Local Uvicorn started on port 8003 with `OPENAI_API_KEY` blank. Isolated HTTP smoke checks passed for root, task creation, planner suggestion, daily summary, and assistant fallback.
* The generated local `tasks.sqlite3`, Python caches, and `.venv` are excluded by `.gitignore` patterns.
* The workspace is not a Git repository, so Git status and tracked-file verification were unavailable.

## Release Summary

All four implementation phases completed. Fourteen files were added, zero modified, and zero removed. Runtime and test dependencies are pinned; no external database infrastructure was added. Render's exact Linux Start Command is `uvicorn main:app --host 0.0.0.0 --port $PORT`; local port 8003 was smoke-tested. Configure a Render persistent disk and `TODO_DB_PATH` before relying on task retention across redeploys; otherwise SQLite data may be ephemeral.
