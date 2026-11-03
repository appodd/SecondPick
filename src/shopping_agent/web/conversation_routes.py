from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi import Path as ApiPath
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, field_validator

from shopping_agent.conversation_store import (
    ConversationStoreError, RecordNotFoundError, OperationConflictError,
    OperationStateError, ActionDecisionConflictError,
)
from shopping_agent.operation_stream import stream_operation_events
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.web.dependencies import get_config
from shopping_agent.web.schemas import (
    WorkbenchModel, TaskCreationResponse, MessageCreationResponse, MessagePage,
    CandidateCheck, CandidateCheckPage, CheckState,
    CheckSuggestionPage, CheckSuggestionAcceptance,
    CheckReview, CheckReviewPage,
    ActionRequestPage, ActionDecisionResponse, OperationDetail, TaskRecord,
)


class MessageInput(WorkbenchModel):
    message: str = Field(min_length=1, max_length=20000)

    @field_validator("message")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Message is blank")
        return value


class CandidateStatementInput(WorkbenchModel):
    listing_id: int = Field(gt=0, le=2**63-1)
    kind: Literal["seller_reply", "user_observation"]


class FollowupInput(MessageInput):
    candidate_statement: CandidateStatementInput | None = None


class RenameInput(WorkbenchModel):
    title: str = Field(min_length=1, max_length=60)


class StatementChangeInput(WorkbenchModel):
    action: Literal["rebind", "withdraw"]
    expected_revision_id: int = Field(ge=0, le=2**63-1)
    listing_id: int | None = Field(default=None, gt=0, le=2**63-1)
    kind: Literal["seller_reply", "user_observation"] | None = None


class DecisionInput(WorkbenchModel):
    task_id: int = Field(gt=0)


class CheckCreateInput(WorkbenchModel):
    question: str = Field(min_length=1, max_length=1000)
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")


class CheckChangeInput(WorkbenchModel):
    expected_revision_id: int = Field(ge=0, le=2**63-1)
    state: CheckState
    statement_id: int | None = Field(default=None, gt=0, le=2**63-1)
    statement_revision_id: int | None = Field(default=None, ge=0, le=2**63-1)
    note: str | None = Field(default=None, min_length=1, max_length=2000)


ScopeId = Annotated[int, ApiPath(gt=0, le=2**63-1)]


class CheckSuggestionConfirm(WorkbenchModel):
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def require_true(cls, value):
        if value is not True:
            raise ValueError("请明确确认保存此问题。")
        return value


class ReviewSourceInput(WorkbenchModel):
    statement_id: int = Field(gt=0, le=2**63-1)
    revision_id: int = Field(ge=0, le=2**63-1)


class CheckReviewInput(WorkbenchModel):
    expected_review_id: int = Field(ge=0, le=2**63-1)
    expected_check_revision_id: int = Field(ge=0, le=2**63-1)
    expected_basis_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["record", "withdraw"]
    outcome: Literal["answered", "uncertain", "conflict"] | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=2000)
    sources: list[ReviewSourceInput] = Field(default_factory=list, max_length=5)


