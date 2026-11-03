"""Checklist persistence does not certify evidence or change model judgments."""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.assessment import evidence_state
from shopping_agent.candidate_checks import CandidateChecks
from shopping_agent.conversation_store import InvalidActionRequestError, OperationConflictError, RecordNotFoundError
from shopping_agent.db import connect, initialize, attach_run_to_task
from shopping_agent.web.app import create_app
from test_structured_assessments import seed_phones
from test_web_preference_updates import ready_service


@pytest.fixture
def fixture(tmp_path):
    service, task = ready_service(tmp_path)
    seed_phones(service.config, task)
    added = service.send_message(task, "卖家称原装，尚待核实", dict(listing_id=2, kind="seller_reply"))
    service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
    return service, task, added.message.candidate_statement.id, CandidateChecks(service.config)


def create(store, task, **kwargs):
    return store.create(task, 2, question="屏幕是否换过？", request_key="request-0001", **kwargs)


def link(store, task, item, statement, source_revision=0):
    return store.change(task, 2, item["id"], expected_revision_id=item["revision_id"], state="evidence_linked",
                        statement_id=statement, statement_revision_id=source_revision, note="已记录，仍待核实")


def test_create_retry_and_scope_preserve_original_question(fixture):
    service, task, statement, store = fixture
    item = create(store, task)
    assert create(store, task) == item
    with pytest.raises(OperationConflictError):
        store.create(task, 3, question="其他问题", request_key="request-0001")
    with pytest.raises(RecordNotFoundError):
        store.create(task, 999, question="问题", request_key="request-0002")
    assert store.page(task, 2)["total_count"] == 1


def test_link_dismiss_reopen_are_versioned_and_do_not_change_facts(fixture):
    service, task, statement, store = fixture
    with connect(service.config.database_path) as conn:
        before = evidence_state(conn, task)
    original = create(store, task)
    linked = link(store, task, original, statement)
    assert linked["effective_state"] == "evidence_linked" and linked["evidence_current"]
    assert link(store, task, original, statement) == linked  # Same last request retry.
    dismissed = store.change(task, 2, original["id"], expected_revision_id=linked["revision_id"], state="dismissed")
    with pytest.raises(OperationConflictError):
        link(store, task, original, statement)
    reopened = store.change(task, 2, original["id"], expected_revision_id=dismissed["revision_id"], state="pending")
    assert reopened["effective_state"] == "pending" and reopened["statement_id"] is None
    initialize(service.config.database_path)
    with connect(service.config.database_path) as conn:
        assert evidence_state(conn, task) == before
        assert conn.execute("SELECT question FROM candidate_checks WHERE id=?", (original["id"],)).fetchone()[0] == original["question"]
        assert conn.execute("SELECT COUNT(*) FROM candidate_check_changes").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM task_preference_revisions WHERE task_id=?", (task,)).fetchone()[0] == 0
    assert store.page(task, 2)["items"][0] == reopened


@pytest.mark.parametrize("mutation", ["withdraw", "rebind", "retag", "round_trip"])
def test_statement_changes_make_link_require_explicit_rechecking(fixture, mutation):
    service, task, statement, store = fixture
    linked = link(store, task, create(store, task), statement)
    if mutation == "withdraw":
        source = service.change_statement(task, statement, action="withdraw", expected_revision_id=0)
    else:
        source = service.change_statement(task, statement, action="rebind", expected_revision_id=0,
            listing_id=2 if mutation == "retag" else 3, kind="user_observation" if mutation == "retag" else "seller_reply")
        if mutation == "round_trip":
            source = service.change_statement(task, statement, action="rebind", expected_revision_id=source.revision_id,
                                               listing_id=2, kind="seller_reply")
    page = CandidateChecks(service.config).page(task, 2)
    current = page["items"][0]
    assert current["state"] == "evidence_linked" and current["effective_state"] == "pending" and current["needs_recheck"]
    assert page["counts"] == dict(pending=1, evidence_linked=0, dismissed=0)
    assert current["statement_text"] == "卖家称原装，尚待核实"  # Original record remains.
    with pytest.raises(OperationConflictError):
        store.change(task, 2, current["id"], expected_revision_id=current["revision_id"], state="evidence_linked",
                     statement_id=statement, statement_revision_id=0, note="different")
    if source.status == "active" and source.listing_id == 2:
        relinked = link(store, task, current, statement, source.revision_id)
        assert relinked["evidence_current"] and relinked["revision_id"] != linked["revision_id"]


