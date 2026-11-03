"""Whole-task local review, partial persistence and comparison publication."""
import json
import threading
import asyncio

import pytest

from shopping_agent.codex_runtime import CodexRuntime, CodexTimeoutError, AnswerResult
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import connect, upsert_listing, add_listing_snapshot, initialize
from shopping_agent.history_review import HistoryReviewResult, ComparisonResult, NominationResult
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.tasks import update_task_preferences
from shopping_agent.web.services import WorkbenchService
from test_operation_coordinator import wait_state
from test_web_preference_updates import ready_service, run_turn, change
from test_structured_assessments import seed_phones, scripted_assessment
from test_web_preference_updates import ORIGINAL


def comparison(request):
    items = request.review_context["assessments"]
    eligible = [a for a in items if a["conclusion"] != "not_met"]
    eligible.sort(key=lambda a: (0 if a["summary"].startswith("C ") else 1, a["listing_id"]))
    ranked = eligible[:2]
    before = request.review_context["previous_comparison"]
    before = {c["listing_id"] for c in before["ranked_candidates"]} if before else set()
    after = {c["listing_id"] for c in ranked}
    by_id = {a["listing_id"]: a for a in items}
    return ComparisonResult.model_validate(dict(type="comparison", content="使用已保存评估比较，保留未知，不代表独立验机。",
        ranked_candidates=[dict(listing_id=a["listing_id"], assessment_id=a["assessment_id"], reason=a["summary"], uncertainties=["维修史与实物待核实"]) for a in ranked],
        changes=[dict(listing_id=i, assessment_id=by_id[i]["assessment_id"], kind=kind, reason="根据同版本逐项评估调整候选")
                 for ids, kind in ((after-before, "entered"), (before-after, "exited")) for i in sorted(ids)]))


class ReviewRunner:
    build_request = CodexRuntime.build_request

    def __init__(self, hook=None, update=False):
        self.requests = []
        self.hook = hook
        self.update = update
        self.cancelled = threading.Event()

    def run(self, request, *, run_id, stage_callback):
        self.requests.append(request)
        stage_callback("analyzing_evidence")
        if self.hook:
            result = self.hook(request)
            if result is not None:
                return result
        if request.phase == "review_batch":
            return scripted_assessment(request)
        if request.phase == "comparison":
            return comparison(request)
        if request.phase == "nomination":
            return NominationResult(type="nomination", candidates=[dict(listing_id=a["listing_id"], assessment_id=a["assessment_id"],
                reason=a["summary"], uncertainties=["维修史与实物待核实"]) for a in request.review_context["assessments"] if a["conclusion"] != "not_met"][:4])
        if self.update and request.allow_preference_update:
            return change(request)
        criteria = list(request.current_criteria) or scripted_assessment(request.model_copy(update={"candidates": (), "evidence": ()})).research.criteria
        return HistoryReviewResult(type="history_review", summary="重新审视当前任务全部已保存候选", criteria=criteria)

    def cancel(self, run_id):
        self.cancelled.set()


def saved(service, task_id):
    return WorkbenchService(service.config).get_task(task_id).research.model_dump()


def add_noise(service, task_id, count):
    with connect(service.config.database_path) as conn:
        run_id = conn.execute("SELECT run_id FROM task_runs WHERE task_id=?", (task_id,)).fetchone()[0]
        for n in range(count):
            listing_id = upsert_listing(conn, platform="xianyu", url=f"https://example.test/noise/{n}")
            add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id,
                title=f"Noise {n} A iPhone 15 Pro 256GB", price_text="3500", location="上海", description="电池89%，卖家称全原无修")
    return listing_id


