"""Proposals never become facts or checklist entries without confirmation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.assessment import CheckSuggestion, evidence_state
from shopping_agent.check_context import check_signature
from shopping_agent.check_suggestions import CheckSuggestions
from shopping_agent.codex_runtime import AnswerResult, CodexRuntime, InvalidCodexResult
from shopping_agent.conversation_store import OperationConflictError, RecordNotFoundError, InvalidActionRequestError
from shopping_agent.db import connect, initialize
from shopping_agent.web.app import create_app
from test_candidate_checks import fixture, create
from test_history_review import ReviewRunner, comparison, saved
from test_structured_assessments import scripted_assessment
from test_web_preference_updates import ScriptedRunner, run_turn


def propose(service, task, question="屏幕是否换过？", listing=2):
    runner = ScriptedRunner(AnswerResult(type="answer", content="有待核实问题，请在商品证据清单确认保存。", candidate_ids=[listing],
        check_suggestions=[CheckSuggestion(listing_id=listing, question=question, reason="缺少维修记录，需要核对实物。")]))
    result = run_turn(service, task, runner, "请提出需要核实的问题")
    assert result.state == "completed", result
    return CheckSuggestions(service.config).page(task, listing)["items"][0]


def test_proposal_is_inert_persistent_and_confirmed_once(fixture):
    service, task, _, checks = fixture
    suggestions = CheckSuggestions(service.config)
    with connect(service.config.database_path) as conn:
        facts, guard = evidence_state(conn, task), check_signature(conn, task)
    row = propose(service, task)
    assert row["check_id"] is None and not row["stale"]
    assert checks.page(task, 2)["total_count"] == 0
    initialize(service.config.database_path)
    with connect(service.config.database_path) as conn:
        assert evidence_state(conn, task) == facts and check_signature(conn, task) == guard
        assert conn.execute("SELECT role FROM conversation_messages WHERE id=?", (row["source_message_id"],)).fetchone()[0] == "assistant"
    accepted = suggestions.accept(task, 2, row["id"])
    assert not accepted["reused_existing"] and accepted["check"]["state"] == "pending"
    assert accepted == suggestions.accept(task, 2, row["id"])
    assert checks.page(task, 2)["total_count"] == 1
    with connect(service.config.database_path) as conn:
        assert evidence_state(conn, task) == facts and check_signature(conn, task) != guard


@pytest.mark.parametrize("dismissed", [False, True])
def test_confirmation_reuses_normalized_existing_without_reviving(fixture, dismissed):
    service, task, _, checks = fixture
    old = checks.create(task, 2, question=" 屏幕是否换过？ ", request_key="existing-item-key")
    if dismissed:
        old = checks.change(task, 2, old["id"], expected_revision_id=0, state="dismissed")
    row = propose(service, task, "屏幕是否换过?")  # NFKC normalizes full-width question mark.
    accepted = CheckSuggestions(service.config).accept(task, 2, row["id"])
    assert accepted["reused_existing"] and accepted["check"] == old
    assert checks.page(task, 2)["total_count"] == 1


def test_two_concurrent_proposals_of_same_question_create_one_item(fixture):
    service, task, _, checks = fixture
    one, two = propose(service, task), propose(service, task)
    store = CheckSuggestions(service.config)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda row: store.accept(task, 2, row["id"]), (one, two)))
    assert len({r["check"]["id"] for r in results}) == 1
    assert sum(r["reused_existing"] for r in results) == 1
    assert checks.page(task, 2)["total_count"] == 1


@pytest.mark.parametrize("mutation", ["evidence", "requirements"])
def test_stale_proposal_blocks_confirmation_but_not_retry_of_saved_item(fixture, mutation):
    service, task, _, checks = fixture
    store = CheckSuggestions(service.config)
    one, two = propose(service, task), propose(service, task, "电池实测多少？")
    accepted = store.accept(task, 2, one["id"])
    with connect(service.config.database_path) as conn:
        if mutation == "evidence":
            conn.execute("UPDATE listing_snapshots SET price_text='9999' WHERE listing_id=2")
        else:
            from shopping_agent.db import add_task_preference_revision
            add_task_preference_revision(conn, task, "新预算", "预算3000", "[]", "[]")
    assert all(r["stale"] for r in store.page(task, 2)["items"])
    with pytest.raises(OperationConflictError):
        store.accept(task, 2, two["id"])
    assert store.accept(task, 2, one["id"]) == accepted
    assert checks.page(task, 2)["total_count"] == 1


def test_scope_in_parser_and_confirmation_is_enforced(fixture):
    service, task, _, _ = fixture
    row = propose(service, task)
    with pytest.raises(RecordNotFoundError):
        CheckSuggestions(service.config).accept(task, 3, row["id"])
    raw = AnswerResult(type="answer", content="ok", candidate_ids=[], check_suggestions=[CheckSuggestion(listing_id=999, question="问题", reason="原因")]).model_dump_json()
    with pytest.raises(InvalidCodexResult):
        CodexRuntime(service.config.database_path.parent).parse_result(raw, allowed_listing_ids={2})


def test_same_listing_in_other_task_cannot_accept_or_share_dedup(fixture):
    service, task, _, _ = fixture
    row = propose(service, task)
    other = service.create_task("另一个独立任务")
    service.store.transition_operation(other.operation.id, {"queued"}, "completed")
    from shopping_agent.db import attach_run_to_task
    with connect(service.config.database_path) as conn:
        run_id = conn.execute("SELECT run_id FROM task_runs WHERE task_id=?", (task,)).fetchone()[0]
        attach_run_to_task(conn, other.task.id, run_id)
    store = CheckSuggestions(service.config)
    with pytest.raises(RecordNotFoundError):
        store.accept(other.task.id, 2, row["id"])
    own = propose(service, other.task.id)
    assert not store.accept(other.task.id, 2, own["id"])["reused_existing"]
    assert store.page(task, 2)["items"][0]["check_id"] is None


@pytest.mark.parametrize("bad", [dict(listing_id=True, question="问题", reason="原因"), dict(listing_id=2, question=" ", reason="原因"), dict(listing_id=2, question="问题", reason=" ")])
def test_invalid_model_suggestions_are_rejected(bad):
    import json
    with pytest.raises(InvalidCodexResult):
        CodexRuntime(__import__('pathlib').Path.cwd()).parse_result(json.dumps(dict(type="answer", content="回答", candidate_ids=[], check_suggestions=[bad])), allowed_listing_ids={2})


def test_duplicate_output_questions_are_coalesced_without_saving_checks(fixture):
    service, task, _, checks = fixture
    item = CheckSuggestion(listing_id=2, question="屏幕是否换过？", reason="维修史未知")
    result = run_turn(service, task, ScriptedRunner(AnswerResult(type="answer", content="待确认", candidate_ids=[], check_suggestions=[item, item])))
    assert result.state == "completed"
    assert CheckSuggestions(service.config).page(task, 2)["total_count"] == 1
    assert checks.page(task, 2)["total_count"] == 0


def test_invalid_save_rolls_back_answer_and_operation_completion(fixture):
    service, task, _, _ = fixture
    from shopping_agent.operation_coordinator import OperationCoordinator
    runner = ScriptedRunner()
    request = OperationCoordinator(service, runner)._build_request(task)
    operation = service.send_message(task, "测试原子性").operation
    service.store.transition_operation(operation.id, {"queued"}, "running")
    with pytest.raises(InvalidActionRequestError):
        service.store.complete_with_answer(operation.id, "不能发布", [], research_request=request,
            check_suggestions=[CheckSuggestion(listing_id=999, question="越界问题", reason="原因")])
    with connect(service.config.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_check_suggestions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM conversation_messages WHERE operation_id=? AND role='assistant'", (operation.id,)).fetchone()[0] == 0
    assert service.store.get_operation(operation.id).state == "running"


def test_only_final_comparison_may_propose_during_review(fixture):
    service, task, _, _ = fixture
    item = CheckSuggestion(listing_id=2, question="屏幕是否换过？", reason="待核实")
    def hook(request):
        if request.phase == "comparison":
            return comparison(request).model_copy(update={"check_suggestions": [item]})
    assert run_turn(service, task, ReviewRunner(hook)).state == "completed"
    assert CheckSuggestions(service.config).page(task, 2)["total_count"] == 1
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE listing_snapshots SET price_text='3700' WHERE listing_id=2")
    def bad(request):
        if request.phase == "review_batch":
            return scripted_assessment(request).model_copy(update={"check_suggestions": [item]})
    result = run_turn(service, task, ReviewRunner(bad))
    assert result.state == "failed" and result.error_code == "invalid_codex_result"


def test_suggestion_page_has_bounded_keyset_history(fixture):
    service, task, _, _ = fixture
    row = propose(service, task)
    with connect(service.config.database_path) as conn:
        for i in range(22):
            conn.execute("INSERT INTO candidate_check_suggestions(task_id,listing_id,operation_id,source_message_id,question,reason,preference_revision_id,evidence_signature,created_at) SELECT task_id,listing_id,operation_id,source_message_id,?,reason,preference_revision_id,evidence_signature,created_at FROM candidate_check_suggestions WHERE id=?", (f"问题{i}", row["id"]))
    store = CheckSuggestions(service.config)
    first = store.page(task, 2)
    assert first["total_count"] == 23 and len(first["items"]) == 20 and first["has_more"]
    second = store.page(task, 2, before_id=first["next_before_id"])
    assert len(second["items"]) == 3 and not second["has_more"]


def test_api_requires_explicit_true_and_immutable_suggestion(fixture, tmp_path):
    service, task, _, _ = fixture
    row = propose(service, task)
    config_path = tmp_path / "web.toml"
    config_path.write_text(f'database_path = "{service.config.database_path.as_posix()}"\n', encoding="utf-8")
    app = create_app(config_path, tmp_path / "settings.json")
    async def check():
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                path = f"/api/tasks/{task}/listings/2/check-suggestions/{row['id']}/accept"
                for body in ({}, {"confirm": False}, {"confirm": 1}, {"confirm": True, "question": "改写"}):
                    assert (await client.post(path, json=body)).status_code == 422
                result = await client.post(path, json={"confirm": True})
                assert result.status_code == 200 and result.json()["check"]["question"] == row["question"]
                assert (await client.post(path, json={"confirm": True})).json() == result.json()
    asyncio.run(check())
