"""User conclusions preserve provenance and expire; they never certify facts."""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.assessment import evidence_state, input_refs
from shopping_agent.check_context import check_signature
from shopping_agent.check_reviews import CheckReviews
from shopping_agent.conversation_store import InvalidActionRequestError, OperationConflictError, RecordNotFoundError
from shopping_agent.db import connect, initialize, attach_run_to_task
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.codex_runtime import AnswerResult
from shopping_agent.web.app import create_app
from test_candidate_checks import fixture, create
from test_web_preference_updates import ScriptedRunner, run_turn


def draft(store, task, item, statement, **updates):
    page = store.page(task, 2, item["id"])
    return dict(expected_review_id=page["latest_review_id"], expected_check_revision_id=page["check_revision_id"],
        expected_basis_token=page["basis_token"], action="record", outcome="answered", summary="用户已记录卖家说法，仍需核对维修记录。",
        sources=[dict(statement_id=statement, revision_id=0)]) | updates


def setup(fixture):
    service, task, statement, checks = fixture
    return service, task, statement, checks, create(checks, task), CheckReviews(service.config)


def test_append_retry_withdraw_and_history_preserve_facts(fixture):
    service, task, statement, _, item, store = setup(fixture)
    with connect(service.config.database_path) as conn:
        facts, guard = evidence_state(conn, task), check_signature(conn, task)
    request = draft(store, task, item, statement)
    one = store.change(task, 2, item["id"], **request)
    assert one["status"] == "current" and not one["independently_verified"]
    assert one == store.change(task, 2, item["id"], **request)
    initialize(service.config.database_path)
    with connect(service.config.database_path) as conn:
        assert evidence_state(conn, task) == facts and check_signature(conn, task) != guard
    two = store.change(task, 2, item["id"], **draft(store, task, item, statement, outcome="uncertain", summary="缺少可核对的维修记录"))
    with pytest.raises(OperationConflictError):
        store.change(task, 2, item["id"], **request)
    page = store.page(task, 2, item["id"])
    withdrawn = store.change(task, 2, item["id"], expected_review_id=two["id"], expected_check_revision_id=0,
        expected_basis_token=page["basis_token"], action="withdraw")
    assert withdrawn["status"] == "withdrawn" and not withdrawn["sources"]
    rows = store.page(task, 2, item["id"])["items"]
    assert len(rows) == 3 and rows[-1]["summary"] == request["summary"] and rows[-1]["status"] == "superseded"


@pytest.mark.parametrize("mutation", ["withdraw", "rebind", "retag", "roundtrip", "own_evidence", "requirements", "check_state"])
def test_input_changes_invalidate_review_without_rewriting_history(fixture, mutation):
    service, task, statement, checks, item, store = setup(fixture)
    request = draft(store, task, item, statement)
    recorded = store.change(task, 2, item["id"], **request)
    if mutation == "withdraw":
        service.change_statement(task, statement, action="withdraw", expected_revision_id=0)
    elif mutation in {"rebind", "retag", "roundtrip"}:
        rebound = service.change_statement(task, statement, action="rebind", expected_revision_id=0,
            listing_id=2 if mutation == "retag" else 3, kind="user_observation" if mutation == "retag" else "seller_reply")
        if mutation == "roundtrip":
            service.change_statement(task, statement, action="rebind", expected_revision_id=rebound.revision_id, listing_id=2, kind="seller_reply")
    elif mutation == "check_state":
        changed = checks.change(task, 2, item["id"], expected_revision_id=0, state="dismissed")
        checks.change(task, 2, item["id"], expected_revision_id=changed["revision_id"], state="pending")
    else:
        with connect(service.config.database_path) as conn:
            if mutation == "own_evidence":
                conn.execute("UPDATE listing_snapshots SET price_text='3999' WHERE listing_id=2")
            else:
                from shopping_agent.db import add_task_preference_revision
                add_task_preference_revision(conn, task, "新要求", "预算3000", "[]", "[]")
    page = store.page(task, 2, item["id"])
    assert page["current_review"]["id"] == recorded["id"] and page["current_review"]["status"] == "needs_recheck"
    assert page["current_review"]["summary"] == recorded["summary"]
    assert store.change(task, 2, item["id"], **request)["status"] == "needs_recheck"  # Exact old retry never revives it.
    snapshot = OperationCoordinator(service, ScriptedRunner())._build_request(task)
    review = snapshot.follow_up_context["items"][0]["user_review"]
    assert review == dict(id=recorded["id"], status="needs_recheck", independently_verified=False)


def test_other_candidate_change_does_not_expire_review_and_current_refs_are_originals(fixture):
    service, task, statement, _, item, store = setup(fixture)
    store.change(task, 2, item["id"], **draft(store, task, item, statement))
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE listing_snapshots SET price_text='3999' WHERE listing_id=3")
    assert store.page(task, 2, item["id"])["current_review"]["status"] == "current"
    snapshot = OperationCoordinator(service, ScriptedRunner())._build_request(task)
    review = snapshot.follow_up_context["items"][0]["user_review"]
    assert review["outcome"] == "answered" and len(review["source_refs"]) == 1
    assert input_refs(snapshot)[review["source_refs"][0]]["data"]["statement_id"] == statement


