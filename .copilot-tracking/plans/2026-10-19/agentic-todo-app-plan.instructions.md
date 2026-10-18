---
applyTo: '.copilot-tracking/changes/2026-10-19/agentic-todo-app-changes.md'
---
<!-- markdownlint-disable-file -->
# Implementation Plan: Agentic Todo App

## Overview

Build a single-page todo app with a root FastAPI entry point, SQLite storage behind one repository, three specialist agents coordinated by an orchestrator, optional OpenAI intent extraction with deterministic fallback, REST CRUD, and pytest coverage.

## Objectives

### User Requirements

* Expose `app` from root `main.py`, serve one root `index.html`, and provide SQLite-backed plain REST CRUD — Source: `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (User request summary, Lines 13-19)
* Keep all agent persistence access in `tools/repository.py` via `TaskRepository`; delegate task operations, planning, and daily summary through agents in `agents/` — Source: User request on 2026-10-19
* Accept natural-language requests with optional `OPENAI_API_KEY` and a usable rule-based fallback; provide task list, assistant, Suggest next, and Daily summary UI — Source: User request on 2026-10-19
* Add pytest tests, `requirements.txt`, and `.gitignore` with the requested patterns — Source: User request on 2026-10-19
* Use Render Linux Start Command `uvicorn main:app --host 0.0.0.0 --port $PORT`; use local port 8003 — Source: User clarification on 2026-10-19

### Derived Objectives

* Keep all SQL, connections, schema, transactions, and row mapping inside the repository module; enforce parameter binding and test with temporary on-disk databases — Derived from: user-mandated persistence boundary and SQLite research
* Use plain Python agent modules, structured intent extraction when configured, validation before dispatch, bounded model timeout/retries, and fallback for missing/failed model calls — Derived from: alternative analysis at `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 14-50)
* Resolve unspecified date, summary, deletion, duplicate-title, and planner-write behavior with low-complexity defaults rather than blocking on product questions — Derived from: user's request to choose the simplest default for open follow-ups
* Keep user/model text safe in the browser and expose AI/fallback mode in assistant responses — Derived from: single-page UI and untrusted-content research

## Context Summary

### Project Files

* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` - Consolidated architecture, requirement interpretation, risks, and external references
* `.copilot-tracking/research/subagents/2026-10-19/architecture-research.md` - API, repository, fallback, dependencies, and test recommendations
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` - Evidence-based design choices and verified Uvicorn command semantics
* `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` - File-level implementation steps, decisions, and validation commands

### References

* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 71-116) - Recommended layout, one-way repository boundary, API, and UI
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 117-171) - Agent behavior, optional LLM, fallback, and tests
* `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 14-112) - Selected architecture, DB/testing patterns, and Uvicorn port behavior

### Standards References

* `.github/copilot-instructions.md` - Not present in workspace; no repository-specific instruction file was found
* `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` - Research and verified official documentation links

## Implementation Checklist

### [x] Implementation Phase 1: Persistence and Contracts

<!-- parallelizable: false -->

* [x] Step 1.1: Implement `TaskRepository`, SQLite schema, transaction lifecycle, and repository tests
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 21-46)
* [x] Step 1.2: Add runtime/test dependencies and required ignore rules
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 47-68)
* [x] Step 1.3: Validate repository and metadata changes
  * `python -m pytest tests/test_repository.py` passed (9 tests); direct `pytest` collection failed because this environment did not put the workspace root on the import path
  * Verified requested ignore entries and `tools/repository.py` as sole sqlite3 import

### [x] Implementation Phase 2: Agent Services

<!-- parallelizable: false -->

* [x] Step 2.1: Implement orchestrator, Task Agent, Planner Agent, Summary Agent, and safe optional model/fallback handling
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 73-106)
* [x] Step 2.2: Test deterministic routes, parser behavior, planner ordering, summaries, and mocked model paths
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 107-114)
  * `python -m pytest tests/test_repository.py tests/test_agents.py` passed (23 tests)

### [x] Implementation Phase 3: HTTP API and Single-Page UI

<!-- parallelizable: true -->

* [x] Step 3.1: Add root FastAPI app, static root response, REST CRUD, assistant actions, and API tests
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 121-154)
* [x] Step 3.2: Build `index.html` task list, assistant box, Suggest next and Daily summary controls
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 155-174)
* [x] Step 3.3: Validate API and UI against the agreed endpoint contract
  * `python -m pytest tests/test_api.py tests/test_agents.py tests/test_repository.py` passed (29 tests)
  * Root route returned 200 `text/html`; inline JavaScript syntax passed; no `innerHTML` use was found
  * Browser smoke test confirmed add-task, natural-language assistant, Suggest next, Daily summary, fallback indicator, and literal hostile-text rendering with no injected image elements
  * API and UI touch separate files and can proceed in parallel against the exact paths, methods, payloads, and response fields defined in Step 3.1 of the details file

### [x] Implementation Phase 4: Launch and Final Validation

<!-- parallelizable: false -->

* [x] Step 4.1: Configure the exact Render command and local port-8003 command; verify SQLite storage location
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 179-194)
  * Render command retained exactly: `uvicorn main:app --host 0.0.0.0 --port $PORT`; local Uvicorn served app at port 8003 with `OPENAI_API_KEY` blank
  * Render persistent disk is an external deployment follow-on, not configured in this workspace
* [x] Step 4.2: Install dependencies, run all tests, and smoke-test the app locally
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 197-205)
  * Installed pinned `requirements.txt` in `.venv`; `python -m pytest -q` passed (29 tests, one third-party deprecation warning)
  * HTTP smoke checks passed for root, CRUD create, planner suggestion, daily summary, and no-key assistant fallback
  * Browser smoke checks confirmed hostile task/assistant text renders literally, no injected `<img>` nodes, add-task, assistant, suggest-next, and daily summary work
* [x] Step 4.3: Fix minor issues and document blockers that need additional research
  * Details: `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Lines 207-209)
  * After each fix, rerun the failing check, full pytest suite, and affected smoke checks

## Planning Log

See `.copilot-tracking/plans/logs/2026-10-19/agentic-todo-app-log.md` for research gaps, selected/alternate approaches, and follow-on work.

## Dependencies

* Python 3.10+ and compatible FastAPI, `uvicorn[standard]`, OpenAI SDK, pytest, and HTTPX versions
* No OpenAI credential required to run tests, start the service, perform CRUD, or use the deterministic fallback
* Render Linux service provides `PORT`; persistent disk configuration is needed for retained SQLite data across redeploys/restarts

## Success Criteria

* `main.py` exports an importable FastAPI `app`; `/` serves the single `index.html` — Traces to: user request
* All task database reads/writes go through `TaskRepository` in `tools/repository.py` with parameterized SQL — Traces to: user request and SQLite research
* Named agents route assistant actions; absent or failing model calls use deterministic fallback without unsafe or ambiguous mutation — Traces to: user request and fallback research
* CRUD, assistant actions, Suggest next, and Daily summary work through the API/UI and have automated test coverage — Traces to: user request
* Render command remains exactly `uvicorn main:app --host 0.0.0.0 --port $PORT`; local run uses port 8003 — Traces to: user clarification
* Full pytest suite and local HTTP smoke checks pass without credentials or live model calls — Traces to: research test strategy
