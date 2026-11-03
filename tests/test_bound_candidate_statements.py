"""User-selected evidence attribution is persisted before isolated local analysis."""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.assessment import input_refs, evidence_signature
from shopping_agent.candidate_context import build_candidate_evidence
from shopping_agent.codex_runtime import CodexTimeoutError, PreferenceUpdateResult
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import InvalidActionRequestError, OperationConflictError
from shopping_agent.db import connect, attach_run_to_task, initialize
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.web.app import create_app
from test_history_review import ReviewRunner, saved, add_noise
from test_operation_coordinator import wait_state
from test_structured_assessments import seed_phones, scripted_assessment
from test_web_preference_updates import ready_service, run_turn, ScriptedRunner, change, ORIGINAL


def bound_turn(service, task_id, runner, text="卖家原话：全原无修", listing_id=2, kind="seller_reply"):
    created = service.send_message(task_id, text, dict(listing_id=listing_id, kind=kind))
    coordinator = OperationCoordinator(service, runner)
    try:
        coordinator.start(created.operation.id)
        return wait_state(service.store, created.operation.id, {"completed", "failed"})
    finally: coordinator.shutdown()


def bound_assessment(request):
    if request.phase != "review_batch": return None
    answer = scripted_assessment(request)
    for item in answer.research.assessments:
        refs = [ref for ref, data in input_refs(request).items() if ref.startswith("statement:") and data["listing_id"] == item.listing_id]
        if refs:
            judgment = next(j for j in item.judgments if j.criterion_id == "originality")
            judgment.status = "CONFLICT" if len(refs) >= 2 else "MET"
            judgment.source_type = "seller_claim"
            judgment.reason = "用户转述，未经独立核实；冲突须保留" if len(refs) >= 2 else "用户转述卖家称全原，无独立验机证明"
            judgment.evidence_refs = refs
    return answer


