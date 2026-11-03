from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from shopping_agent.config import AppConfig
from shopping_agent.conversation_store import (
    ActionDecisionConflictError,
    ActionRequestInput,
    ConversationStore,
    InvalidActionRequestError,
    OperationConflictError,
    OperationStateError,
)
from shopping_agent.db import (
    add_listing_snapshot,
    attach_run_to_task,
    connect,
    create_search_run,
    upsert_listing,
)


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(database_path=tmp_path / "conversation.sqlite")


def _seed_task(tmp_path: Path) -> tuple[ConversationStore, int]:
    store = ConversationStore(_config(tmp_path))
    created = store.create_task_with_message(
        title="Find a laptop",
        message="Find a reliable laptop",
        city="Shanghai",
    )
    store.transition_operation(created.operation.id, {"queued"}, "completed")
    return store, created.task_id


def _start_running_operation(store: ConversationStore, task_id: int, message: str = "continue") -> int:
    created = store.create_message_operation(task_id, message)
    return store.transition_operation(created.operation.id, {"queued"}, "running").id


def _attach_listing(store: ConversationStore, task_id: int, suffix: str) -> int:
    with connect(store.database_path) as conn:
        run_id = create_search_run(conn, goal="laptop", city="Shanghai")
        attach_run_to_task(conn, task_id=task_id, run_id=run_id)
        listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url=f"https://example.test/listing/{suffix}",
        )
        add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id, title=suffix)
    return listing_id


def test_create_task_message_and_operation_is_atomic(tmp_path: Path) -> None:
    store = ConversationStore(_config(tmp_path))
    created = store.create_task_with_message(
        title="Find a ThinkPad in Shanghai",
        message="Find a ThinkPad X1 Carbon in Shanghai",
        city="Shanghai",
    )

    assert created.message.role == "user"
    assert created.operation.state == "queued"
    assert created.operation.user_message_id == created.message.id
    assert store.list_messages(created.task_id, limit=20, before_id=None).items == [
        created.message
    ]
    assert [event.event_type for event in store.list_events(created.operation.id, after_id=0)] == [
        "queued"
    ]


def test_only_one_mutable_operation_per_task(tmp_path: Path) -> None:
    store, task_id = _seed_task(tmp_path)
    store.create_message_operation(task_id, "first")

    with pytest.raises(OperationConflictError):
        store.create_message_operation(task_id, "second")


