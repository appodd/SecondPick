from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import (
    ActionDecisionConflictError,
    ActionRequestInput,
    ActionRequestRecord,
    InvalidActionRequestError,
    OperationConflictError,
    RecordNotFoundError,
)
from shopping_agent.db import connect, fetch_research_task
from shopping_agent.web.schemas import MessageDto, OperationDetail


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        database_path=tmp_path / "conversation-service.sqlite",
        default_city="Shanghai",
    )


def _service_with_task(config: AppConfig) -> tuple[ConversationService, int]:
    service = ConversationService(config)
    created = service.create_task("Find a reliable laptop")
    service.store.transition_operation(created.operation.id, {"queued"}, "completed")
    return service, created.task.id


def _pending_request(
    service: ConversationService,
    task_id: int,
    message: str,
) -> ActionRequestRecord:
    created = service.send_message(task_id, message)
    service.store.transition_operation(created.operation.id, {"queued"}, "running")
    return service.store.complete_with_action_request(
        created.operation.id,
        ActionRequestInput(
            summary=f"Request for {message}",
            risk="Would start a search",
            listing_ids=[],
            actions=["search"],
        ),
    )


def test_create_task_uses_local_title_and_returns_operation(config: AppConfig) -> None:
    service = ConversationService(config)

    result = service.create_task("Find a Shanghai ThinkPad X1 Carbon, budget 5000")

    assert result.task.title == "Find a Shanghai ThinkPad X1 Carbon, budget 5000"
    # Merely mentioning a city does not make the system default a trading condition.
    assert result.task.city == ""
    assert result.task.original_goal == result.message.content
    assert result.message.role == "user"
    assert result.message.candidate_ids == []
    assert result.operation.state == "queued"


def test_initial_title_is_trimmed_to_60_unicode_code_points(config: AppConfig) -> None:
    message = "研" * 61 + " tail"

    result = ConversationService(config).create_task(message)

    assert result.task.title == "研" * 60
    assert len(result.task.title) == 60
    assert result.message.content == message


@pytest.mark.parametrize("method", ["create_task", "send_message"])
def test_blank_messages_are_rejected(config: AppConfig, method: str) -> None:
    service, task_id = _service_with_task(config)

    with pytest.raises(ValueError, match="must not be blank"):
        if method == "create_task":
            service.create_task(" \n\t ")
        else:
            service.send_message(task_id, " \n\t ")


def test_simultaneous_messages_return_operation_conflict(config: AppConfig) -> None:
    service, task_id = _service_with_task(config)
    barrier = threading.Barrier(2)

    def send(message: str) -> str:
        barrier.wait()
        try:
            service.send_message(task_id, message)
        except OperationConflictError:
            return "conflict"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(send, ["first", "second"]))

    assert sorted(outcomes) == ["accepted", "conflict"]


def test_rename_accepts_only_title_and_preserves_original_goal(config: AppConfig) -> None:
    service, task_id = _service_with_task(config)

    renamed = service.rename_task(task_id, {"title": "Renamed research"})

    assert renamed.title == "Renamed research"
    assert renamed.original_goal == "Find a reliable laptop"
    with pytest.raises(ValueError, match="Only title"):
        service.rename_task(task_id, {"title": "Changed", "goal": "Replacement"})


def test_messages_are_returned_in_cursor_pages_with_candidate_ids(
    config: AppConfig,
) -> None:
    service, task_id = _service_with_task(config)
    for content in ("second", "third", "fourth"):
        created = service.send_message(task_id, content)
        service.store.transition_operation(created.operation.id, {"queued"}, "completed")

    newest = service.get_messages(task_id, limit=2, before_id=None)
    older = service.get_messages(task_id, limit=2, before_id=newest.next_before_id)

    assert [message.content for message in newest.items] == ["third", "fourth"]
    assert all(message.candidate_ids == [] for message in newest.items)
    assert newest.has_more is True
    assert [message.content for message in older.items] == [
        "Find a reliable laptop",
        "second",
    ]
    assert older.has_more is False


def test_action_request_history_includes_all_states_and_is_paginated(
    config: AppConfig,
) -> None:
    service, task_id = _service_with_task(config)
    approved = _pending_request(service, task_id, "approved")
    service.approve_action(task_id, approved.id)
    rejected = _pending_request(service, task_id, "rejected")
    service.reject_action(task_id, rejected.id)
    pending = _pending_request(service, task_id, "pending")

    newest = service.get_action_requests(task_id, limit=2, before_id=None)
    older = service.get_action_requests(
        task_id,
        limit=2,
        before_id=newest.next_before_id,
    )

    assert [item.state for item in newest.items] == ["rejected", "pending"]
    assert newest.has_more is True
    assert [item.state for item in older.items] == ["approved"]
    assert {approved.id, rejected.id, pending.id} == {
        *(item.id for item in newest.items),
        *(item.id for item in older.items),
    }


def test_action_decisions_enforce_task_ownership_and_reversal_rules(
    config: AppConfig,
) -> None:
    service, owner_task_id = _service_with_task(config)
    request = _pending_request(service, owner_task_id, "owner")
    service.store.transition_operation(
        service.create_task("Other task").operation.id,
        {"queued"},
        "completed",
    )
    other_task_id = service.create_task("Third task").task.id

    with pytest.raises(InvalidActionRequestError, match="does not belong"):
        service.approve_action(other_task_id, request.id)

    decided = service.approve_action(owner_task_id, request.id)
    repeated = service.approve_action(owner_task_id, request.id)

    assert decided.action_request.state == "approved"
    assert repeated == decided
    with pytest.raises(ActionDecisionConflictError):
        service.reject_action(owner_task_id, request.id)


def test_operation_detail_includes_last_event_and_pending_action(config: AppConfig) -> None:
    service, task_id = _service_with_task(config)
    request = _pending_request(service, task_id, "needs confirmation")

    detail = service.get_operation(request.operation_id)

    assert detail.operation.state == "waiting_confirmation"
    assert detail.last_event_id > 0
    assert detail.action_request is not None
    assert detail.action_request.id == request.id


def test_missing_records_raise_typed_not_found(config: AppConfig) -> None:
    service = ConversationService(config)

    with pytest.raises(RecordNotFoundError):
        service.get_messages(999, limit=20, before_id=None)
    with pytest.raises(RecordNotFoundError):
        service.get_operation(999)


def test_web_dtos_are_strict_and_forbid_unknown_fields() -> None:
    payload = {
        "id": 1,
        "task_id": 2,
        "role": "user",
        "content": "hello",
        "operation_id": 3,
        "candidate_ids": [],
        "created_at": "2026-09-28T00:00:00+00:00",
    }

    assert MessageDto.model_validate(payload).candidate_ids == []
    with pytest.raises(ValidationError):
        MessageDto.model_validate({**payload, "unexpected": True})
    with pytest.raises(ValidationError):
        OperationDetail.model_validate(
            {
                "operation": {
                    "id": "1",
                    "task_id": 2,
                    "state": "queued",
                    "error_code": None,
                    "error_detail": None,
                },
                "last_event_id": 1,
                "action_request": None,
            }
        )


def test_rename_updates_only_title_column(config: AppConfig) -> None:
    service, task_id = _service_with_task(config)
    service.rename_task(task_id, "New title")

    with connect(config.database_path) as conn:
        row = fetch_research_task(conn, task_id)

    assert row is not None
    assert row["title"] == "New title"
    assert row["goal"] == "Find a reliable laptop"