@pytest.mark.parametrize("include_c", [True, False], ids=["historical-C-returns", "V6-no-C"])
def test_review_reconsiders_whole_history_and_versioned_changes(tmp_path, include_c):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id, include_c=include_c)
    runner = ReviewRunner()
    assert run_turn(service, task_id, runner, "重新评估全部历史候选").state == "completed"
    first = saved(service, task_id)
    assert first["reviews"][0]["coverage"]["pending_count"] == 0
    assert len(first["assessment_batches"]) == 1
    assert len(first["comparisons"]) == 1
    previous_ids = [c["listing_id"] for c in first["comparisons"][0]["result"]["ranked_candidates"]]
    assert previous_ids == [1, 2]
    revised_runner = ReviewRunner(update=True)
    operation = run_turn(service, task_id, revised_runner)
    assert operation.state == "completed", operation
    after = saved(ConversationService(service.config), task_id)
    assert len(after["comparisons"]) == 2
    old, current = after["comparisons"]
    assert old["stale"] and not current["stale"]
    assert old["result"] == first["comparisons"][0]["result"]
    assert current["previous_comparison_id"] == old["id"]
    assert current["coverage"] == dict(scope_count=4 if include_c else 3, reviewed_count=4 if include_c else 3,
                                       assessed_count=4 if include_c else 3, pending_count=0, truncated=False)
    current_ids = [c["listing_id"] for c in current["result"]["ranked_candidates"]]
    assert current_ids == ([3, 2] if include_c else [2])
    assert {(c["listing_id"], c["kind"]) for c in current["result"]["changes"]} == ({(1, "exited"), (3, "entered")} if include_c else {(1, "exited")})
    assert all(not req.allow_preference_update for req in revised_runner.requests if req.phase != "chat")