def test_message_insert_rolls_back_when_operation_insert_fails(tmp_path: Path) -> None:
    store, task_id = _seed_task(tmp_path)
    before = store.list_messages(task_id, limit=20, before_id=None).items
    with connect(store.database_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_operation_insert
            BEFORE INSERT ON operations
            BEGIN
                SELECT RAISE(ABORT, 'forced operation failure');
            END
            """
        )

    with pytest.raises(RuntimeError, match="forced operation failure"):
        store.create_message_operation(task_id, "must roll back")

    assert store.list_messages(task_id, limit=20, before_id=None).items == before


def test_messages_are_cursor_paginated_in_conversation_order(tmp_path: Path) -> None:
    store, task_id = _seed_task(tmp_path)
    for text in ("second", "third", "fourth"):
        created = store.create_message_operation(task_id, text)
        store.transition_operation(created.operation.id, {"queued"}, "completed")

    newest = store.list_messages(task_id, limit=2, before_id=None)
    older = store.list_messages(task_id, limit=2, before_id=newest.next_before_id)

    assert [message.content for message in newest.items] == ["third", "fourth"]
    assert newest.has_more is True
    assert [message.content for message in older.items] == ["Find a reliable laptop", "second"]
    assert older.has_more is False
    assert older.next_before_id is None


def test_events_replay_after_id_in_ascending_order(tmp_path: Path) -> None:
    store = ConversationStore(_config(tmp_path))
    operation = store.create_task_with_message("Laptop", "Find one", "Shanghai").operation
    first = store.append_event(operation.id, "stage", {"stage": "context"})
    second = store.append_event(operation.id, "stage", {"stage": "codex"})
    third = store.append_event(operation.id, "stage", {"stage": "persist"})

    replay = store.list_events(operation.id, after_id=first.id)

    assert replay == [second, third]
    assert replay[0].payload == {"stage": "codex"}


def test_complete_answer_round_trips_candidate_ids_atomically(tmp_path: Path) -> None:
    store, task_id = _seed_task(tmp_path)
    listing_ids = [_attach_listing(store, task_id, str(index)) for index in range(2)]
    operation_id = _start_running_operation(store, task_id)

    answer = store.complete_with_answer(operation_id, "Two candidates", listing_ids)

    assert answer.role == "assistant"
    assert answer.candidate_ids == listing_ids
    assert store.list_messages(task_id, 20, None).items[-1] == answer
    assert store.get_operation(operation_id).state == "completed"
    assert store.list_events(operation_id, 0)[-1].event_type == "completed"


def test_completion_rejects_non_running_operation_without_partial_output(tmp_path: Path) -> None:
    store, task_id = _seed_task(tmp_path)
    operation = store.create_message_operation(task_id, "answer this").operation

    with pytest.raises(OperationStateError):
        store.complete_with_answer(operation.id, "must not persist", [])

    assert all(
        message.content != "must not persist"
        for message in store.list_messages(task_id, 20, None).items
    )


@pytest.mark.parametrize("completion", ["answer", "action_request"])
def test_completion_rolls_back_when_terminal_event_insert_fails(
    tmp_path: Path,
    completion: str,
) -> None:
    store, task_id = _seed_task(tmp_path)
    listing_id = _attach_listing(store, task_id, "rollback")
    operation_id = _start_running_operation(store, task_id)
    messages_before = store.list_messages(task_id, 20, None).items
    with connect(store.database_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_terminal_event
            BEFORE INSERT ON operation_events
            WHEN NEW.event_type IN ('completed', 'waiting_confirmation')
            BEGIN
                SELECT RAISE(ABORT, 'forced event failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced event failure"):
        if completion == "answer":
            store.complete_with_answer(operation_id, "must roll back", [listing_id])
        else:
            store.complete_with_action_request(
                operation_id,
                ActionRequestInput("Inspect", "Open page", [listing_id], ["detail"]),
            )

    assert store.get_operation(operation_id).state == "running"
    assert store.list_messages(task_id, 20, None).items == messages_before
    assert store.list_action_requests(task_id, 20, None).items == []


def test_action_requests_validate_listing_scope_and_allowed_actions(tmp_path: Path) -> None:
    store, task_id = _seed_task(tmp_path)
    in_scope = _attach_listing(store, task_id, "in-scope")
    other_store_task = store.create_task_with_message("Other", "Other task", "Shanghai")
    store.transition_operation(other_store_task.operation.id, {"queued"}, "completed")
    out_of_scope = _attach_listing(store, other_store_task.task_id, "out-of-scope")
    operation_id = _start_running_operation(store, task_id)

    with pytest.raises(InvalidActionRequestError):
        store.complete_with_answer(operation_id, "Wrong task", [out_of_scope])
    with pytest.raises(InvalidActionRequestError):
        store.complete_with_action_request(
            operation_id,
            ActionRequestInput("Inspect", "Open pages", [in_scope, out_of_scope], ["detail"]),
        )
    with pytest.raises(InvalidActionRequestError):
        store.complete_with_action_request(
            operation_id,
            ActionRequestInput("Inspect", "Open pages", [in_scope], ["purchase"]),
        )

    assert store.get_operation(operation_id).state == "running"
    assert store.list_action_requests(task_id, 20, None).items == []


def test_action_requests_are_paginated_and_decisions_are_idempotent(tmp_path: Path) -> None:
    store, task_id = _seed_task(tmp_path)
    listing_id = _attach_listing(store, task_id, "candidate")
    requests = []
    for index, decision in enumerate(("approved", "rejected", None)):
        operation_id = _start_running_operation(store, task_id, f"request {index}")
        request = store.complete_with_action_request(
            operation_id,
            ActionRequestInput(
                summary=f"Request {index}",
                risk="Open a listing page",
                listing_ids=[listing_id],
                actions=["detail", "ocr"],
            ),
        )
        assert store.get_operation(operation_id).state == "waiting_confirmation"
        assert store.list_events(operation_id, 0)[-1].event_type == "waiting_confirmation"
        if decision is not None:
            request = store.decide_action_request(request.id, decision)
            assert store.decide_action_request(request.id, decision) == request
            assert store.get_operation(operation_id).state == "completed"
        requests.append(request)

    newest = store.list_action_requests(task_id, 2, None)
    older = store.list_action_requests(task_id, 2, newest.next_before_id)

    assert newest.items == requests[1:]
    assert newest.items[-1].listing_ids == [listing_id]
    assert newest.items[-1].actions == ["detail", "ocr"]
    assert newest.has_more is True
    assert older.items == requests[:1]
    assert {request.state for request in requests} == {"approved", "rejected", "pending"}
    with pytest.raises(ActionDecisionConflictError):
        store.decide_action_request(requests[0].id, "rejected")


def test_rename_changes_title_without_changing_original_goal(tmp_path: Path) -> None:
    store = ConversationStore(_config(tmp_path))
    created = store.create_task_with_message("Original title", "Immutable goal", "Shanghai")

    store.rename_task(created.task_id, "Renamed title")

    with connect(store.database_path) as conn:
        task = conn.execute(
            "SELECT title, goal FROM research_tasks WHERE id = ?", (created.task_id,)
        ).fetchone()
    assert dict(task) == {"title": "Renamed title", "goal": "Immutable goal"}
