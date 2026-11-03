"""Real saved checklist context and publication guards, with scripted reasoning."""
import json

import pytest

from shopping_agent.assessment import evidence_state, input_refs
from shopping_agent.check_context import check_signature
from shopping_agent.codex_runtime import AnswerResult, ActionRequestResult, CodexRuntime
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import connect, attach_run_to_task
from shopping_agent.operation_coordinator import OperationCoordinator
from test_candidate_checks import fixture, create, link
from test_history_review import ReviewRunner, saved, add_noise
from test_web_preference_updates import ScriptedRunner, run_turn, change


def request(service, task):
    return OperationCoordinator(service, ScriptedRunner())._build_request(task)


def test_current_association_is_a_reference_not_verified_fact(fixture):
    service, task, statement, store = fixture
    item = link(store, task, create(store, task), statement)
    restored = request(ConversationService(service.config), task)
    check = restored.follow_up_context["items"][0]
    assert check["id"] == item["id"] and check["state"] == "evidence_linked"
    assert not check["independently_verified"] and check["source_status"] == "current_in_input"
    assert input_refs(restored)[check["linked_evidence_ref"]]["data"]["statement_id"] == statement
    assert "statement_text" not in check and "statement_text" not in restored.follow_up_context
    prompt = CodexRuntime._build_prompt(restored)
    assert "NOT candidate facts" in prompt and "Association alone" in prompt
    assert "屏幕是否换过" in prompt


@pytest.mark.parametrize("action", ["withdraw", "rebind", "retag", "roundtrip"])
def test_corrected_link_cannot_reconstruct_old_evidence(fixture, action):
    service, task, statement, store = fixture
    link(store, task, create(store, task), statement)
    if action == "withdraw":
        service.change_statement(task, statement, action="withdraw", expected_revision_id=0)
    else:
        result = service.change_statement(task, statement, action="rebind", expected_revision_id=0,
            listing_id=2 if action == "retag" else 3, kind="user_observation" if action == "retag" else "seller_reply")
        if action == "roundtrip":
            service.change_statement(task, statement, action="rebind", expected_revision_id=result.revision_id, listing_id=2, kind="seller_reply")
    snapshot = request(service, task)
    check = snapshot.follow_up_context["items"][0]
    assert check["state"] == "pending" and check["needs_recheck"]
    assert check["source_status"] == "invalid" and check["linked_evidence_ref"] is None
    assert "statement_text" not in check
    if action == "withdraw":
        assert not any(ref.startswith("statement:") for ref in input_refs(snapshot))


def test_older_link_not_supplied_does_not_bypass_twenty_source_bound(fixture):
    service, task, statement, store = fixture
    link(store, task, create(store, task), statement)
    for _ in range(20):
        added = service.send_message(task, "新的补充", dict(listing_id=2, kind="seller_reply"))
        service.store.transition_operation(added.operation.id, {"queued"}, "cancelled")
    snapshot = request(service, task)
    check = snapshot.follow_up_context["items"][0]
    assert check["source_status"] == "current_not_in_input" and not check["needs_recheck"]
    assert check["linked_evidence_ref"] is None
    assert len([r for r in input_refs(snapshot) if r.startswith("statement:")]) == 20


def test_twenty_question_bound_counts_dismissed_and_task_isolation(fixture):
    service, task, statement, store = fixture
    original = create(store, task)
    store.change(task, 2, original["id"], expected_revision_id=0, state="dismissed")
    for i in range(23):
        store.create(task, 2, question=f"核实问题{i}", request_key=f"request-{i:04}-new")
    other = service.create_task("另一个任务")
    service.store.transition_operation(other.operation.id, {"queued"}, "completed")
    with connect(service.config.database_path) as conn:
        run_id = conn.execute("SELECT run_id FROM task_runs WHERE task_id=?", (task,)).fetchone()[0]
        attach_run_to_task(conn, task_id=other.task.id, run_id=run_id)
    store.create(other.task.id, 2, question="另任务私有问题", request_key="other-task-key")
    snapshot = request(service, task)
    data = snapshot.follow_up_context
    assert len(data["items"]) == 20 and data["total_count"] == 23 and data["truncated"]
    assert data["dismissed_count"] == 1
    assert "另任务私有问题" not in json.dumps(data, ensure_ascii=False)
    assert all(item["id"] != original["id"] for item in data["items"])


@pytest.mark.parametrize("result_kind", ["answer", "action", "preferences"])
def test_changed_checklist_blocks_old_publication_atomically(fixture, result_kind):
    service, task, statement, store = fixture
    def mutate(snapshot):
        create(store, task)
        if result_kind == "action":
            return ActionRequestResult(type="action_request", summary="查看详情", risk="low", listing_ids=[2], actions=["detail"])
        if result_kind == "preferences":
            return change(snapshot)
        return AnswerResult(type="answer", content="旧清单回答", candidate_ids=[])
    result = run_turn(service, task, ScriptedRunner(mutate), "请分析现有核实问题")
    assert result.state == "failed" and result.error_code == "review_inputs_changed", result
    assert "清单已变化" in result.error_detail
    with connect(service.config.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM conversation_messages WHERE operation_id=? AND role='assistant'", (result.id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM action_requests WHERE operation_id=?", (result.id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_preference_revisions WHERE task_id=?", (task,)).fetchone()[0] == 0
    assert store.page(task, 2)["total_count"] == 1


def test_check_changes_preserve_facts_and_reuse_but_comparison_reads_fresh_context(fixture):
    service, task, statement, store = fixture
    runner = ReviewRunner()
    assert run_turn(service, task, runner).state == "completed"
    before = saved(service, task)
    with connect(service.config.database_path) as conn:
        facts = evidence_state(conn, task)
        old_checks = check_signature(conn, task)
    create(store, task)
    second = ReviewRunner()
    assert run_turn(service, task, second).state == "completed"
    assert not any(r.phase == "review_batch" for r in second.requests)
    comparison = next(r for r in second.requests if r.phase == "comparison")
    assert comparison.follow_up_context["items"][0]["question"] == "屏幕是否换过？"
    assert not comparison.evidence and not comparison.candidates
    assert all(not r.follow_up_context for r in runner.requests if r.phase in {"review_batch", "nomination"})
    assert saved(service, task)["assessment_batches"][0]["result"] == before["assessment_batches"][0]["result"]
    with connect(service.config.database_path) as conn:
        assert evidence_state(conn, task) == facts
        assert check_signature(conn, task) != old_checks


def test_comparison_cannot_publish_after_checklist_changes(fixture):
    service, task, statement, store = fixture
    def mutate(snapshot):
        if snapshot.phase == "comparison":
            create(store, task)
    result = run_turn(service, task, ReviewRunner(mutate))
    assert result.state == "failed" and result.error_code == "review_inputs_changed", result
    data = saved(service, task)
    assert data["assessment_batches"] and not data["comparisons"]


def test_recent_check_supplements_bounded_chat_cards(fixture):
    service, task, statement, store = fixture
    listing_id = add_noise(service, task, 201)
    store.create(task, listing_id, question="较早未展示的候选也要核实", request_key="last-candidate-key")
    snapshot = request(service, task)
    assert listing_id in snapshot.allowed_listing_ids
    assert snapshot.follow_up_context["items"][0]["listing_id"] == listing_id