@pytest.fixture
def seeded(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    return service, task_id


def test_bound_reply_reassesses_only_its_candidate_and_retains_immutable_source(seeded):
    service, task_id = seeded
    assert run_turn(service, task_id, ReviewRunner()).state == "completed"
    original = saved(service, task_id)["assessment_batches"][0]
    runner = ReviewRunner(bound_assessment)
    operation = bound_turn(service, task_id, runner)
    assert operation.state == "completed", operation
    assert not runner.requests[0].allow_preference_update
    assert [r.allowed_listing_ids for r in runner.requests if r.phase == "review_batch"] == [frozenset({2})]
    data = saved(service, task_id)
    old, new = data["assessment_batches"]
    assert old["result"] == original["result"]
    assert old["candidate_stale"] == {"1": False, "2": True, "3": False, "4": False}
    judgment = new["result"]["assessments"][0]["judgments"][-1]
    assert judgment["source_type"] == "seller_claim" and judgment["status"] == "MET"
    excerpt = next(value for ref, value in new["evidence_refs"].items() if ref.startswith("statement:"))
    statement = json.loads(excerpt["data"]["evidence_json"])
    assert statement["statement_text"] == "卖家原话：全原无修" and not statement["independently_verified"]
    assert statement["attribution"] == "user_relayed_seller_claim"
    restored = ConversationService(service.config).get_messages(task_id).items
    message = next(m for m in restored if m.id == statement["source_message_id"])
    assert message.candidate_statement.listing_id == 2 and message.content == statement["statement_text"]
    assert not any(m.candidate_statement for m in restored if m.role != "user")
    with connect(service.config.database_path) as conn:
        assert not service.store._preference_update_allowed(conn, task_id, message.id)


def test_conflicting_replies_have_distinct_references_and_do_not_replace_old_claims(seeded):
    service, task_id = seeded
    assert bound_turn(service, task_id, ReviewRunner(bound_assessment), "卖家称没换屏").state == "completed"
    first = saved(service, task_id)["assessment_batches"][0]["result"]
    assert bound_turn(service, task_id, ReviewRunner(bound_assessment), "卖家改口称换过屏").state == "completed"
    data = saved(service, task_id)
    judgment = data["assessment_batches"][-1]["result"]["assessments"][0]["judgments"][-1]
    assert judgment["status"] == "CONFLICT" and len(set(judgment["evidence_refs"])) == 2
    assert data["assessment_batches"][0]["result"] == first
    evidence = build_candidate_evidence(service.config, task_id=task_id, listing_ids=[2])["candidates"][0]
    assert [r["statement_text"] for r in evidence["user_statements"]] == ["卖家称没换屏", "卖家改口称换过屏"]


@pytest.mark.parametrize("kind", ["seller_reply", "user_observation"])
def test_saved_statement_survives_timeout_restart_and_old_message_window(seeded, kind):
    service, task_id = seeded
    assert bound_turn(service, task_id, ScriptedRunner(CodexTimeoutError("offline")), kind=kind).state == "failed"
    with connect(service.config.database_path) as conn:
        for _ in range(105): conn.execute("INSERT INTO conversation_messages(task_id,role,content,created_at) VALUES (?,'system','历史记录','fixture')", (task_id,))
    restarted = ConversationService(service.config)
    request = OperationCoordinator(restarted, ReviewRunner())._build_request(task_id)
    refs = {k: v for k, v in input_refs(request).items() if k.startswith("statement:")}
    assert len(refs) == 1 and next(iter(refs.values()))["listing_id"] == 2
    assert json.loads(next(iter(refs.values()))["data"]["evidence_json"])["kind"] == kind
    assert not any("全原无修" in m.content for m in request.messages)


def test_bound_evidence_cannot_be_used_to_modify_requirements(seeded):
    service, task_id = seeded
    operation = bound_turn(service, task_id, ScriptedRunner(change), "卖家说预算可以提高到4300")
    assert operation.state == "failed" and operation.error_code == "invalid_codex_result"
    with connect(service.config.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_preference_revisions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM candidate_statements").fetchone()[0] == 1


@pytest.mark.parametrize("binding", [{"listing_id": 9999, "kind": "seller_reply"}, {"listing_id": True, "kind": "seller_reply"},
    {"listing_id": 0, "kind": "seller_reply"}, {"listing_id": 2, "kind": "verified"}, {"listing_id": 2, "kind": "seller_reply", "extra": 1}])
def test_invalid_binding_rolls_back_message_operation_and_statement(seeded, binding):
    service, task_id = seeded
    before = len(service.get_messages(task_id).items)
    with pytest.raises(InvalidActionRequestError): service.send_message(task_id, "补充", binding)
    assert len(service.get_messages(task_id).items) == before
    with connect(service.config.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_statements").fetchone()[0] == 0


def test_same_listing_shared_by_tasks_does_not_share_user_statement(seeded):
    service, task_id = seeded
    other = service.create_task("独立研究")
    service.store.transition_operation(other.operation.id, {"queued"}, "completed")
    with connect(service.config.database_path) as conn:
        run_id = conn.execute("SELECT run_id FROM task_runs WHERE task_id=?", (task_id,)).fetchone()[0]
        attach_run_to_task(conn, task_id=other.task.id, run_id=run_id)
        before = evidence_signature(conn, task_id)
    assert bound_turn(service, other.task.id, ScriptedRunner(CodexTimeoutError("offline"))).state == "failed"
    with connect(service.config.database_path) as conn: assert evidence_signature(conn, task_id) == before
    assert not build_candidate_evidence(service.config, task_id=task_id, listing_ids=[2])["candidates"][0]["user_statements"]
    assert not build_candidate_evidence(service.config, run_ids=[run_id], listing_ids=[2])["candidates"][0]["user_statements"]


def test_unbound_ambiguous_message_does_not_become_candidate_evidence(seeded):
    service, task_id = seeded
    assert run_turn(service, task_id, ReviewRunner(), "他说没修过，指的是谁还没确定").state == "completed"
    assert not any(m.candidate_statement for m in service.get_messages(task_id).items)
    with connect(service.config.database_path) as conn: assert conn.execute("SELECT COUNT(*) FROM candidate_statements").fetchone()[0] == 0


def test_statement_capture_is_atomic_with_operation_conflict(seeded):
    service, task_id = seeded
    created = service.send_message(task_id, "正在分析")
    with pytest.raises(OperationConflictError): service.send_message(task_id, "卖家回复", dict(listing_id=2, kind="seller_reply"))
    with connect(service.config.database_path) as conn: assert conn.execute("SELECT COUNT(*) FROM candidate_statements").fetchone()[0] == 0
    service.store.transition_operation(created.operation.id, {"queued"}, "completed")
    with pytest.raises(InvalidActionRequestError): service.send_message(task_id, "a"*8001, dict(listing_id=2, kind="seller_reply"))
    with pytest.raises(InvalidActionRequestError): service.send_message(task_id, "巨大编号", dict(listing_id=10**80, kind="seller_reply"))


def test_bounded_statement_history_preserves_old_messages_and_initializer(seeded):
    service, task_id = seeded
    for n in range(21):
        created = service.send_message(task_id, f"原文{n}", dict(listing_id=2, kind="user_observation"))
        service.store.transition_operation(created.operation.id, {"queued"}, "completed")
    initialize(service.config.database_path)
    evidence = build_candidate_evidence(service.config, task_id=task_id, listing_ids=[2])["candidates"][0]
    assert evidence["user_statement_count"] == 21 and evidence["user_statements_truncated"]
    assert len(evidence["user_statements"]) == 20 and evidence["user_statements"][0]["statement_text"] == "原文1"
    assert any(m.content == "原文0" and m.candidate_statement for m in service.get_messages(task_id).items)


def test_recent_explicit_binding_supplements_candidates_beyond_chat_limit(seeded):
    service, task_id = seeded
    late = add_noise(service, task_id, 201)
    service.send_message(task_id, "这件商品的卖家说可以面交", dict(listing_id=late, kind="seller_reply"))
    request = OperationCoordinator(service, ReviewRunner())._build_request(task_id)
    assert late in request.allowed_listing_ids and late in {e.listing_id for e in request.evidence}
    assert any(k.startswith(f"statement:{late}:") for k in input_refs(request))


@pytest.mark.anyio
async def test_api_binding_is_scoped_and_restores_in_messages_and_evidence(seeded, tmp_path):
    service, task_id = seeded
    path = tmp_path / "config.toml"
    path.write_text(f'database_path = "{service.config.database_path.as_posix()}"\n', encoding="utf-8")
    app = create_app(path, tmp_path / "settings.json")
    app.state.codex_runtime = ScriptedRunner(CodexTimeoutError("offline"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            response = await client.post(f"/api/tasks/{task_id}/messages", json=dict(message="卖家原话", candidate_statement=dict(listing_id=2,kind="seller_reply")))
            assert response.status_code == 202 and response.json()["message"]["candidate_statement"]["listing_id"] == 2
            wait_state(service.store, response.json()["operation"]["id"], {"failed"})
            messages = (await client.get(f"/api/tasks/{task_id}/messages")).json()["items"]
            assert messages[-1]["candidate_statement"]["kind"] == "seller_reply"
            evidence = (await client.get(f"/api/listings/2/evidence", params={"task_id": task_id})).json()
            assert evidence["user_statements"][0]["statement_text"] == "卖家原话"
            assert (await client.post("/api/tasks", json=dict(message="新研究",candidate_statement=dict(listing_id=2,kind="seller_reply")))).status_code == 422
            assert (await client.post(f"/api/tasks/{task_id}/messages", json=dict(message="坏编号",candidate_statement=dict(listing_id=True,kind="seller_reply")))).status_code == 422
            assert (await client.post(f"/api/tasks/{task_id}/messages", json=dict(message="巨大编号",candidate_statement=dict(listing_id=10**80,kind="seller_reply")))).status_code == 422


@pytest.fixture
def anyio_backend(): return "asyncio"
