from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from shopping_agent import setup_status
from shopping_agent.config import AppConfig, load_effective_config
from shopping_agent.codex_runtime import CodexRuntime
from shopping_agent.conversation_service import ConversationService
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.browser_jobs import BrowserJobStore, BrowserJobCoordinator
from shopping_agent.browser_collection import BrowserCollectionBackend
from shopping_agent.web.browser_routes import register_browser_routes
from shopping_agent.web.monitor_routes import register_monitor_routes
from shopping_agent.web.project_routes import register_project_routes
from shopping_agent.web.image_routes import register_image_routes
from shopping_agent.web.vision_routes import register_vision_routes
from shopping_agent.project_research import ProjectResearch
from shopping_agent.monitoring import MonitorStore, MonitorCoordinator
from shopping_agent.monitor_engine import GoofishEngine
from shopping_agent.service_lease import ServiceLease
from shopping_agent.web.conversation_routes import register_conversation_routes
from shopping_agent.setup_status import CodexStatus, SetupCheck, SetupStatus
from shopping_agent.user_settings import UserSettings, save_user_settings
from shopping_agent.web.dependencies import (
    get_config,
    get_settings,
    get_settings_path,
    get_workbench_service,
)
from shopping_agent.web.schemas import (
    CandidatePage,
    DebugSnapshot,
    ListingEvidence,
    MarketOverview,
    TaskDetail,
    ResearchHistory, AssessmentBatch, TaskHistory,
    TaskListPage,
)
from shopping_agent.web.services import WorkbenchService


STATIC_DIR = Path(__file__).with_name("static")


class HealthResponse(BaseModel):
    status: Literal["ok"]


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setup_completed: bool | None = None
    setup_mode: Literal["basic", "ai"] | None = None
    default_city: str | None = None
    platforms: list[str] | None = None
    allow_ocr: bool | None = None
    preferred_view: Literal["research", "debug"] | None = None