def register_conversation_routes(app: FastAPI) -> None:
    from shopping_agent.candidate_checks import CandidateChecks
    from shopping_agent.check_suggestions import CheckSuggestions
    from shopping_agent.check_reviews import CheckReviews

    @app.get("/api/tasks/{task_id}/listings/{listing_id}/checks/{check_id}/reviews", response_model=CheckReviewPage)
    def check_reviews(task_id: ScopeId, listing_id: ScopeId, check_id: ScopeId, request: Request,
            limit: Annotated[int, Query(ge=1, le=50)] = 20,
            before_id: Annotated[int | None, Query(gt=0, le=2**63-1)] = None):
        return CheckReviews(request.app.state.conversation_service.config).page(task_id, listing_id, check_id, limit=limit, before_id=before_id)

    @app.post("/api/tasks/{task_id}/listings/{listing_id}/checks/{check_id}/reviews", response_model=CheckReview, status_code=201)
    def save_check_review(task_id: ScopeId, listing_id: ScopeId, check_id: ScopeId, body: CheckReviewInput, request: Request):
        return CheckReviews(request.app.state.conversation_service.config).change(task_id, listing_id, check_id, **body.model_dump())

    @app.get("/api/tasks/{task_id}/listings/{listing_id}/check-suggestions", response_model=CheckSuggestionPage)
    def check_suggestions(task_id: ScopeId, listing_id: ScopeId, request: Request,
            limit: Annotated[int, Query(ge=1, le=50)] = 20,
            before_id: Annotated[int | None, Query(gt=0, le=2**63-1)] = None):
        return CheckSuggestions(request.app.state.conversation_service.config).page(task_id, listing_id, limit=limit, before_id=before_id)

    @app.post("/api/tasks/{task_id}/listings/{listing_id}/check-suggestions/{suggestion_id}/accept", response_model=CheckSuggestionAcceptance)
    def accept_check_suggestion(task_id: ScopeId, listing_id: ScopeId, suggestion_id: ScopeId, body: CheckSuggestionConfirm, request: Request):
        return CheckSuggestions(request.app.state.conversation_service.config).accept(task_id, listing_id, suggestion_id)

    @app.get("/api/tasks/{task_id}/listings/{listing_id}/checks", response_model=CandidateCheckPage)
    def checks(task_id: ScopeId, listing_id: ScopeId, request: Request,
               limit: Annotated[int, Query(ge=1, le=50)] = 20,
               before_id: Annotated[int | None, Query(gt=0, le=2**63-1)] = None):
        return CandidateChecks(request.app.state.conversation_service.config).page(task_id, listing_id, limit=limit, before_id=before_id)

    @app.post("/api/tasks/{task_id}/listings/{listing_id}/checks", response_model=CandidateCheck, status_code=201)
    def create_check(task_id: ScopeId, listing_id: ScopeId, body: CheckCreateInput, request: Request):
        return CandidateChecks(request.app.state.conversation_service.config).create(task_id, listing_id, **body.model_dump())

    @app.patch("/api/tasks/{task_id}/listings/{listing_id}/checks/{check_id}", response_model=CandidateCheck)
    def change_check(task_id: ScopeId, listing_id: ScopeId, check_id: ScopeId, body: CheckChangeInput, request: Request):
        return CandidateChecks(request.app.state.conversation_service.config).change(task_id, listing_id, check_id, **body.model_dump())

    @app.exception_handler(ConversationStoreError)
    async def domain_error(request, exc):
        if isinstance(exc, RecordNotFoundError):
            status, code = 404, "not_found"
        elif isinstance(exc, OperationConflictError):
            status, code = 409, "operation_conflict"
        elif isinstance(exc, (ActionDecisionConflictError, OperationStateError)):
            status, code = 409, "decision_conflict"
        else:
            status, code = 400, "invalid_scope"
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": str(exc)}})

    @app.post("/api/tasks", status_code=202, response_model=TaskCreationResponse)
    def create_task(body: MessageInput, request: Request,
                    config: Annotated[AppConfig, Depends(get_config)]):
        service = ConversationService(config, store=request.app.state.conversation_service.store)
        result = service.create_task(body.message)
        request.app.state.coordinator.start(result.operation.id)
        return result

    @app.patch("/api/tasks/{task_id}", response_model=TaskRecord)
    def rename_task(task_id: int, body: RenameInput, request: Request):
        return request.app.state.conversation_service.rename_task(task_id, body.title)

    @app.get("/api/tasks/{task_id}/messages", response_model=MessagePage)
    def messages(task_id: int, request: Request,
                 limit: Annotated[int, Query(ge=1, le=100)] = 50,
                 before_id: Annotated[int | None, Query(gt=0)] = None):
        return request.app.state.conversation_service.get_messages(task_id, limit, before_id)

    @app.post("/api/tasks/{task_id}/messages", status_code=202, response_model=MessageCreationResponse)
    def send_message(task_id: int, body: FollowupInput, request: Request):
        result = request.app.state.conversation_service.send_message(task_id, body.message,
            body.candidate_statement.model_dump() if body.candidate_statement else None)
        request.app.state.coordinator.start(result.operation.id)
        return result

    @app.patch("/api/tasks/{task_id}/statements/{statement_id}")
    def change_statement(task_id: Annotated[int, ApiPath(gt=0, le=2**63-1)], statement_id: Annotated[int, ApiPath(gt=0, le=2**63-1)], body: StatementChangeInput, request: Request):
        return request.app.state.conversation_service.change_statement(task_id, statement_id, **body.model_dump())

    @app.get("/api/tasks/{task_id}/action-requests", response_model=ActionRequestPage)
    def action_requests(task_id: int, request: Request,
                        limit: Annotated[int, Query(ge=1, le=100)] = 50,
                        before_id: Annotated[int | None, Query(gt=0)] = None):
        return request.app.state.conversation_service.get_action_requests(task_id, limit, before_id)

    @app.get("/api/operations/{operation_id}", response_model=OperationDetail)
    def operation(operation_id: int, request: Request):
        return request.app.state.conversation_service.get_operation(operation_id)

    @app.post("/api/operations/{operation_id}/cancel", response_model=OperationDetail)
    def cancel(operation_id: int, request: Request):
        return request.app.state.coordinator.cancel(operation_id)

    @app.get("/api/operations/{operation_id}/events")
    def events(operation_id: int, request: Request,
               after: Annotated[int, Query(ge=0)] = 0,
               last_event_id: Annotated[int | None, Header(ge=0)] = None):
        store = request.app.state.conversation_service.store
        store.get_operation(operation_id)
        return StreamingResponse(
            stream_operation_events(store, operation_id, max(after, last_event_id or 0)),
            media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/action-requests/{request_id}/approve", response_model=ActionDecisionResponse)
    def approve(request_id: int, body: DecisionInput, request: Request):
        return request.app.state.conversation_service.approve_action(body.task_id, request_id)

    @app.post("/api/action-requests/{request_id}/reject", response_model=ActionDecisionResponse)
    def reject(request_id: int, body: DecisionInput, request: Request):
        return request.app.state.conversation_service.reject_action(body.task_id, request_id)
