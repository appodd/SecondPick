from __future__ import annotations

from shopping_agent.region_preference import region_preference

from collections.abc import Mapping
from dataclasses import asdict
from typing import Literal

from shopping_agent.config import AppConfig
from shopping_agent.conversation_store import (
    ActionRequestRecord,
    ConversationStore,
    InvalidActionRequestError,
    MessageRecord,
    OperationRecord,
    RecordNotFoundError,
)
from shopping_agent.tasks import build_task_summary
from shopping_agent.web.schemas import (
    ActionDecisionResponse,
    ActionRequestDto,
    ActionRequestPage,
    MessageCreationResponse,
    MessageDto,
    MessagePage,
    OperationDetail,
    OperationDto,
    TaskCreationResponse,
    TaskRecord,
)


TITLE_MAX_CODE_POINTS = 60


class ConversationService:
    def __init__(self, config: AppConfig, store: ConversationStore | None = None) -> None:
        self.config = config
        self.store = store or ConversationStore(config)

    def create_task(self, message: str) -> TaskCreationResponse:
        message = _validated_message(message)
        created = self.store.create_task_with_message(
            title=_title_from_message(message),
            message=message,
            city=region_preference(message)['city'] or '',
        )
        return TaskCreationResponse(
            task=self._get_task(created.task_id),
            message=_message_dto(created.message),
            operation=_operation_dto(created.operation),
        )

    def send_message(self, task_id: int, message: str, candidate_statement=None) -> MessageCreationResponse:
        created = self.store.create_message_operation(
            task_id,
            _validated_message(message),
            candidate_statement=candidate_statement,
        )
        return MessageCreationResponse(
            message=_message_dto(created.message),
            operation=_operation_dto(created.operation),
        )

    def change_statement(self, task_id, statement_id, **change):
        from shopping_agent.web.schemas import CandidateStatementBinding
        row = self.store.change_statement(task_id, statement_id, **change)
        return CandidateStatementBinding.model_validate({key: row[key] for key in
            ("id", "listing_id", "kind", "status", "revision_id", "original_listing_id")})

    def rename_task(
        self,
        task_id: int,
        title: str | Mapping[str, object],
    ) -> TaskRecord:
        if isinstance(title, Mapping):
            if set(title) != {"title"}:
                raise ValueError("Only title may be changed")
            title = title["title"]
        if not isinstance(title, str):
            raise ValueError("Task title must be a string")
        normalized = title.strip()
        if not normalized:
            raise ValueError("Task title must not be blank")
        self.store.rename_task(task_id, normalized[:TITLE_MAX_CODE_POINTS])
        return self._get_task(task_id)

    def get_messages(
        self,
        task_id: int,
        limit: int = 50,
        before_id: int | None = None,
    ) -> MessagePage:
        page = self.store.list_messages(task_id, limit, before_id)
        return MessagePage(
            items=[_message_dto(record) for record in page.items],
            has_more=page.has_more,
            next_before_id=page.next_before_id,
        )

    def get_action_requests(
        self,
        task_id: int,
        limit: int = 50,
        before_id: int | None = None,
    ) -> ActionRequestPage:
        page = self.store.list_action_requests(task_id, limit, before_id)
        return ActionRequestPage(
            items=[_action_request_dto(record) for record in page.items],
            has_more=page.has_more,
            next_before_id=page.next_before_id,
        )

    def get_operation(self, operation_id: int) -> OperationDetail:
        operation = self.store.get_operation(operation_id)
        events = self.store.list_events(operation_id, after_id=0)
        action_request = None
        if operation.state == "waiting_confirmation":
            action_request = self._find_operation_action_request(operation)
        return OperationDetail(
            operation=_operation_dto(operation),
            last_event_id=events[-1].id if events else 0,
            action_request=(
                _action_request_dto(action_request) if action_request is not None else None
            ),
        )

    def approve_action(self, task_id: int, request_id: int) -> ActionDecisionResponse:
        return self._decide_action(task_id, request_id, "approved")

    def reject_action(self, task_id: int, request_id: int) -> ActionDecisionResponse:
        return self._decide_action(task_id, request_id, "rejected")

    def _decide_action(
        self,
        task_id: int,
        request_id: int,
        decision: Literal["approved", "rejected"],
    ) -> ActionDecisionResponse:
        request = self._find_task_action_request(task_id, request_id)
        decided = self.store.decide_action_request(request.id, decision)
        operation = self.store.get_operation(decided.operation_id)
        return ActionDecisionResponse(
            action_request=_action_request_dto(decided),
            operation=_operation_dto(operation),
        )

    def _find_operation_action_request(
        self,
        operation: OperationRecord,
    ) -> ActionRequestRecord:
        before_id = None
        while True:
            page = self.store.list_action_requests(operation.task_id, 100, before_id)
            for request in page.items:
                if request.operation_id == operation.id:
                    return request
            if not page.has_more:
                raise RecordNotFoundError(
                    f"Action request for operation not found: {operation.id}"
                )
            before_id = page.next_before_id

    def _find_task_action_request(
        self,
        task_id: int,
        request_id: int,
    ) -> ActionRequestRecord:
        before_id = None
        while True:
            page = self.store.list_action_requests(task_id, 100, before_id)
            for request in page.items:
                if request.id == request_id:
                    return request
            if not page.has_more:
                raise InvalidActionRequestError(
                    f"Action request {request_id} does not belong to task {task_id}"
                )
            before_id = page.next_before_id

    def _get_task(self, task_id: int) -> TaskRecord:
        try:
            summary = build_task_summary(self.config, task_id)
        except ValueError as exc:
            raise RecordNotFoundError(f"Research task not found: {task_id}") from exc
        return TaskRecord.model_validate(summary["task"])


def _validated_message(message: str) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must not be blank")
    return message


def _title_from_message(message: str) -> str:
    return message.strip()[:TITLE_MAX_CODE_POINTS]


def _message_dto(record: MessageRecord) -> MessageDto:
    return MessageDto.model_validate(asdict(record))


def _operation_dto(record: OperationRecord) -> OperationDto:
    return OperationDto.model_validate(
        {
            "id": record.id,
            "task_id": record.task_id,
            "state": record.state,
            "error_code": record.error_code,
            "error_detail": record.error_detail,
        }
    )


def _action_request_dto(record: ActionRequestRecord) -> ActionRequestDto:
    return ActionRequestDto.model_validate(
        {
            "id": record.id,
            "task_id": record.task_id,
            "operation_id": record.operation_id,
            "summary": record.summary,
            "risk": record.risk,
            "listing_ids": record.listing_ids,
            "actions": record.actions,
            "state": record.state,
            "search_query": record.search_query,
            "max_pages": record.max_pages,
        }
    )
