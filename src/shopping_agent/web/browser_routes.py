from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request, Query
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from shopping_agent.browser_jobs import BrowserJobError, BrowserJobStore
from shopping_agent.config import AppConfig
from shopping_agent.web.dependencies import get_config
from shopping_agent.web.schemas import WorkbenchModel
from shopping_agent.web.schemas import OperationDetail


class ExecutionInput(WorkbenchModel):
    task_id: int = Field(gt=0)
    query: str = Field(default="", max_length=120)
    max_pages: int = Field(default=1, ge=1, le=3, strict=True)
    acknowledge_risk: Literal[True]
    retry_of: int | None = Field(default=None, gt=0)

    @field_validator("acknowledge_risk", mode="before")
    @classmethod
    def explicit_boolean(cls, value):
        if value is not True:
            raise ValueError("Explicit acknowledgement required")
        return value


class BrowserResult(WorkbenchModel):
    run_ids: list[int] = Field(default_factory=list)
    listing_count: int = 0
    authenticated: bool | None = None


class BrowserJob(WorkbenchModel):
    id: int
    kind: Literal["login", "collection"]
    task_id: int | None
    request_id: int | None
    retry_of: int | None
    query: str
    max_pages: int
    actions: list[Literal["search", "detail"]]
    listing_ids: list[int]
    state: Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
    stage: str
    error_code: str | None
    error_detail: str | None
    result: BrowserResult
    verify_requested: bool
    stop_requested: bool
    created_at: str
    completed_at: str | None
    analysis_operation_id: int | None = None


class BrowserStatus(WorkbenchModel):
    auth_status: Literal["unknown", "verified", "invalid"]
    active_job: BrowserJob | None
    login_job: BrowserJob | None
    max_pages: int
    enabled: bool


class BrowserAuditEvent(WorkbenchModel):
    id: int
    event_type: str
    metadata: dict[str, str | int | bool | None]
    created_at: str


class BrowserAuditPage(WorkbenchModel):
    job_id: int
    has_more: bool
    items: list[BrowserAuditEvent]


def register_browser_routes(app: FastAPI):
    @app.exception_handler(BrowserJobError)
    async def browser_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": str(exc)}})

    @app.get("/api/browser/status", response_model=BrowserStatus)
    def status(request: Request, config: Annotated[AppConfig, Depends(get_config)]):
        return {**request.app.state.browser_store.status(), "max_pages": min(3, config.max_pages_per_platform),
                "enabled": "xianyu" in config.platforms and config.allow_login}

    @app.post("/api/setup/xianyu-login", status_code=202, response_model=BrowserJob)
    def login(request: Request, config: Annotated[AppConfig, Depends(get_config)]):
        job = BrowserJobStore(config).create_login()
        request.app.state.browser_coordinator.start(job["id"], config=config)
        return job

    @app.get("/api/browser/jobs/{job_id}", response_model=BrowserJob)
    def read_job(job_id: int, request: Request):
        return request.app.state.browser_store.get(job_id)

    @app.get("/api/browser/jobs/{job_id}/audit", response_model=BrowserAuditPage)
    def audit(job_id: int, request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 100):
        return request.app.state.browser_store.events(job_id, limit)

    @app.post("/api/browser/jobs/{job_id}/verify", response_model=BrowserJob)
    def verify(job_id: int, request: Request):
        return request.app.state.browser_coordinator.verify_login(job_id)

    @app.post("/api/browser/jobs/{job_id}/cancel", response_model=BrowserJob)
    def cancel(job_id: int, request: Request):
        return request.app.state.browser_coordinator.cancel(job_id)

    @app.post("/api/browser/jobs/{job_id}/resume-verification", response_model=BrowserJob)
    def resume_verification(job_id: int, request: Request):
        return request.app.state.browser_coordinator.resume_verification(job_id)

    @app.post("/api/browser/jobs/{job_id}/analyze", response_model=OperationDetail, status_code=202)
    def analyze(job_id: int, request: Request):
        operation_id = request.app.state.browser_store.analyze(job_id)
        request.app.state.coordinator.start(operation_id)
        return request.app.state.conversation_service.get_operation(operation_id)

    @app.get("/api/action-requests/{request_id}/execution", response_model=BrowserJob | None)
    def execution(request_id: int, task_id: int, request: Request):
        return request.app.state.browser_store.latest_for_request(task_id, request_id)

    @app.post("/api/action-requests/{request_id}/execute", status_code=202, response_model=BrowserJob)
    def execute(request_id: int, body: ExecutionInput, request: Request,
                config: Annotated[AppConfig, Depends(get_config)]):
        store = BrowserJobStore(config)
        if "xianyu" not in config.platforms or not config.allow_login:
            raise BrowserJobError("collection_disabled", "请在设置中启用闲鱼，并允许浏览器登录。", 400)
        if store.status()["auth_status"] != "verified":
            raise BrowserJobError("login_required", "请先在设置中登录闲鱼并验证。")
        job = store.create_collection(body.task_id, request_id, body.query, body.max_pages, body.retry_of)
        request.app.state.browser_coordinator.start(job["id"], config=config)
        return job