def create_app(config_path: Path, settings_path: Path) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        config = load_effective_config(config_path, settings_path)
        with ServiceLease(config.database_path) as lease:
            app.state.service_lease = lease
            service = ConversationService(config)
            runtime = getattr(app.state, "codex_runtime", None) or CodexRuntime(
                Path(__file__).resolve().parents[3], config.codex_bin, config.codex_timeout_seconds)
            app.state.codex_runtime = runtime
            app.state.conversation_service = service
            app.state.coordinator = OperationCoordinator(service, runtime)
            app.state.coordinator.recover_interrupted()
            app.state.browser_store = BrowserJobStore(config)
            app.state.browser_store.recover_interrupted()
            backend = getattr(app.state, "browser_backend", None) or BrowserCollectionBackend()
            app.state.browser_coordinator = BrowserJobCoordinator(app.state.browser_store, backend, app.state.coordinator)
            app.state.monitor_store = MonitorStore(config)
            app.state.monitor_store.recover_interrupted()
            engine = getattr(app.state, "monitor_engine", None) or GoofishEngine(config)
            app.state.monitor_coordinator = MonitorCoordinator(app.state.monitor_store, engine)
            app.state.project_research = ProjectResearch(config, runtime, app.state.monitor_store)
            app.state.project_research.visual_settings_reader = app.state.vision_settings.read
            from shopping_agent.web.visual_investigation_routes import service as visual_investigation_service
            visual_investigation_service(app)
            app.state.monitor_store.window_guard = app.state.project_research.settle_windows
            app.state.monitor_store.continue_window = app.state.project_research.continue_window
            from shopping_agent.auto_covers import AutoCovers
            app.state.auto_covers = AutoCovers(config, resolver=getattr(app.state,'cover_resolver',None), transport=getattr(app.state,'cover_transport',None))
            app.state.project_research.start()
            if config.monitor_engine.enabled and "xianyu" in config.platforms:
                app.state.monitor_coordinator.start()
            try:
                app.state.auto_covers.start()
                yield
            finally:
                errors = []
                for coordinator in (app.state.auto_covers, app.state.project_research, app.state.monitor_coordinator, app.state.browser_coordinator, app.state.coordinator):
                    try:
                        coordinator.shutdown()
                    except BaseException as exc:
                        errors.append(exc)
                if errors:
                    lease.retain_until_exit()
                    raise errors[0]

    app = FastAPI(title="SecondPick Research Workbench", lifespan=lifespan)
    register_project_routes(app)
    from shopping_agent.web.project_chat_routes import register as register_project_chat
    register_project_chat(app)
    from shopping_agent.web.cover_routes import register as register_covers
    register_covers(app)
    app.state.config_path = Path(config_path)
    app.state.settings_path = Path(settings_path)
    register_vision_routes(app, Path(settings_path))
    from shopping_agent.web.visual_routes import register_visual_routes
    register_visual_routes(app)
    from shopping_agent.web.visual_investigation_routes import register as register_visual_investigations
    register_visual_investigations(app)

    @app.middleware("http")
    async def enforce_loopback_request(request: Request, call_next):
        if not _is_loopback_host(request.headers.get("host")):
            return _error_response(400, "invalid_host", "Host must be loopback.")
        origin = request.headers.get("origin")
        if origin is not None and not _same_loopback_origin(origin, request.url):
            return _error_response(403, "invalid_origin", "Origin must match the local service.")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("sec-fetch-site") == "cross-site":
            return _error_response(403, "invalid_origin", "Cross-site actions are not allowed.")
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request, exc
        return _error_response(
            422,
            "validation_error",
            "Request validation failed.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        del request
        if exc.status_code == 404:
            code = "not_found"
        elif exc.status_code == 405:
            code = "method_not_allowed"
        else:
            code = "http_error"
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return _error_response(exc.status_code, code, message)

    @app.exception_handler(ValueError)
    async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        del request
        message = str(exc)
        is_missing_task = message.startswith("Research task not found:") or (
            message.startswith("Research task ") and message.endswith(" does not exist.")
        )
        if is_missing_task:
            task_id = _task_id_from_error(message)
            message = f"Research task not found: {task_id}"
            return _error_response(404, "not_found", message)
        return _error_response(400, "invalid_request", message)

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/api/setup/status", response_model=SetupStatus)
    def read_setup_status(
        config: Annotated[AppConfig, Depends(get_config)],
        settings: Annotated[UserSettings, Depends(get_settings)],
    ) -> SetupStatus:
        return setup_status.build_setup_status(config, settings, check_browser=False)

    @app.post("/api/setup/check-environment", response_model=list[SetupCheck])
    def check_environment(
        config: Annotated[AppConfig, Depends(get_config)],
    ) -> list[SetupCheck]:
        return [
            SetupCheck(name=result.name, ok=result.ok, detail=result.detail)
            for result in setup_status.run_doctor(config, check_browser=False)
        ]

    @app.post("/api/setup/check-codex", response_model=CodexStatus)
    def check_codex() -> CodexStatus:
        return setup_status.check_codex_availability()

    @app.get("/api/settings", response_model=UserSettings)
    def read_settings(
        settings: Annotated[UserSettings, Depends(get_settings)],
    ) -> UserSettings:
        return settings

    @app.patch("/api/settings", response_model=UserSettings)
    def patch_settings(
        patch: SettingsPatch,
        settings: Annotated[UserSettings, Depends(get_settings)],
        settings_file: Annotated[Path, Depends(get_settings_path)],
    ) -> UserSettings:
        updates = {
            key: value
            for key, value in patch.model_dump(exclude_unset=True).items()
            if value is not None or key == "default_city"
        }
        saved = settings.model_copy(update=updates)
        save_user_settings(settings_file, saved)
        return saved

    @app.get("/api/tasks", response_model=TaskListPage)
    def list_tasks(
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> TaskListPage:
        return service.list_tasks(limit=limit, offset=offset)

    @app.get("/api/tasks/{task_id}", response_model=TaskDetail)
    def get_task(
        task_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
    ) -> TaskDetail:
        return service.get_task(task_id)

    @app.get("/api/tasks/{task_id}/history", response_model=TaskHistory)
    def get_task_history(
        task_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
        limit: Annotated[int, Query(ge=1, le=20)] = 10,
        cursor: str | None = None,
    ) -> TaskHistory:
        return service.get_task_history(task_id, limit, cursor)

    @app.get("/api/tasks/{task_id}/research", response_model=ResearchHistory)
    def get_research_history(
        task_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
        limit: Annotated[int, Query(ge=1, le=20)] = 10,
        cursor: str | None = None,
    ) -> ResearchHistory:
        return service.get_research_history(task_id, limit, cursor)

    @app.get("/api/tasks/{task_id}/research/assessments/{assessment_id}", response_model=AssessmentBatch)
    def get_assessment(
        task_id: int, assessment_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
    ) -> AssessmentBatch:
        assessment = service.get_assessment(task_id, assessment_id)
        if assessment is None:
            raise HTTPException(status_code=404, detail="Assessment not found in this task.")
        return assessment

    @app.get("/api/tasks/{task_id}/candidates", response_model=CandidatePage)
    def get_candidates(
        task_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> CandidatePage:
        return service.get_candidates(task_id, limit, cursor)

    @app.get("/api/tasks/{task_id}/market", response_model=MarketOverview)
    def get_market(
        task_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
    ) -> MarketOverview:
        return service.get_market(task_id)

    @app.get("/api/tasks/{task_id}/debug", response_model=DebugSnapshot)
    def get_debug_snapshot(
        task_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
    ) -> DebugSnapshot:
        return service.get_debug_snapshot(task_id)

    @app.get("/api/listings/{listing_id}/evidence", response_model=ListingEvidence)
    def get_listing_evidence(
        listing_id: int,
        task_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
    ) -> ListingEvidence:
        return service.get_listing_evidence(task_id, listing_id)

    @app.get("/api/tasks/{task_id}/reports/{report_id}")
    def get_report(
        task_id: int,
        report_id: int,
        service: Annotated[WorkbenchService, Depends(get_workbench_service)],
    ) -> FileResponse:
        report_path = service.get_report_path(task_id, report_id)
        if report_path is None:
            raise HTTPException(status_code=404)
        return FileResponse(
            report_path,
            filename=report_path.name,
            content_disposition_type="attachment",
        )

    register_conversation_routes(app)
    register_browser_routes(app)
    register_image_routes(app)
    register_monitor_routes(app)

    @app.get("/{spa_path:path}", include_in_schema=False)
    def serve_spa(spa_path: str) -> FileResponse:
        if spa_path == "api" or spa_path.startswith("api/"):
            raise HTTPException(status_code=404)

        static_root = STATIC_DIR.resolve()
        requested_file = (STATIC_DIR / spa_path).resolve()
        if not requested_file.is_relative_to(static_root):
            raise HTTPException(status_code=404)
        if spa_path and requested_file.is_file():
            media_type = {
                ".css": "text/css",
                ".js": "text/javascript",
                ".mjs": "text/javascript",
            }.get(requested_file.suffix.lower())
            return FileResponse(requested_file, media_type=media_type)
        if spa_path.startswith("assets/") or Path(spa_path).suffix:
            raise HTTPException(status_code=404)

        index_file = STATIC_DIR / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="Frontend build not found")
        return FileResponse(index_file)

    return app


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _task_id_from_error(message: str) -> str:
    if message.startswith("Research task not found:"):
        return message.rsplit(":", 1)[1].strip()
    return message.removeprefix("Research task ").removesuffix(" does not exist.")


def _is_loopback_host(value: str | None) -> bool:
    if value is None:
        return False
    candidate = value.strip()
    if not candidate or any(character in candidate for character in "/\\@, "):
        return False
    if candidate == "::1":
        return True
    try:
        parsed = urlsplit(f"//{candidate}")
        if parsed.path or parsed.query or parsed.fragment or parsed.username:
            return False
        parsed.port
    except ValueError:
        return False
    return _is_loopback_hostname(parsed.hostname)


def _is_loopback_origin(value: str) -> bool:
    candidate = value.strip()
    if not candidate or "," in candidate:
        return False
    try:
        parsed = urlsplit(candidate)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            return False
        parsed.port
    except ValueError:
        return False
    return _is_loopback_hostname(parsed.hostname)


def _same_loopback_origin(value, target):
    if not _is_loopback_origin(value):
        return False
    parsed = urlsplit(value.strip())
    return (parsed.scheme == target.scheme and parsed.hostname == target.hostname
            and (parsed.port or (443 if parsed.scheme == "https" else 80)) ==
            (target.port or (443 if target.scheme == "https" else 80)))


def _is_loopback_hostname(hostname: str | None) -> bool:
    if hostname is None:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