def test_more_than_200_candidates_and_recent_supplement_are_task_scoped(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    late_id = add_noise(service, task_id, 201)
    operation = service.send_message(task_id, "最近候选").operation
    service.store.transition_operation(operation.id, {"queued"}, "running")
    service.store.complete_with_answer(operation.id, "选择较晚保存的候选", [late_id])
    coordinator = OperationCoordinator(service, ReviewRunner())
    request = coordinator._build_request(task_id)
    assert late_id in request.allowed_listing_ids
    assert late_id in {e.listing_id for e in request.evidence}
    assert len(request.candidates) == 201 and request.scope_coverage["scope_count"] == 205
    other = service.create_task("另一任务")
    assert not coordinator._build_request(other.task.id).allowed_listing_ids
    # A separate task's active operation does not interfere with this task.
    runner = ReviewRunner()
    # This case persists 205 assessments in 11 batches; under full-suite load
    # its bounded completion budget is larger than a single-turn smoke test.
    operation = run_turn(service, task_id, runner, "重评所有历史候选", completion_timeout=30)
    assert operation.state == "completed", operation
    batches = [r for r in runner.requests if r.phase == "review_batch"]
    assert len(batches) == 11 and all(len(r.candidates) <= 20 for r in batches)
    all_ids = [c.listing_id for r in batches for c in r.candidates]
    assert len(all_ids) == len(set(all_ids)) == 205 and late_id in all_ids
    result = saved(service, task_id)
    assert result["comparisons"][-1]["coverage"]["assessed_count"] == 205


def test_partial_failure_preserves_batches_and_retry_reuses_them(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    add_noise(service, task_id, 19)  # 23 candidates, 2 batches
    seen = 0
    def fail_second(request):
        nonlocal seen
        if request.phase == "review_batch":
            seen += 1
            if seen == 2:
                raise CodexTimeoutError("fixture")
    operation = run_turn(service, task_id, ReviewRunner(fail_second))
    assert operation.state == "failed" and operation.error_code == "codex_timeout"
    first = saved(service, task_id)
    assert len(first["assessment_batches"]) == 1
    assert first["reviews"][0]["coverage"]["assessed_count"] == 20
    assert first["reviews"][0]["coverage"]["pending_count"] == 3
    assert not first["comparisons"]
    restarted = ConversationService(service.config)
    runner = ReviewRunner()
    operation = run_turn(restarted, task_id, runner, "继续重评")
    assert operation.state == "completed", operation
    assert len([r for r in runner.requests if r.phase == "review_batch"]) == 1
    result = saved(restarted, task_id)
    assert len(result["assessment_batches"]) == 2
    assert result["reviews"][-1]["coverage"]["pending_count"] == 0
    assert result["comparisons"][0]["coverage"]["assessed_count"] == 23


@pytest.mark.parametrize("failure_kind", ["timeout", "execution"])
def test_nomination_failure_restarts_services_and_reuses_saved_assessments(tmp_path, failure_kind):
    from shopping_agent.codex_runtime import CodexExecutionError
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    assert run_turn(service, task_id, ReviewRunner(), "先重评全部候选").state == "completed"
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE listing_snapshots SET price_text='3501' WHERE listing_id=1")
    def fail(request):
        if request.phase == "nomination":
            raise (CodexTimeoutError if failure_kind == "timeout" else CodexExecutionError)("fixture")
    assert run_turn(service, task_id, ReviewRunner(fail), "重评全部候选").state == "failed"
    before = saved(service, task_id)
    assert len(before["assessment_batches"]) == 2 and len(before["comparisons"]) == 1
    assert before["comparisons"][-1]["stale"]
    restarted = ConversationService(service.config)
    runner = ReviewRunner()
    assert run_turn(restarted, task_id, runner, "继续重评全部候选").state == "completed"
    assert [r.phase for r in runner.requests] == ["chat", "nomination", "comparison"]
    after = saved(restarted, task_id)
    assert after["assessment_batches"] == before["assessment_batches"]
    assert after["comparisons"][-1]["coverage"]["assessed_count"] == 4
    assert not after["comparisons"][-1]["stale"]


@pytest.mark.parametrize("corrupt", ["other_assessment", "missing_change", "wrong_change", "hard_failure", "cross_task"])
def test_invalid_comparison_never_publishes_snapshot_or_answer(tmp_path, corrupt):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    def bad(request):
        if request.phase != "comparison":
            return None
        result = comparison(request).model_dump()
        if corrupt == "other_assessment":
            result["ranked_candidates"][0]["assessment_id"] = 99999
        elif corrupt == "missing_change":
            result["changes"] = []
        elif corrupt == "wrong_change":
            result["changes"][0]["kind"] = "exited"
        elif corrupt == "cross_task":
            result["ranked_candidates"][0]["listing_id"] = 99999
        else:
            item = next(a for a in request.review_context["assessments"] if a["conclusion"] == "not_met") if any(a["conclusion"] == "not_met" for a in request.review_context["assessments"]) else None
            # Inject an excluded candidate that is not in the comparison input.
            result["ranked_candidates"][0]["listing_id"] = item["listing_id"] if item else 3
        return result
    operation = run_turn(service, task_id, ReviewRunner(bad))
    assert operation.state == "failed" and operation.error_code == "invalid_codex_result"
    result = saved(service, task_id)
    assert len(result["assessment_batches"]) == 1 and not result["comparisons"]
    assert not any(m.role == "assistant" for m in service.get_messages(task_id).items)
    assert not any(e.event_type == "comparison_saved" for e in service.store.list_events(operation.id, 0))


@pytest.mark.parametrize("moment", ["batch", "comparison"])
@pytest.mark.parametrize("mutation", ["requirements", "evidence"])
def test_changed_inputs_block_late_batches_and_comparisons(tmp_path, moment, mutation):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    fired = False
    def mutate(request):
        nonlocal fired
        if fired or request.phase != ("review_batch" if moment == "batch" else "comparison"):
            return None
        fired = True
        result = scripted_assessment(request) if request.phase == "review_batch" else comparison(request)
        if mutation == "requirements":
            update_task_preferences(service.config, task_id, "新要求", "上海256GB，预算4300")
        else:
            with connect(service.config.database_path) as conn:
                conn.execute("UPDATE listing_snapshots SET description='证据已更新'")
        return result
    operation = run_turn(service, task_id, ReviewRunner(mutate))
    assert operation.state == "failed"
    result = saved(service, task_id)
    assert not result["comparisons"]
    assert len(result["assessment_batches"]) == (0 if moment == "batch" else 1)
    assert result["reviews"][0]["stale"]


def test_cancellation_preserves_successful_batch_and_no_comparison(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    add_noise(service, task_id, 19)
    entered = threading.Event()
    seen = 0
    runner = ReviewRunner()
    def blocked(request):
        nonlocal seen
        if request.phase == "review_batch":
            seen += 1
            if seen == 2:
                entered.set()
                assert runner.cancelled.wait(5)
    runner.hook = blocked
    op = service.send_message(task_id, "重评全部").operation
    coordinator = OperationCoordinator(service, runner)
    try:
        coordinator.start(op.id)
        assert entered.wait(5)
        coordinator.cancel(op.id)
        wait_state(service.store, op.id, {"cancelled"})
    finally:
        coordinator.shutdown()
    result = saved(service, task_id)
    assert len(result["assessment_batches"]) == 1
    assert result["reviews"][0]["coverage"]["pending_count"] == 3
    assert not result["comparisons"]


def test_v1_assessment_table_migration_preserves_ids_and_snapshot(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    from test_web_preference_updates import ScriptedRunner
    run_turn(service, task_id, ScriptedRunner(scripted_assessment))
    with connect(service.config.database_path) as conn:
        old = dict(conn.execute("SELECT * FROM research_assessments").fetchone())
        declaration = conn.execute("SELECT sql FROM sqlite_master WHERE name='research_assessments'").fetchone()[0]
        legacy = declaration.replace("research_assessments", "legacy_assessments", 1)
        legacy = legacy.replace("  batch_index INTEGER NOT NULL DEFAULT 0,\n", "").replace("  candidate_ids_json TEXT NOT NULL DEFAULT '[]',\n", "")
        legacy = legacy.replace("  UNIQUE(operation_id, batch_index)", "  UNIQUE(operation_id)")
        conn.execute(legacy)
        columns = [key for key in old if key not in {"batch_index", "candidate_ids_json"}]
        conn.execute(f"INSERT INTO legacy_assessments ({','.join(columns)}) SELECT {','.join(columns)} FROM research_assessments")
        conn.execute("DROP TABLE research_assessments")
        conn.execute("ALTER TABLE legacy_assessments RENAME TO research_assessments")
    initialize(service.config.database_path)
    initialize(service.config.database_path)
    with connect(service.config.database_path) as conn:
        row = dict(conn.execute("SELECT * FROM research_assessments").fetchone())
        assert all(row[key] == old[key] for key in columns)
        assert row["batch_index"] == 0
        assert not list(conn.execute("PRAGMA foreign_key_check"))


def test_long_history_preference_permission_uses_database(tmp_path):
    service, task_id = ready_service(tmp_path)
    with connect(service.config.database_path) as conn:
        for _ in range(105):
            conn.execute("INSERT INTO conversation_messages (task_id,role,content,created_at) VALUES (?,'system','系统记录','fixture')", (task_id,))
    from test_web_preference_updates import ScriptedRunner
    runner = ScriptedRunner(change, AnswerResult(type="answer", content="已保存", candidate_ids=[]))
    assert run_turn(service, task_id, runner).state == "completed"
    assert runner.requests[0].allow_preference_update


def test_duplicate_batch_is_idempotent_and_conflicting_duplicate_is_rejected(tmp_path):
    from shopping_agent.conversation_store import InvalidActionRequestError
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    op = service.send_message(task_id, "重评历史").operation
    service.store.transition_operation(op.id, {"queued"}, "running")
    op = service.store.get_operation(op.id)
    coordinator = OperationCoordinator(service, ReviewRunner())
    initial = coordinator._build_request(task_id).model_copy(update={"trigger_message_id": op.user_message_id})
    intent = HistoryReviewResult(type="history_review", summary="重评", criteria=scripted_assessment(initial).research.criteria)
    review_id = service.store.begin_history_review(op.id, initial, intent)
    assert service.store.begin_history_review(op.id, initial, intent) == review_id
    request = coordinator._build_request(task_id, [1, 2, 3, 4]).model_copy(update={"phase": "review_batch", "trigger_message_id": op.user_message_id})
    answer = scripted_assessment(request)
    first = service.store.save_history_batch(op.id, review_id, request, answer)
    assert service.store.save_history_batch(op.id, review_id, request, answer) == first
    answer.research.assessments[0].summary = "不同结果"
    with pytest.raises(InvalidActionRequestError):
        service.store.save_history_batch(op.id, review_id, request, answer)
    result = saved(service, task_id)
    assert len(result["assessment_batches"]) == 1
    assert result["reviews"][0]["coverage"]["assessed_count"] == 4
    events = [e for e in service.store.list_events(op.id, 0) if "assessment_id" in e.payload]
    assert len(events) == 1


def test_interrupted_review_keeps_successes_and_comparison_retry_needs_no_batches(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    def stop_before_compare(request):
        if request.phase == "comparison":
            raise CodexTimeoutError("fixture")
    operation = run_turn(service, task_id, ReviewRunner(stop_before_compare))
    assert operation.state == "failed"
    # Simulate a crashed process's durable running record before startup recovery.
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE operations SET state='running',completed_at=NULL WHERE id=?", (operation.id,))
    coordinator = OperationCoordinator(ConversationService(service.config), ReviewRunner())
    coordinator.recover_interrupted()
    assert saved(service, task_id)["reviews"][0]["state"] == "interrupted"
    retry = ReviewRunner()
    assert run_turn(service, task_id, retry, "继续重评").state == "completed"
    assert [r.phase for r in retry.requests] == ["chat", "comparison"]
    assert len(saved(service, task_id)["assessment_batches"]) == 1


@pytest.mark.parametrize("kind", ["missing_candidate", "collection", "different_criteria"])
def test_bad_review_batch_stops_further_work_without_a_purchase_failure(tmp_path, kind):
    from shopping_agent.codex_runtime import ActionRequestResult
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    add_noise(service, task_id, 19)
    def bad(request):
        if request.phase != "review_batch":
            return None
        if kind == "collection":
            return ActionRequestResult(type="action_request", summary="抓详情", risk="访问平台", listing_ids=[1], actions=["detail"])
        answer = scripted_assessment(request)
        if kind == "missing_candidate":
            answer.research.assessments.pop()
        else:
            answer.research.criteria[0].description = "放宽预算"
        return answer
    runner = ReviewRunner(bad)
    operation = run_turn(service, task_id, runner)
    assert operation.state == "failed"
    result = saved(service, task_id)
    assert len([r for r in runner.requests if r.phase == "review_batch"]) == 1
    assert not result["assessment_batches"] and not result["comparisons"]
    assert result["reviews"][0]["coverage"]["pending_count"] == 23
    assert not service.get_action_requests(task_id).items


def test_empty_history_comparison_does_not_invent_candidates(tmp_path):
    service, task_id = ready_service(tmp_path)
    runner = ReviewRunner()
    assert run_turn(service, task_id, runner, "重评已保存候选").state == "completed"
    result = saved(service, task_id)
    assert result["comparisons"][0]["coverage"]["scope_count"] == 0
    assert result["comparisons"][0]["result"]["ranked_candidates"] == []
    assert [r.phase for r in runner.requests] == ["chat", "comparison"]


@pytest.mark.parametrize("kind", ["old_version_reference", "hard_failure", "lost_uncertainty", "missing_exit"])
def test_new_comparison_cannot_mix_versions_hide_unknowns_or_keep_rejected_candidate(tmp_path, kind):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    assert run_turn(service, task_id, ReviewRunner()).state == "completed"
    previous = saved(service, task_id)["comparisons"][0]
    old_assessment_id = saved(service, task_id)["assessment_batches"][0]["id"]
    def corrupt(request):
        if request.phase != "comparison":
            return None
        result = comparison(request).model_dump()
        if kind == "old_version_reference":
            result["ranked_candidates"][0]["assessment_id"] = old_assessment_id
        elif kind == "hard_failure":
            item = next(a for a in request.review_context["assessments"] if a["listing_id"] == 1)
            result["ranked_candidates"][0].update(listing_id=1, assessment_id=item["assessment_id"])
        elif kind == "lost_uncertainty":
            result["ranked_candidates"][1]["uncertainties"] = []
        else:
            result["changes"] = [c for c in result["changes"] if c["kind"] != "exited"]
        return result
    operation = run_turn(service, task_id, ReviewRunner(corrupt, update=True))
    assert operation.state == "failed"
    current = saved(service, task_id)
    assert len(current["comparisons"]) == 1 and current["comparisons"][0]["stale"]
    assert current["comparisons"][0]["result"] == previous["result"]
    assert current["reviews"][-1]["coverage"]["pending_count"] == 0


def test_evidence_change_prevents_reusing_a_partial_batch(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    add_noise(service, task_id, 19)
    seen = 0
    def fail(request):
        nonlocal seen
        if request.phase == "review_batch":
            seen += 1
            if seen == 2:
                raise CodexTimeoutError("fixture")
    run_turn(service, task_id, ReviewRunner(fail))
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE listing_snapshots SET description='新增已保存信息' WHERE listing_id=1")
    runner = ReviewRunner()
    assert run_turn(service, task_id, runner).state == "completed"
    assert [r.allowed_listing_ids for r in runner.requests if r.phase == "review_batch"] == [frozenset({1,21,22,23})]
    assert len([r for r in runner.requests if r.phase == "nomination"]) == 2
    assert saved(service, task_id)["assessment_batches"][0]["stale"]


def test_complete_review_can_return_no_eligible_candidates(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    def reject(request):
        if request.phase != "review_batch":
            return None
        answer = scripted_assessment(request)
        for item in answer.research.assessments:
            item.judgments[0].status = "NOT_MET"
            item.conclusion = "not_met"
        answer.candidate_ids = []
        return answer
    assert run_turn(service, task_id, ReviewRunner(reject)).state == "completed"
    result = saved(service, task_id)
    assert result["comparisons"][0]["result"]["ranked_candidates"] == []
    assert result["comparisons"][0]["coverage"]["assessed_count"] == 4


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_normal_api_persists_review_and_restores_comparison_in_new_app(tmp_path):
    from httpx import ASGITransport, AsyncClient
    from shopping_agent.web.app import create_app
    config = tmp_path / "config.toml"
    config.write_text(f'database_path = "{(tmp_path / "db.sqlite").as_posix()}"\n', encoding="utf-8")
    settings = tmp_path / "settings.json"
    class ApiRunner(ReviewRunner):
        def run(self, request, **kwargs):
            if request.phase == "chat" and len(request.messages) == 1:
                return AnswerResult(type="answer", content="已记录原始目标", candidate_ids=[])
            return super().run(request, **kwargs)
    app = create_app(config, settings)
    runner = ApiRunner()
    app.state.codex_runtime = runner
    async def finish(client, operation_id):
        for _ in range(300):
            op = (await client.get(f"/api/operations/{operation_id}")).json()["operation"]
            if op["state"] in {"completed", "failed"}:
                assert op["state"] == "completed", op
                return
            await asyncio.sleep(.01)
        raise AssertionError("operation did not finish")
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            first = (await client.post("/api/tasks", json={"message": ORIGINAL})).json()
            task_id = first["task"]["id"]
            await finish(client, first["operation"]["id"])
            initial = (await client.get(f"/api/tasks/{task_id}")).json()["research"]
            initial_comparisons = len(initial["comparisons"])
            seed_phones(app.state.conversation_service.config, task_id)
            response = (await client.post(f"/api/tasks/{task_id}/messages", json={"message": "重评历史候选"})).json()
            await finish(client, response["operation"]["id"])
            runner.update = True
            changed = (await client.post(f"/api/tasks/{task_id}/messages", json={"message": "预算到4300，电池90%，必须全原"})).json()
            await finish(client, changed["operation"]["id"])
            current = (await client.get(f"/api/tasks/{task_id}")).json()["research"]
            # Initial goal recording may already retain a comparison snapshot.
            # These two explicit review requests must append two more records.
            assert len(current["comparisons"]) == initial_comparisons + 2
            assert current["comparisons"][0]["stale"]
    restarted = create_app(config, settings)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(transport=ASGITransport(app=restarted), base_url="http://127.0.0.1") as client:
            restored = (await client.get(f"/api/tasks/{task_id}")).json()["research"]
            assert restored == current
