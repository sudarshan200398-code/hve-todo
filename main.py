"""FastAPI application for the todo API."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal, Mapping

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from tools import TaskRepository, TaskTools


INDEX_FILE = Path(__file__).resolve().with_name("index.html")


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateTaskRequest(_StrictRequest):
    title: StrictStr
    priority: Literal["low", "normal", "high"] = "normal"
    due_date: StrictStr | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value.strip()

    @field_validator("due_date")
    @classmethod
    def due_date_must_be_iso_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("due_date must be a valid ISO date (YYYY-MM-DD)") from error
        if parsed.isoformat() != value:
            raise ValueError("due_date must use YYYY-MM-DD format")
        return value

class PatchTaskRequest(_StrictRequest):
    title: StrictStr | None = None
    completed: StrictBool | None = None
    priority: Literal["low", "normal", "high"] | None = None
    due_date: StrictStr | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be empty")
        return value.strip() if value is not None else None

    @field_validator("due_date")
    @classmethod
    def due_date_must_be_iso_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("due_date must be a valid ISO date (YYYY-MM-DD)") from error
        if parsed.isoformat() != value:
            raise ValueError("due_date must use YYYY-MM-DD format")
        return value

    @model_validator(mode="after")
    def require_patch_fields(self) -> PatchTaskRequest:
        supplied = self.model_fields_set
        if not supplied:
            raise ValueError("PATCH body must contain at least one field")
        for field in ("title", "completed", "priority"):
            if field in supplied and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


class AssistantRequest(_StrictRequest):
    message: StrictStr

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value


class EmptyRequest(_StrictRequest):
    pass


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, strict=True)

    id: StrictInt
    title: StrictStr
    completed: StrictBool
    priority: Literal["low", "normal", "high"]
    due_date: StrictStr | None
    created_at: StrictStr
    updated_at: StrictStr
    completed_at: StrictStr | None


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]


class SummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, strict=True)

    open_count: StrictInt
    completed_count: StrictInt
    due_today_count: StrictInt
    completed_today_count: StrictInt


class AssistantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, strict=True)

    message: StrictStr
    agent: StrictStr
    mode: Literal["ai", "fallback"]
    task: TaskResponse | None = None
    tasks: list[TaskResponse] | None = None
    suggestion: TaskResponse | None = None
    summary: SummaryResponse | None = None


def _agent_services(
    tools: TaskTools, model_adapter: Any | None
) -> tuple[Any | None, Any | None, Any | None, Any | None]:
    """Build the Phase 2 agents using the shared tools facade.

    The agent contract is intentionally small: Orchestrator.handle(message),
    PlannerAgent.suggest(), and SummaryAgent.summarize(). Each service may
    return the matching assistant response fields as a mapping or object.
    """
    try:
        from agents.orchestrator import Orchestrator, PlannerAgent, SummaryAgent, TaskAgent
    except ModuleNotFoundError as error:
        if error.name not in {"agents", "agents.orchestrator"}:
            raise
        return None, None, None, None

    task_agent = TaskAgent(tools)
    planner_agent = PlannerAgent(tools)
    summary_agent = SummaryAgent(tools)
    orchestrator = Orchestrator(tools, model_client=model_adapter)
    return orchestrator, task_agent, planner_agent, summary_agent


def _assistant_payload(
    result: Any,
    *,
    forced_agent: str | None = None,
    payload_field: str | None = None,
    default_message: str = "",
) -> dict[str, Any]:
    """Normalize agent responses to the fixed public assistant response shape."""
    if isinstance(result, AssistantResponse):
        payload = result.model_dump()
    elif isinstance(result, Mapping) and any(
        key in result for key in ("agent", "mode", "task", "tasks", "suggestion", "summary")
    ):
        payload = dict(result)
    else:
        payload = {}
        if payload_field is not None:
            payload[payload_field] = result

    payload.setdefault("message", default_message)
    payload.setdefault("agent", forced_agent or "orchestrator")
    payload.setdefault("mode", "fallback")
    for field in ("task", "tasks", "suggestion", "summary"):
        payload.setdefault(field, None)
    if forced_agent is not None:
        payload["agent"] = forced_agent
    return AssistantResponse.model_validate(payload).model_dump()


def create_app(
    repository: TaskRepository | None = None,
    *,
    db_path: str | Path | None = None,
    orchestrator: Any | None = None,
    task_agent: Any | None = None,
    planner_agent: Any | None = None,
    summary_agent: Any | None = None,
    model_adapter: Any | None = None,
) -> FastAPI:
    """Create an app with injectable persistence and agent services for tests."""
    task_repository = repository or TaskRepository(db_path)
    tools = TaskTools(task_repository)

    if any(service is None for service in (orchestrator, task_agent, planner_agent, summary_agent)):
        defaults = _agent_services(tools, model_adapter)
        orchestrator = orchestrator or defaults[0]
        task_agent = task_agent or defaults[1]
        planner_agent = planner_agent or defaults[2]
        summary_agent = summary_agent or defaults[3]

    application = FastAPI()
    application.state.repository = task_repository
    application.state.tools = tools
    application.state.orchestrator = orchestrator
    application.state.task_agent = task_agent
    application.state.planner_agent = planner_agent
    application.state.summary_agent = summary_agent

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"location": list(item.get("loc", ())), "message": item.get("msg", "Invalid value"), "type": item.get("type", "")}
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": details,
                }
            },
        )

    @application.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, error: HTTPException) -> JSONResponse:
        code = "not_found" if error.status_code == 404 else "http_error"
        message = str(error.detail)
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": code, "message": message}},
            headers=error.headers,
        )

    @application.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(INDEX_FILE, media_type="text/html")

    @application.get("/api/tasks", response_model=TaskListResponse)
    def list_tasks(completed: bool | None = None) -> dict[str, Any]:
        return {"tasks": tools.list_tasks(completed=completed)}

    @application.post("/api/tasks", response_model=TaskResponse, status_code=201)
    def create_task(request: CreateTaskRequest) -> Any:
        return tools.create_task(
            request.title, priority=request.priority, due_date=request.due_date
        )

    @application.get("/api/tasks/{task_id}", response_model=TaskResponse)
    def get_task(task_id: int) -> Any:
        task = tools.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @application.patch("/api/tasks/{task_id}", response_model=TaskResponse)
    def update_task(task_id: int, request: PatchTaskRequest) -> Any:
        changes = request.model_dump(exclude_unset=True)
        task = tools.update_task(task_id, changes)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @application.delete("/api/tasks/{task_id}", status_code=204)
    def delete_task(task_id: int) -> Response:
        if not tools.delete_task(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        return Response(status_code=204)

    @application.post("/api/assistant", response_model=AssistantResponse)
    def assistant(request: AssistantRequest) -> dict[str, Any]:
        service = application.state.orchestrator
        if service is None:
            raise HTTPException(status_code=503, detail="Assistant agents are unavailable")
        result = service.handle(request.message)
        return _assistant_payload(result)

    @application.post("/api/assistant/suggest-next", response_model=AssistantResponse)
    def suggest_next(_request: EmptyRequest) -> dict[str, Any]:
        service = application.state.planner_agent
        if service is None:
            raise HTTPException(status_code=503, detail="Planner agent is unavailable")
        result = service.suggest()
        return _assistant_payload(
            result,
            forced_agent="planner",
            payload_field="suggestion",
            default_message="Suggested the next task.",
        )

    @application.get("/api/assistant/daily-summary", response_model=AssistantResponse)
    def daily_summary() -> dict[str, Any]:
        service = application.state.summary_agent
        if service is None:
            raise HTTPException(status_code=503, detail="Summary agent is unavailable")
        result = service.summarize()
        return _assistant_payload(
            result,
            forced_agent="summary",
            payload_field="summary",
            default_message="Daily summary ready.",
        )

    return application


app = create_app()
