<!-- markdownlint-disable-file -->
---
title: Agentic Todo App Planning Log
description: Research discrepancies, implementation choices, and follow-on work for the todo app plan.
ms.date: 2026-10-19
ms.topic: reference
---

# Planning Log: Agentic Todo App

## Discrepancy Log

Gaps and differences between research findings, the user's clarifications, and the implementation plan.

### Unaddressed Research Items

None.

### Resolved Research Items

* DR-04 (Resolved, Major): The initial omission of an explicit hostile-text test requirement has been resolved.
  * Source: `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Line 257) requires hostile-text test coverage.
  * Reason: The original details specified safe rendering but did not require testing hostile task and assistant content.
  * Impact: Before resolution, unsafe rendering or input handling could regress without detection.
  * Resolution: The API criteria require hostile task titles and assistant responses to remain literal text at `.copilot-tracking/details/2026-10-19/agentic-todo-app-details.md` (Line 147), and the UI criteria require a UI/API test or browser smoke test using hostile markup-like content at Line 168.

### Plan Deviations from Research

* DD-01 (Minor): Render launch command is fixed to the user's exact Linux deployment command rather than a cross-shell Python launcher.
  * Research recommends a launcher when one command must be portable across PowerShell, cmd.exe, and POSIX shells.
  * Plan implements `uvicorn main:app --host 0.0.0.0 --port $PORT` on Render and `uvicorn main:app --host 0.0.0.0 --port 8003` locally.
  * Rationale: The user specified Render Linux and explicitly requested the command. `$PORT` expansion is appropriate for Render's Linux shell; local Windows uses the separate fixed port command.
  * Impact: None for the specified deployment; the command is intentionally not portable across shell environments.
* DD-02 (Minor): The plan selects simple defaults for research questions instead of deferring product decisions.
  * Research recommends that timezone/day boundaries, delete confirmation, and planner mutation policy be decided.
  * Plan uses UTC date interpretation and daily boundaries, immediate deletion only after explicit unambiguous assistant intent, browser confirmation for the delete button, no duplicate-title restriction, and non-mutating planner suggestions.
  * Rationale: User requested the simplest default without follow-up questions; these defaults are explicit and testable.
  * Impact: A future multi-user/timezone requirement may need a user preference and schema/API changes.
* DD-03 (Minor): Render persistence is conditional in the implementation details, not a committed persistent-disk configuration.
  * Research warns that local SQLite data can be lost on ephemeral container filesystems and recommends persistent storage where retention matters.
  * Plan implements a `TODO_DB_PATH` override and says to configure a persistent disk if tasks must survive redeploys/restarts; an ephemeral demo is also allowed. The planning log previously described persistent-disk use as the selected approach.
  * Rationale: The conditional plan matches the research, but the log must not imply that Render disk provisioning is already included in source changes or the implementation scope.
  * Impact: Without an actual mounted persistent path and Render configuration, retained tasks are not guaranteed across redeploys/restarts.
  * Resolution: Before retaining user data, configure a Render persistent disk, set `TODO_DB_PATH` to its mount path, and verify the mount/path in deployment. Otherwise document the service as ephemeral and accept data loss.

## Implementation Paths Considered

### Selected: Plain Python agents with validated intent extraction and repository-only SQLite

* Approach: Root `main.py` serves one HTML page and API; `TaskRepository` in `tools/repository.py` owns all persistence; a small orchestrator dispatches to Task, Planner, and Summary agents. Optional OpenAI Structured Outputs proposes intent; application validation and a rule parser fallback own safe execution.
* Rationale: Matches requested structure, maintains deterministic writes and no-key operation, and minimizes dependencies while remaining testable.
* Evidence: `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 14-50) and `.copilot-tracking/research/2026-10-19/greenfield-agentic-todo-app-research.md` (Lines 71-171)

### IP-01: Adopt a multi-agent orchestration framework

* Approach: Use an SDK that manages agent handoffs, tool calls, sessions, and tracing.
* Trade-offs: Built-in orchestration can help if the workflow grows to complex multi-turn handoffs, but it adds dependencies, run-loop concepts, and debugging surface for CRUD actions already controlled by server code.
* Rejection rationale: Current workflow needs one deterministic route to one specialist and no persistent agent sessions or approvals.
* Evidence: `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 18-28)

### IP-02: Let the model call CRUD tools directly

* Approach: Expose repository tools to OpenAI function calling and let the model select and call them.
* Trade-offs: More flexible tool selection, but increases network round trips and risks interpreting schema-valid arguments as authorization. Every tool call still needs application validation and safe dispatch.
* Rejection rationale: Server-side intent validation and deterministic agent routing satisfy the current actions with fewer failure modes.
* Evidence: `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 29-50)

### IP-03: Use an ORM instead of standard-library SQLite access

* Approach: Add SQLModel/SQLAlchemy mappings and session/unit-of-work management.
* Trade-offs: Easier richer relationships, migrations, and backend portability, but adds dependencies and state/session lifecycle complexity for one table.
* Rejection rationale: Standard-library SQLite meets current schema needs. Keep the repository boundary so a future adapter can replace it without agents bypassing the interface.
* Evidence: `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 51-70)

### IP-04: Use async routes or embed the HTML response

* Approach: Use async handlers with the synchronous DB/client stack, or inline HTML in an `HTMLResponse`.
* Trade-offs: Async can suit fully asynchronous I/O, and inline HTML is simple for generated content; however direct blocking calls can block the event loop and embedding duplicates the requested standalone file.
* Rejection rationale: Synchronous handlers fit `sqlite3` and the synchronous SDK. `FileResponse` serves the explicit root `index.html` without CWD dependence.
* Evidence: `.copilot-tracking/research/subagents/2026-10-19/alternatives-research.md` (Lines 71-84)

## Suggested Follow-On Work

* WI-01: Configure Render persistent disk and `TODO_DB_PATH` — Mount a persistent directory and point SQLite to it before retaining user data across deploys/restarts. Priority: high before production use; effort: small. Source: DD-03 and research's SQLite deployment risks. Dependency: service plan supports persistent storage.
* WI-02: Add authentication and per-user task ownership — Required before exposing personal task data to untrusted users or making this a multi-user service. Priority: medium; effort: medium. Source: single-user, no-auth proof-of-concept assumption. Dependency: user/identity model and ownership migration.
* WI-03: Add browser automation — Add an end-to-end test only if UI regressions warrant another test dependency. Priority: low; effort: small. Source: research notes that initial UI validation can be manual. Dependency: stable UI selectors and CI browser runtime.
