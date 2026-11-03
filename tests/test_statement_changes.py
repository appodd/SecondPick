"""Corrections use real persistence; scripted judgments do not prove model quality."""
import asyncio
import copy

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.assessment import evidence_state, input_refs
from shopping_agent.candidate_context import build_candidate_evidence
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import InvalidActionRequestError, OperationConflictError, RecordNotFoundError
from shopping_agent.codex_runtime import ActionRequestResult
from shopping_agent.db import connect, initialize
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.web.app import create_app
from test_bound_candidate_statements import bound_turn, bound_assessment
from test_history_review import ReviewRunner, saved
from test_structured_assessments import seed_phones
from test_web_preference_updates import ready_service, run_turn, ScriptedRunner


@pytest.fixture
def seeded(tmp_path):
    service, task = ready_service(tmp_path)
    seed_phones(service.config, task)
    assert bound_turn(service, task, ReviewRunner(bound_assessment), "商品#2卖家称全原无修", listing_id=2).state == "completed"
    statement = next(m.candidate_statement for m in service.get_messages(task).items if m.candidate_statement)
    return service, task, statement.id


def change(service, task, statement, action="withdraw", revision=0, **kwargs):
    return service.change_statement(task, statement, action=action, expected_revision_id=revision, **kwargs)


def state(service, task):
    with connect(service.config.database_path) as conn:
        return evidence_state(conn, task)


def test_withdraw_retains_original_and_invalidates_only_its_candidate(seeded):
    service, task, statement = seeded
    before = copy.deepcopy(saved(service, task))
    previous = state(service, task)
    result = change(service, task, statement)
    assert result.status == "withdrawn" and result.revision_id > 0
    after = state(service, task)
    assert previous[0] != after[0]
    assert {i for i in previous[1] if previous[1][i] != after[1][i]} == {"2"}
    restored = ConversationService(service.config)
    message = next(m for m in restored.get_messages(task).items if m.candidate_statement)
    assert message.content == "商品#2卖家称全原无修" and message.candidate_statement.status == "withdrawn"
    assert build_candidate_evidence(service.config, task_id=task, listing_ids=[2])["candidates"][0]["user_statements"] == []
    assert saved(service, task)["assessment_batches"][0]["result"] == before["assessment_batches"][0]["result"]
    assert saved(service, task)["assessment_batches"][0]["candidate_stale"]["2"]
    with connect(service.config.database_path) as conn:
        assert conn.execute("SELECT listing_id FROM candidate_statements WHERE id=?", (statement,)).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM candidate_statement_changes").fetchone()[0] == 1


def test_rebind_changes_two_candidates_and_preserves_others(seeded):
    service, task, statement = seeded
    previous = state(service, task)
    row = change(service, task, statement, "rebind", listing_id=3, kind="user_observation")
    assert row.original_listing_id == 2 and row.listing_id == 3
    after = state(service, task)
    assert {i for i in previous[1] if previous[1][i] != after[1][i]} == {"2", "3"}
    evidence = build_candidate_evidence(service.config, task_id=task, listing_ids=[2, 3])["candidates"]
    by_id = {e["listing_id"]: e for e in evidence}
    assert not by_id[2]["user_statements"]
    assert by_id[3]["user_statements"][0]["kind"] == "user_observation"
    assert by_id[3]["user_statements"][0]["statement_text"] == "商品#2卖家称全原无修"
    request = OperationCoordinator(service, ReviewRunner())._build_request(task)
    binding = next(m.candidate_statement for m in request.messages if m.candidate_statement)
    assert binding["listing_id"] == 3
    refs = {r: d for r, d in input_refs(request).items() if r.startswith("statement:")}
    assert refs and {d["listing_id"] for d in refs.values()} == {3}


