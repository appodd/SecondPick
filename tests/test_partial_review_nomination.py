"""Partial reuse must reconsider non-nominees without rewriting old judgments."""
import json
import threading

import pytest

from shopping_agent.codex_runtime import AnswerResult, CodexRuntime, CodexTimeoutError
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import InvalidActionRequestError, OperationStateError
from shopping_agent.db import connect, initialize
from shopping_agent.history_review import NominationResult, nomination_context, comparison_context
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.tasks import update_task_preferences
from test_history_review import ReviewRunner, add_noise, saved
from test_operation_coordinator import wait_state
from test_structured_assessments import seed_phones, scripted_assessment
from test_web_preference_updates import ready_service, run_turn


@pytest.fixture
def partial(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    add_noise(service, task_id, 19)
    assert run_turn(service, task_id, ReviewRunner()).state == "completed"
    with connect(service.config.database_path) as conn:
        originals = [tuple(r) for r in conn.execute("SELECT id,result_json,input_json,dependencies_json FROM research_assessments ORDER BY id")]
        conn.execute("UPDATE listing_snapshots SET price_text='9999' WHERE listing_id=1")
    return service, task_id, originals


def entry(item):
    return dict(listing_id=item["listing_id"], assessment_id=item["assessment_id"], reason="依据保存判断重新提名", uncertainties=["实物与维修史待核实"])


def hook(request):
    if request.phase == "review_batch":
        answer = scripted_assessment(request)
        for candidate in answer.research.assessments:
            if candidate.listing_id == 1:
                candidate.judgments[0].status = "NOT_MET"
                candidate.conclusion = "not_met"
        answer.candidate_ids = [i for i in answer.candidate_ids if i != 1]
        return answer
    if request.phase == "nomination":
        items = request.review_context["assessments"]
        return NominationResult(type="nomination", candidates=[entry(a) for a in items if a["listing_id"] == 11])


def test_reuses_22_judgments_and_promotes_a_previously_omitted_candidate(partial):
    service, task_id, originals = partial
    before = saved(service, task_id)
    assert 11 not in before["assessment_batches"][0]["candidate_ids"]
    runner = ReviewRunner(hook)
    result = run_turn(ConversationService(service.config), task_id, runner)
    assert result.state == "completed", result
    assert [r.allowed_listing_ids for r in runner.requests if r.phase == "review_batch"] == [frozenset({1})]
    nominations = [r for r in runner.requests if r.phase == "nomination"]
    assert [len(r.review_context["assessments"]) for r in nominations] == [20, 3]
    assert len({a["listing_id"] for r in nominations for a in r.review_context["assessments"]}) == 23
    assert all(not r.candidates and not r.evidence and not r.messages and not r.runs for r in nominations)
    assert all(not r.allow_preference_update for r in nominations)
    after = saved(service, task_id)
    assert [e["listing_id"] for e in after["comparisons"][-1]["result"]["ranked_candidates"]] == [2, 11]
    assert after["reviews"][-1]["nomination_progress"] == dict(required=True, total_groups=2, completed_groups=2, pending_groups=0)
    assert after["comparisons"][-1]["coverage"]["assessed_count"] == 23
    final_input = runner.requests[-1].review_context
    assert final_input["nominations"][0]["candidates"][0]["reason"] == "依据保存判断重新提名"
    with connect(service.config.database_path) as conn:
        assert [tuple(r) for r in conn.execute("SELECT id,result_json,input_json,dependencies_json FROM research_assessments ORDER BY id LIMIT 2")] == originals
        assert conn.execute("SELECT COUNT(*) FROM review_candidate_links").fetchone()[0] == 19


@pytest.mark.parametrize("kind", ["foreign_listing", "wrong_assessment", "hard_failure", "lost_unknown", "duplicate", "wrong_type"])
def test_invalid_nominations_never_publish_a_comparison(partial, kind):
    service, task_id, _ = partial
    def corrupt(request):
        if request.phase != "nomination": return hook(request)
        items = request.review_context["assessments"]
        target = next(a for a in items if a["listing_id"] == (1 if kind == "hard_failure" else 2))
        raw = dict(type="nomination", candidates=[entry(target)])
        if kind == "foreign_listing": raw["candidates"][0]["listing_id"] = 99999
        if kind == "wrong_assessment": raw["candidates"][0]["assessment_id"] = 99999
        if kind == "lost_unknown": raw["candidates"][0]["uncertainties"] = []
        if kind == "duplicate": raw["candidates"].append(raw["candidates"][0].copy())
        if kind == "wrong_type": return AnswerResult(type="answer", content="不能作为提名", candidate_ids=[])
        return raw
    operation = run_turn(service, task_id, ReviewRunner(corrupt))
    assert operation.state == "failed" and operation.error_code == "invalid_codex_result"
    data = saved(service, task_id)
    assert len(data["comparisons"]) == 1 and data["comparisons"][0]["stale"]
    assert data["reviews"][-1]["coverage"]["pending_count"] == 0
    assert data["reviews"][-1]["nomination_progress"]["completed_groups"] == 0


@pytest.mark.parametrize("mutation", ["requirements", "evidence"])
def test_nomination_cannot_publish_against_changed_inputs(partial, mutation):
    service, task_id, _ = partial
    def changed(request):
        result = hook(request)
        if request.phase == "nomination":
            if mutation == "requirements": update_task_preferences(service.config, task_id, "新增需求", "全新需求")
            else:
                with connect(service.config.database_path) as conn:
                    conn.execute("UPDATE listing_snapshots SET description='new' WHERE listing_id=23")
        return result
    operation = run_turn(service, task_id, ReviewRunner(changed))
    assert operation.state == "failed" and operation.error_code in {"requirements_changed", "review_inputs_changed"}
    assert len(saved(service, task_id)["comparisons"]) == 1


def test_nomination_failure_preserves_assessments_and_retry_does_not_reevaluate(partial):
    service, task_id, _ = partial
    def fail(request):
        if request.phase == "nomination" and request.review_context["group_index"] == 1:
            raise CodexTimeoutError("offline nomination timeout")
        return hook(request)
    operation = run_turn(service, task_id, ReviewRunner(fail))
    assert operation.error_code == "codex_timeout"
    before = saved(service, task_id)
    assert before["reviews"][-1]["nomination_progress"]["completed_groups"] == 1
    assert len(before["comparisons"]) == 1
    retry = ReviewRunner(hook)
    assert run_turn(ConversationService(service.config), task_id, retry).state == "completed"
    assert not [r for r in retry.requests if r.phase == "review_batch"]
    assert len([r for r in retry.requests if r.phase == "nomination"]) == 2
    assert len(saved(service, task_id)["assessment_batches"]) == 3


def test_cancel_during_nomination_rejects_late_output(partial):
    service, task_id, _ = partial
    entered = threading.Event()
    runner = ReviewRunner()
    def blocked(request):
        if request.phase == "nomination":
            entered.set()
            assert runner.cancelled.wait(5)
        return hook(request)
    runner.hook = blocked
    operation = service.send_message(task_id, "重新评估").operation
    coordinator = OperationCoordinator(service, runner)
    try:
        coordinator.start(operation.id)
        assert entered.wait(5)
        coordinator.cancel(operation.id)
        wait_state(service.store, operation.id, {"cancelled"})
    finally: coordinator.shutdown()
    data = saved(service, task_id)
    assert len(data["comparisons"]) == 1
    assert data["reviews"][-1]["nomination_progress"]["completed_groups"] == 0


def test_nomination_save_is_atomic_idempotent_and_bound_to_its_group(partial):
    service, task_id, _ = partial
    def timeout(request):
        if request.phase == "nomination": raise CodexTimeoutError("stop before nomination")
        return hook(request)
    operation = run_turn(service, task_id, ReviewRunner(timeout))
    # Restore the interrupted operation only inside this isolated store fixture.
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE operations SET state='running',completed_at=NULL WHERE id=?", (operation.id,))
        review = conn.execute("SELECT * FROM history_reviews WHERE operation_id=?", (operation.id,)).fetchone()
        context = nomination_context(conn, review, 0)
        with pytest.raises(ValueError, match="nomination groups"): comparison_context(conn, review)
    request = OperationCoordinator(service, ReviewRunner())._build_request(task_id).model_copy(update={
        "phase": "nomination", "candidates": (), "evidence": (), "review_context": context,
        "allowed_listing_ids": frozenset(a["listing_id"] for a in context["assessments"])})
    result = hook(request)
    first = service.store.save_history_nomination(operation.id, review["id"], request, result)
    assert service.store.save_history_nomination(operation.id, review["id"], request, result) == first
    changed = result.model_copy(update={"candidates": []})
    with pytest.raises(InvalidActionRequestError): service.store.save_history_nomination(operation.id, review["id"], request, changed)
    bad = request.model_copy(update={"review_context": {**context, "assessments": []}})
    with pytest.raises(InvalidActionRequestError): service.store.save_history_nomination(operation.id, review["id"], bad, result)
    assert len([e for e in service.store.list_events(operation.id, 0) if "nomination_id" in e.payload]) == 1
    service.store.transition_operation(operation.id, {"running"}, "cancelled")
    with pytest.raises(OperationStateError): service.store.save_history_nomination(operation.id, review["id"], request, result)


@pytest.mark.parametrize("version", ["shopping-research-v5", "shopping-research-v6", "shopping-research-v7", "shopping-research-v8", "shopping-research-v9", "shopping-research-v10", "shopping-research-v11", "shopping-research-v12", "shopping-research-v13", "shopping-research-v4"])
def test_only_explicitly_compatible_independent_contract_can_be_partially_reused(partial, version):
    service, task_id, _ = partial
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE research_assessments SET prompt_version=?", (version,))
    runner = ReviewRunner(hook)
    assert run_turn(service, task_id, runner).state == "completed"
    ids = {i for r in runner.requests if r.phase == "review_batch" for i in r.allowed_listing_ids}
    assert ids == (set(range(1, 24)) if version.endswith("v4") else {1})


def test_new_tables_initialize_idempotently_without_rewriting_old_links(partial):
    service, task_id, _ = partial
    with connect(service.config.database_path) as conn:
        old = [tuple(r) for r in conn.execute("SELECT * FROM review_assessment_links ORDER BY review_id,assessment_id")]
        conn.execute("DROP TABLE review_nominations")
        conn.execute("DROP TABLE review_candidate_links")
    initialize(service.config.database_path)
    initialize(service.config.database_path)
    with connect(service.config.database_path) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM review_assessment_links ORDER BY review_id,assessment_id")] == old
    runner = ReviewRunner(hook)
    assert run_turn(service, task_id, runner).state == "completed"