def test_form_basis_and_source_versions_cannot_silently_advance(fixture):
    service, task, statement, _, item, store = setup(fixture)
    request = draft(store, task, item, statement)
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE listing_snapshots SET price_text='3999' WHERE listing_id=2")
    with pytest.raises(OperationConflictError):
        store.change(task, 2, item["id"], **request)
    request = draft(store, task, item, statement)
    request["sources"][0]["revision_id"] = 999
    with pytest.raises(OperationConflictError):
        store.change(task, 2, item["id"], **request)
    assert store.page(task, 2, item["id"])["total_count"] == 0


def test_conflict_requires_distinct_sources_and_keeps_their_types(fixture):
    service, task, statement, _, item, store = setup(fixture)
    with pytest.raises(InvalidActionRequestError):
        store.change(task, 2, item["id"], **draft(store, task, item, statement, outcome="conflict"))
    added = service.send_message(task, "我看到维修单记载换屏", dict(listing_id=2, kind="user_observation"))
    service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
    sources = [dict(statement_id=i, revision_id=0) for i in (statement, added.message.candidate_statement.id)]
    recorded = store.change(task, 2, item["id"], **draft(store, task, item, statement, outcome="conflict", sources=sources))
    assert {s["kind"] for s in recorded["sources"]} == {"seller_reply", "user_observation"}
    assert all(s["current"] for s in recorded["sources"])


def test_other_task_and_other_listing_sources_are_rejected(fixture):
    service, task, statement, _, item, store = setup(fixture)
    other = service.create_task("另一个任务")
    service.store.transition_operation(other.operation.id, {"queued"}, "completed")
    with connect(service.config.database_path) as conn:
        run = conn.execute("SELECT run_id FROM task_runs WHERE task_id=?", (task,)).fetchone()[0]
        attach_run_to_task(conn, other.task.id, run)
    added = service.send_message(other.task.id, "其他任务私有说法", dict(listing_id=2, kind="seller_reply"))
    service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
    with pytest.raises(OperationConflictError):
        store.change(task, 2, item["id"], **draft(store, task, item, added.message.candidate_statement.id))
    with pytest.raises(RecordNotFoundError):
        store.page(task, 3, item["id"])


def test_review_changes_block_inflight_plain_answer(fixture):
    service, task, statement, _, item, store = setup(fixture)
    def record(snapshot):
        store.change(task, 2, item["id"], **draft(store, task, item, statement))
        return AnswerResult(type="answer", content="旧记录回答", candidate_ids=[])
    result = run_turn(service, task, ScriptedRunner(record))
    assert result.state == "failed" and result.error_code == "review_inputs_changed"


def test_review_becoming_stale_blocks_inflight_plain_answer(fixture):
    service, task, statement, _, item, store = setup(fixture)
    store.change(task, 2, item["id"], **draft(store, task, item, statement))
    def mutate(snapshot):
        assert snapshot.follow_up_context["items"][0]["user_review"]["status"] == "current"
        with connect(service.config.database_path) as conn:
            conn.execute("UPDATE listing_snapshots SET price_text='9999' WHERE listing_id=2")
        return AnswerResult(type="answer", content="旧记录回答", candidate_ids=[])
    result = run_turn(service, task, ScriptedRunner(mutate))
    assert result.state == "failed" and result.error_code == "review_inputs_changed"


def test_older_current_source_does_not_bypass_bounded_model_input(fixture):
    service, task, statement, _, item, store = setup(fixture)
    for _ in range(20):
        added = service.send_message(task, "另一个新的补充", dict(listing_id=2, kind="seller_reply"))
        service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
    store.change(task, 2, item["id"], **draft(store, task, item, statement))
    snapshot = OperationCoordinator(service, ScriptedRunner())._build_request(task)
    review = snapshot.follow_up_context["items"][0]["user_review"]
    assert review["status"] == "current" and review["source_refs"] == [] and review["unavailable_source_count"] == 1


def test_reviews_page_is_bounded_and_retains_current_on_older_pages(fixture):
    service, task, statement, _, item, store = setup(fixture)
    for i in range(22):
        store.change(task, 2, item["id"], **draft(store, task, item, statement, summary=f"记录{i}"))
    page = store.page(task, 2, item["id"])
    assert len(page["items"]) == 20 and page["total_count"] == 22 and page["has_more"]
    older = store.page(task, 2, item["id"], before_id=page["next_before_id"])
    assert len(older["items"]) == 2 and older["current_review"]["id"] == page["current_review"]["id"]


def test_api_strict_fields_scope_and_persisted_result(fixture, tmp_path):
    service, task, statement, _, item, store = setup(fixture)
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'database_path = "{service.config.database_path.as_posix()}"\n', encoding="utf-8")
    app = create_app(config_path, tmp_path / "settings.json")
    async def check():
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                path = f"/api/tasks/{task}/listings/2/checks/{item['id']}/reviews"
                request = draft(store, task, item, statement)
                assert (await client.post(path, json=request | {"expected_review_id": True})).status_code == 422
                assert (await client.post(path, json=request | {"verified": True})).status_code == 422
                result = await client.post(path, json=request)
                assert result.status_code == 201 and not result.json()["independently_verified"]
                assert (await client.get(path)).json()["current_review"]["id"] == result.json()["id"]
    asyncio.run(check())