def test_correction_round_trip_has_new_signature_and_audit_rows(seeded):
    service, task, statement = seeded
    original = state(service, task)
    row = change(service, task, statement, "rebind", listing_id=3, kind="seller_reply")
    change(service, task, statement, "rebind", row.revision_id, listing_id=2, kind="seller_reply")
    assert original[0] != state(service, task)[0]
    with connect(service.config.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_statement_changes").fetchone()[0] == 2


def test_duplicate_change_is_idempotent_and_stale_change_cannot_overwrite(seeded):
    service, task, statement = seeded
    row = change(service, task, statement, "rebind", listing_id=3, kind="seller_reply")
    assert change(service, task, statement, "rebind", listing_id=3, kind="seller_reply") == row
    with pytest.raises(OperationConflictError): change(service, task, statement)
    withdrawn = change(service, task, statement, revision=row.revision_id)
    assert change(service, task, statement, revision=row.revision_id) == withdrawn
    assert change(service, task, statement, revision=withdrawn.revision_id) == withdrawn
    with pytest.raises(OperationConflictError):
        change(service, task, statement, "rebind", withdrawn.revision_id, listing_id=2, kind="seller_reply")


@pytest.mark.parametrize("kwargs", [dict(listing_id=999), dict(listing_id=2**80), dict(listing_id=True), dict(kind="invalid")])
def test_invalid_correction_has_no_partial_event(seeded, kwargs):
    service, task, statement = seeded
    args = dict(listing_id=3, kind="seller_reply") | kwargs
    before = state(service, task)
    with pytest.raises(InvalidActionRequestError): change(service, task, statement, "rebind", **args)
    assert state(service, task) == before


def test_foreign_task_cannot_read_or_change_statement(seeded):
    service, task, statement = seeded
    other = service.create_task("其他任务")
    with pytest.raises(RecordNotFoundError): change(service, other.task.id, statement)
    assert not next(m for m in service.get_messages(task).items if m.candidate_statement).candidate_statement.status == "withdrawn"


def test_withdraw_during_inference_prevents_late_publish(seeded):
    service, task, statement = seeded
    def hook(request):
        if request.phase == "review_batch": change(service, task, statement)
    # Requirement change forces fresh assessments rather than cache reuse.
    runner = ReviewRunner(hook, update=True)
    record = run_turn(service, task, runner)
    assert record.state == "failed" and record.error_code == "review_inputs_changed"


def test_correction_cannot_change_pending_collection_request_inputs(seeded):
    service, task, statement = seeded
    record = run_turn(service, task, ScriptedRunner(ActionRequestResult(type="action_request", summary="抓详情",
        listing_ids=[2], actions=["detail"], risk="平台访问")), "看看详情")
    assert record.state == "waiting_confirmation"
    before = state(service, task)
    with pytest.raises(OperationConflictError): change(service, task, statement)
    assert state(service, task) == before


def test_withdraw_reassessment_reuses_other_candidates_and_removes_refs(seeded):
    service, task, statement = seeded
    change(service, task, statement)
    runner = ReviewRunner()
    assert run_turn(service, task, runner, "重评历史候选").state == "completed"
    assert [r.allowed_listing_ids for r in runner.requests if r.phase == "review_batch"] == [frozenset({2})]
    request = next(r for r in runner.requests if r.phase == "review_batch")
    assert not any(ref.startswith("statement:") for ref in input_refs(request))
    assert next(m.candidate_statement for m in request.messages if m.candidate_statement)["status"] == "withdrawn"


def test_api_scope_and_strict_input_and_restart_migration(seeded, tmp_path):
    service, task, statement = seeded
    initialize(service.config.database_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'database_path = "{service.config.database_path.as_posix()}"\n', encoding="utf-8")
    app = create_app(config_path, tmp_path / "settings.json")
    app.state.codex_runtime = ReviewRunner()
    async def check():
      async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            path = f"/api/tasks/{task}/statements/{statement}"
            assert (await client.patch(path, json=dict(action="withdraw", expected_revision_id=True))).status_code == 422
            assert (await client.patch(path, json=dict(action="withdraw", expected_revision_id=0, extra="bad"))).status_code == 422
            assert (await client.patch(path, json=dict(action="withdraw", expected_revision_id=0))).json()["status"] == "withdrawn"
            assert (await client.patch(f"/api/tasks/{task}/statements/{2**80}", json=dict(action="withdraw", expected_revision_id=0))).status_code == 422
    asyncio.run(check())