def test_foreign_task_statement_cannot_be_linked_even_for_same_listing(fixture):
    service, task, statement, store = fixture
    other = service.create_task("另一次购买")
    service.store.transition_operation(other.operation.id, {"queued"}, "cancelled")
    with connect(service.config.database_path) as conn:
        run = conn.execute("SELECT run_id FROM task_runs WHERE task_id=? LIMIT 1", (task,)).fetchone()[0]
        attach_run_to_task(conn, other.task.id, run)
    added = service.send_message(other.task.id, "其他任务的原话", dict(listing_id=2, kind="seller_reply"))
    item = create(store, task)
    with pytest.raises(OperationConflictError):
        link(store, task, item, added.message.candidate_statement.id)
    with pytest.raises(RecordNotFoundError):
        store.change(other.task.id, 2, item["id"], state="dismissed", expected_revision_id=0)
    assert store.page(other.task.id, 2)["items"] == []


@pytest.mark.parametrize("change", [dict(expected_revision_id=True), dict(expected_revision_id=2**80),
                                   dict(state=[]), dict(state="verified"), dict(note=" ")])
def test_invalid_changes_leave_no_partial_events(fixture, change):
    service, task, statement, store = fixture
    item = create(store, task)
    with pytest.raises(InvalidActionRequestError):
        store.change(task, 2, item["id"], **(dict(expected_revision_id=0, state="dismissed") | change))
    assert store.page(task, 2)["items"] == [item]


def test_keyset_pages_keep_all_old_items_and_counts(fixture):
    service, task, statement, store = fixture
    for n in range(45):
        store.create(task, 2, question=f"问题 {n}", request_key=f"request-{n:04d}")
    first = store.page(task, 2)
    store.create(task, 2, question="翻页期间新增", request_key="request-later")
    second = store.page(task, 2, before_id=first["next_before_id"])
    third = store.page(task, 2, before_id=second["next_before_id"])
    assert len({i["id"] for page in (first, second, third) for i in page["items"]}) == 45
    assert third["total_count"] == 46 and not third["has_more"]
    assert first["available_statements"][0]["revision_id"] == 0


def test_available_supplements_are_bounded_without_losing_old_linkability(fixture):
    service, task, statement, store = fixture
    for n in range(22):
        added = service.send_message(task, f"后续原文 {n}", dict(listing_id=2, kind="user_observation"))
        service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
    page = store.page(task, 2)
    assert page["statement_count"] == 23 and page["statements_truncated"]
    assert len(page["available_statements"]) == 20
    assert statement not in {s["id"] for s in page["available_statements"]}
    assert link(store, task, create(store, task), statement)["evidence_current"]


def test_api_strict_inputs_scope_and_current_sources(fixture, tmp_path):
    service, task, statement, store = fixture
    path = tmp_path / "config.toml"
    path.write_text(f'database_path = "{service.config.database_path.as_posix()}"\n', encoding="utf-8")
    app = create_app(path, tmp_path / "settings.json")
    async def check():
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                url = f"/api/tasks/{task}/listings/2/checks"
                result = await client.post(url, json=dict(question="容量是否同机？", request_key="api-request-1"))
                assert result.status_code == 201
                item = result.json()
                assert (await client.patch(f"{url}/{item['id']}", json=dict(state="dismissed", expected_revision_id=True))).status_code == 422
                assert (await client.patch(f"{url}/{item['id']}", json=dict(state="verified", expected_revision_id=0))).status_code == 422
                assert (await client.post(url, json=dict(question="x", request_key="api-request-2", extra=True))).status_code == 422
                assert (await client.get(f"{url}?before_id={2**80}")).status_code == 422
                assert (await client.get(f"/api/tasks/{task}/listings/999/checks")).status_code == 404
                assert (await client.get(url)).json()["available_statements"][0]["id"] == statement
    asyncio.run(check())
