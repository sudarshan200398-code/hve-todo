"""Intent extraction, validation, and named-agent dispatch."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from tools.repository import Priority, TaskTools

from .planner_agent import PlannerAgent
from .summary_agent import SummaryAgent
from .task_agent import TaskAgent

logger = logging.getLogger("uvicorn.error")
URGENT_WORDS = re.compile(r"\b(?:urgent|urgently|asap|critical|important|high priority)\b", re.I)

Action = Literal["create", "update", "complete", "delete", "list", "suggest", "summary", "unknown"]


class AssistantIntent(BaseModel):
    """Strict structured proposal; nullable fields remain required for JSON schema."""

    model_config = ConfigDict(extra="forbid")

    action: Action
    title: str | None
    due_date: str | None
    priority: Priority | None
    task_reference: str | None
    needs_clarification: bool


class Orchestrator:
    """Route a user request through optional model extraction and safe fallback."""

    MODEL_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        tools: TaskTools,
        *,
        model_client: object | None = None,
        api_key: str | None = None,
        model: str | None = None,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self._task_agent = TaskAgent(tools)
        self._planner = PlannerAgent(tools, today_provider=today_provider)
        self._summary = SummaryAgent(tools)
        self._today_provider = today_provider or (lambda: datetime.now(timezone.utc).date())
        self._api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._model_client = model_client

    def handle(self, message: str) -> dict[str, object]:
        """Process one assistant request and always return the HTTP result contract."""
        if not isinstance(message, str) or not message.strip():
            return self._response(
                "Please enter a request.", agent="orchestrator", mode="fallback"
            )

        intent: AssistantIntent | None = None
        mode: Literal["ai", "fallback"] = "fallback"
        if self._api_key.strip():
            try:
                intent = self._extract_intent(message)
                mode = "ai"
            except Exception as error:
                # Provider, timeout, refusal, and invalid response all degrade safely.
                logger.warning("LLM intent extraction failed, using fallback: %s: %s", type(error).__name__, error)
                intent = None

        if intent is None:
            intent = self._parse_fallback(message)
        return self._dispatch(intent, mode)

    def suggest_next(self) -> dict[str, object]:
        task = self._planner.suggest()
        text = f"Next, work on “{task.title}”." if task else "There are no open tasks to suggest."
        return self._response(text, agent="planner", mode="fallback", suggestion=task)

    def daily_summary(self) -> dict[str, object]:
        summary = self._summary.summarize()
        text = (
            f"You have {summary['open_count']} open and {summary['completed_count']} completed tasks. "
            f"{summary['due_today_count']} are due today; "
            f"{summary['completed_today_count']} were completed today."
        )
        return self._response(text, agent="summary", mode="fallback", summary=summary)

    def _extract_intent(self, message: str) -> AssistantIntent:
        client = self._model_client
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                api_key=self._api_key,
                timeout=self.MODEL_TIMEOUT_SECONDS,
                max_retries=2,
            )
        # Plain JSON mode works with OpenAI and with OpenAI-compatible
        # providers such as Gemini (set OPENAI_BASE_URL).
        result = client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract a todo intent only. Do not execute actions. Reply with one JSON object "
                        "with exactly these keys: action (one of create, update, complete, delete, list, "
                        "suggest, summary, unknown), title (string or null), due_date (YYYY-MM-DD or null), "
                        "priority (low, normal, high or null), task_reference (string or null), "
                        "needs_clarification (true or false). Return unknown and needs_clarification true "
                        "for ambiguity. Use ISO dates based on the supplied UTC date. References must "
                        "preserve the user's exact task identifier or title. Words such as urgent, asap, "
                        "important or critical mean priority high; no rush, whenever or someday mean priority low."
                    ),
                },
                {
                    "role": "user",
                    "content": f"UTC date: {self._today_provider().isoformat()}\nRequest: {message}",
                },
            ],
        )
        content = result.choices[0].message.content if result.choices else None
        if not content:
            raise ValueError("No structured intent was returned")
        parsed = json.loads(content)
        if isinstance(parsed, dict) and parsed.get("priority") == "medium":
            parsed["priority"] = "normal"
        if (
            isinstance(parsed, dict)
            and parsed.get("action") == "create"
            and parsed.get("priority") in (None, "normal")
            and URGENT_WORDS.search(message)
        ):
            parsed["priority"] = "high"
        return self._validate_intent(parsed)

    @staticmethod
    def _validate_intent(value: object) -> AssistantIntent:
        try:
            intent = (
                value
                if isinstance(value, AssistantIntent)
                else AssistantIntent.model_validate(value)
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise ValueError("Invalid intent") from error
        if intent.title is not None and not intent.title.strip():
            raise ValueError("Empty task title")
        if intent.task_reference is not None and not intent.task_reference.strip():
            raise ValueError("Empty task reference")
        if intent.due_date is not None:
            try:
                date.fromisoformat(intent.due_date)
            except ValueError as error:
                raise ValueError("Invalid due date") from error
        if intent.action == "create" and intent.title is None:
            raise ValueError("Create intent requires a title")
        if intent.action in {"update", "complete", "delete"} and not intent.task_reference:
            raise ValueError("Task operation requires a reference")
        if intent.action == "update" and not any(
            value is not None for value in (intent.title, intent.due_date, intent.priority)
        ):
            raise ValueError("Update intent requires a change")
        return intent

    def _parse_fallback(self, message: str) -> AssistantIntent:
        text = message.strip()
        lower = text.casefold().strip().rstrip(".!?")
        empty = {
            "title": None,
            "due_date": None,
            "priority": None,
            "task_reference": None,
            "needs_clarification": False,
        }

        if re.fullmatch(r"(?:show|list)(?:\s+me)?\s+(?:(all|open|incomplete|completed|done)\s+)?(?:tasks?|todos?)", lower):
            match = re.fullmatch(
                r"(?:show|list)(?:\s+me)?\s+(?:(all|open|incomplete|completed|done)\s+)?(?:tasks?|todos?)",
                lower,
            )
            qualifier = match.group(1) if match else None
            return AssistantIntent(
                action="list", **{**empty, "task_reference": qualifier}
            )

        if lower in {"suggest", "suggest next", "what should i do next", "next task"}:
            return AssistantIntent(action="suggest", **empty)
        if lower in {"summary", "daily summary", "summarize", "summarise", "how am i doing today"}:
            return AssistantIntent(action="summary", **empty)

        create_match = re.match(
            r"^(?:please\s+)?(?:add|create|remember)\s+(?:a\s+)?(?:task(?:\s+to)?\s+)?(.+)$",
            text,
            re.IGNORECASE,
        )
        if create_match:
            title = create_match.group(1).strip().rstrip(".!?")
            due_date = None
            due_match = re.search(r"\b(today|tomorrow)\b", title, re.IGNORECASE)
            if due_match:
                due_date = self._today_provider() + (
                    timedelta(days=1) if due_match.group(1).casefold() == "tomorrow" else timedelta()
                )
                title = title[: due_match.start()] + " " + title[due_match.end() :]
            priority: Priority = "normal"
            priority_match = re.search(r"\b(high|normal|low)\s+priority\b", title, re.IGNORECASE)
            if priority_match:
                priority = priority_match.group(1).casefold()  # type: ignore[assignment]
                title = title[: priority_match.start()] + " " + title[priority_match.end() :]
            title = re.sub(r"[,;\s]+", " ", title).strip(" .,!?:;")
            if title:
                return AssistantIntent(
                    action="create",
                    title=title,
                    due_date=due_date.isoformat() if due_date else None,
                    priority=priority,
                    task_reference=None,
                    needs_clarification=False,
                )

        command_patterns = (
            ("complete", r"^(?:complete|finish|done)(?:\s+task)?\s+(?P<ref>.+)$"),
            ("delete", r"^(?:delete|remove)(?:\s+task)?\s+(?P<ref>.+)$"),
        )
        for action, pattern in command_patterns:
            match = re.match(pattern, lower, re.IGNORECASE)
            if match:
                return AssistantIntent(
                    action=action,
                    **{
                        **empty,
                        "task_reference": match.group("ref").strip().rstrip(".!?"),
                    },
                )

        marked_complete = re.match(r"^mark\s+(?:task\s+)?(?P<ref>.+?)\s+(?:as\s+)?complete$", lower)
        if marked_complete:
            return AssistantIntent(
                action="complete",
                **{**empty, "task_reference": marked_complete.group("ref").strip()},
            )

        rename = re.match(r"^(?:update|edit|rename)(?:\s+task)?\s+(?P<ref>\d+|#[\w-]+)\s+(?:to|as)\s+(?P<title>.+)$", text, re.IGNORECASE)
        if rename:
            return AssistantIntent(
                action="update",
                title=rename.group("title").strip().rstrip(".!?"),
                due_date=None,
                priority=None,
                task_reference=rename.group("ref"),
                needs_clarification=False,
            )
        return AssistantIntent(
            action="unknown", **{**empty, "needs_clarification": True}
        )

    def _dispatch(self, intent: AssistantIntent, mode: Literal["ai", "fallback"]) -> dict[str, object]:
        if intent.needs_clarification or intent.action == "unknown":
            return self._response(
                "I’m not sure what you mean. Please specify one task action and an exact task ID or title.",
                agent="orchestrator",
                mode=mode,
            )

        if intent.action == "suggest":
            suggestion = self._planner.suggest()
            message = f"Next, work on “{suggestion.title}”." if suggestion else "There are no open tasks to suggest."
            return self._response(message, agent="planner", mode=mode, suggestion=suggestion)
        if intent.action == "summary":
            summary = self._summary.summarize()
            message = (
                f"You have {summary['open_count']} open and {summary['completed_count']} completed tasks. "
                f"{summary['due_today_count']} are due today; {summary['completed_today_count']} were completed today."
            )
            return self._response(message, agent="summary", mode=mode, summary=summary)
        if intent.action == "list":
            qualifier = (intent.task_reference or "").casefold()
            completed = True if qualifier in {"completed", "done"} else False if qualifier in {"open", "incomplete"} else None
            tasks = self._task_agent.list(completed=completed)
            return self._response(f"Found {len(tasks)} task(s).", agent="task", mode=mode, tasks=tasks)
        if intent.action == "create":
            try:
                task = self._task_agent.create(
                    intent.title or "", priority=intent.priority or "normal", due_date=intent.due_date
                )
            except (TypeError, ValueError):
                return self._clarification(mode)
            return self._response(f"Added “{task.title}”.", agent="task", mode=mode, task=task)

        reference = self._task_agent.resolve_reference(intent.task_reference or "")
        if reference.ambiguous:
            return self._response(
                "That title matches more than one task. Please use the task ID.",
                agent="task",
                mode=mode,
            )
        task = reference.task
        if task is None:
            return self._response(
                "I couldn’t find that task. Please check its ID or exact title.",
                agent="task",
                mode=mode,
            )
        if intent.action == "complete":
            changed = self._task_agent.complete(task.id)
            return self._response(
                f"Completed “{changed.title}”." if changed else "That task no longer exists.",
                agent="task",
                mode=mode,
                task=changed,
            )
        if intent.action == "delete":
            deleted = self._task_agent.delete(task.id)
            return self._response(
                f"Deleted “{task.title}”." if deleted else "That task no longer exists.",
                agent="task",
                mode=mode,
            )
        if intent.action == "update":
            changes: dict[str, object] = {}
            if intent.title is not None:
                changes["title"] = intent.title
            if intent.priority is not None:
                changes["priority"] = intent.priority
            if intent.due_date is not None:
                changes["due_date"] = intent.due_date
            try:
                changed = self._task_agent.update(task.id, changes)
            except (TypeError, ValueError):
                return self._clarification(mode)
            return self._response(
                f"Updated “{changed.title}”." if changed else "That task no longer exists.",
                agent="task",
                mode=mode,
                task=changed,
            )
        return self._clarification(mode)

    def _clarification(self, mode: Literal["ai", "fallback"]) -> dict[str, object]:
        return self._response(
            "Please clarify the task details. No changes were made.", agent="orchestrator", mode=mode
        )

    @staticmethod
    def _response(
        message: str,
        *,
        agent: str,
        mode: Literal["ai", "fallback"],
        task: object | None = None,
        tasks: object | None = None,
        suggestion: object | None = None,
        summary: object | None = None,
    ) -> dict[str, object]:
        return {
            "message": message,
            "agent": agent,
            "mode": mode,
            "task": task,
            "tasks": tasks,
            "suggestion": suggestion,
            "summary": summary,
        }