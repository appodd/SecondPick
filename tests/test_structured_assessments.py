"""Isolated product flow with scripted judgments, not a model-quality evaluation."""
import asyncio
import copy

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.assessment import ResearchResult, input_refs
from shopping_agent.codex_runtime import AnswerResult
from shopping_agent.codex_runtime import RESULT_SCHEMA_JSON, CodexTimeoutError
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import (connect, create_search_run, attach_run_to_task,
                               upsert_listing, add_listing_snapshot)
from shopping_agent.web.app import create_app
from shopping_agent.web.services import WorkbenchService
from test_web_preference_updates import ScriptedRunner, ready_service, run_turn, change, ORIGINAL
from test_web_services import seeded_web_config


def seed_phones(config, task_id, *, include_c=True):
    with connect(config.database_path) as conn:
        run = create_search_run(conn, goal=ORIGINAL, city="上海")
        attach_run_to_task(conn, task_id=task_id, run_id=run)
        for name, price, battery, city in [("A", 3500, 89, "上海"), ("B", 3750, 92, "上海"), ("C", 4200, 95, "上海"), ("D", 3650, 94, "苏州")]:
            if name == "C" and not include_c:
                continue
            listing = upsert_listing(conn, platform="xianyu", url=f"https://example.test/{name}")
            add_listing_snapshot(conn, listing_id=listing, run_id=run,
                title=f"{name} iPhone 15 Pro 256GB", price_text=str(price), location=city,
                description=f"电池{battery}%；" + ("维修史未说明" if name == "B" else "卖家称全原无修"))


def scripted_assessment(request):
    """Deterministic fixture output; never included in the runtime's input."""
    updated = "4300" in request.task.effective_goal
    relaxed = "接受官方换屏" in request.task.effective_goal
    first_source = next(m.id for m in request.messages if m.role == "user")
    source = request.trigger_message_id if updated or relaxed else first_source
    criteria = [
        dict(criterion_id="budget", description=f"预算不超过{4300 if updated else 3800}元", priority="hard", source_message_ids=[source]),
        dict(criterion_id="battery", description=f"电池至少{90 if updated and not relaxed else 88}%", priority="hard", source_message_ids=[source]),
        dict(criterion_id="capacity", description="256GB", priority="hard", source_message_ids=[first_source]),
        dict(criterion_id="location", description="上海面交", priority="hard", source_message_ids=[first_source]),
        dict(criterion_id="originality", description="接受官方换屏" if relaxed else "必须全原，换屏不要" if updated else "尽量原装", priority="hard" if updated and not relaxed else "soft", source_message_ids=[source]),
    ]
    if request.current_criteria:
        criteria = [c.model_dump() for c in request.current_criteria]
    assessments = []
    for card in request.candidates:
        # The fixture IDs are assigned by storage, not assumed by the adapter.
        name = next(n for n in "ABCD" if f"{n} iPhone" in card.data["evidence_json"])
        refs = [ref for ref, data in input_refs(request).items() if data["listing_id"] == card.listing_id and ref.startswith("card:")]
        statuses = dict(budget="NOT_MET" if name == "C" and not updated else "MET",
            battery="NOT_MET" if name == "A" and updated and not relaxed else "MET",
            capacity="MET", location="NOT_MET" if name == "D" else "MET",
            originality="UNKNOWN" if name == "B" else "MET")
        failed = any(statuses[c["criterion_id"]] == "NOT_MET" for c in criteria if c["priority"] == "hard")
        assessments.append(dict(listing_id=card.listing_id,
            judgments=[dict(criterion_id=c["criterion_id"], status=statuses[c["criterion_id"]],
                reason="维修史没有说明，需核实" if c["criterion_id"] == "originality" and name == "B" else "依据已保存的虚构卡片信息，未经独立验机",
                source_type="missing" if c["criterion_id"] == "originality" and name == "B" else "seller_claim",
                evidence_refs=[] if c["criterion_id"] == "originality" and name == "B" else refs) for c in criteria],
            conclusion="not_met" if failed else "conditional", summary=f"{name} 的夹具判断，尚需验机"))
    return AnswerResult(type="answer", content="根据已保存证据逐项比较，未知仍需核实。",
        candidate_ids=[a["listing_id"] for a in assessments if a["conclusion"] != "not_met"][:4],
        research=ResearchResult.model_validate(dict(criteria=criteria, assessments=assessments)))


def history(service, task_id):
    data = WorkbenchService(service.config).get_task(task_id).research.model_dump()
    return {key: data[key] for key in ("standards", "assessment_batches")}


@pytest.mark.parametrize("include_c", [True, False], ids=["M1-R1-R3-V3", "V6-no-invented-C"])
def test_four_candidates_revisions_and_restart(tmp_path, include_c):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id, include_c=include_c)
    assert run_turn(service, task_id, ScriptedRunner(scripted_assessment), "逐项比较候选").state == "completed"
    original = history(service, task_id)
    assert len(original["standards"]) == 1
    # M1 round 2: ordinary follow-up reuses the exact standard, no new preference revision.
    assert run_turn(service, task_id, ScriptedRunner(scripted_assessment), "B比A贵250值得吗？").state == "completed"
    assert len(history(service, task_id)["standards"]) == 1
    assert run_turn(service, task_id, ScriptedRunner(change, scripted_assessment)).state == "completed"
    saved = history(ConversationService(service.config), task_id)
    assert len(saved["standards"]) == 2
    assert saved["standards"][0]["stale"] and not saved["standards"][1]["stale"]
    assert [b["stale"] for b in saved["assessment_batches"]] == [True, True, False]
    batch = saved["assessment_batches"][-1]
    assert len(batch["result"]["assessments"]) == (4 if include_c else 3)
    judged = batch["result"]["assessments"]
    assert judged[0]["judgments"][1]["status"] == "NOT_MET"  # A battery
    assert judged[1]["judgments"][-1]["status"] == "UNKNOWN"  # B repairs
    assert judged[-1]["judgments"][3]["status"] == "NOT_MET"  # D city
    if include_c:
        assert judged[2]["conclusion"] == "conditional"
        assert original["assessment_batches"][0]["result"]["assessments"][2]["conclusion"] == "not_met"
    def relax(request):
        update = change(request)
        return update.model_copy(update={"effective_goal": "上海256GB，预算4300，电池至少88%，接受官方换屏",
            "added_preferences": ["电池至少88%", "接受官方换屏"], "removed_preferences": ["电池至少90%", "必须全原"]})
    assert run_turn(service, task_id, ScriptedRunner(relax, scripted_assessment), "电池放宽到88%，接受有记录的官方换屏").state == "completed"
    relaxed = history(service, task_id)["assessment_batches"][-1]
    assert relaxed["result"]["assessments"][0]["conclusion"] == "conditional"
    assert relaxed["result"]["assessments"][1]["judgments"][-1]["status"] == "UNKNOWN"


@pytest.mark.parametrize("corrupt", ["cross_candidate", "missing_ref", "foreign_source", "unknown_criterion", "contradiction", "blank_reason"])
def test_invalid_assessment_rolls_back_answer_standard_and_events(tmp_path, corrupt):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    def bad(request):
        result = scripted_assessment(request).model_dump()
        item = result["research"]["assessments"][0]
        if corrupt == "cross_candidate":
            item["judgments"][0]["evidence_refs"] = [next(ref for ref, data in input_refs(request).items() if data["listing_id"] != item["listing_id"])]
        elif corrupt == "missing_ref":
            item["judgments"][0]["evidence_refs"] = ["invented"]
        elif corrupt == "foreign_source":
            result["research"]["criteria"][0]["source_message_ids"] = [99999]
        elif corrupt == "unknown_criterion":
            item["judgments"][0]["criterion_id"] = "invented"
        elif corrupt == "contradiction":
            item["judgments"][0]["status"] = "UNKNOWN"
            item["conclusion"] = "consider"
        else:
            item["judgments"][0]["reason"] = " "
        return result
    operation = run_turn(service, task_id, ScriptedRunner(bad))
    assert operation.state == "failed" and operation.error_code == "invalid_codex_result"
    assert history(service, task_id) == {"standards": [], "assessment_batches": []}
    assert not any(m.role == "assistant" for m in service.get_messages(task_id).items)
    assert not any(e.event_type == "assessments_saved" for e in service.store.list_events(operation.id, 0))


def test_evidence_change_blocks_late_result_and_marks_saved_judgment_stale(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    assert run_turn(service, task_id, ScriptedRunner(scripted_assessment)).state == "completed"
    def change_evidence(request):
        result = scripted_assessment(request)
        with connect(service.config.database_path) as conn:
            conn.execute("UPDATE listing_snapshots SET description = '新增证据' WHERE listing_id = ?", (request.candidates[0].listing_id,))
        return result
    assert run_turn(service, task_id, ScriptedRunner(change_evidence)).state == "failed"
    saved = history(service, task_id)
    assert len(saved["assessment_batches"]) == 1
    assert saved["assessment_batches"][0]["stale"]
    # Saved reference still contains its original excerpt, never the new evidence.
    assert "新增证据" not in str(saved["assessment_batches"][0]["evidence_refs"])


def test_standard_is_immutable_within_revision_and_other_task_is_isolated(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    run_turn(service, task_id, ScriptedRunner(scripted_assessment))
    before = copy.deepcopy(history(service, task_id))
    def rewrite(request):
        result = scripted_assessment(request).model_dump()
        result["research"]["criteria"][0]["description"] = "预算随意"
        return result
    assert run_turn(service, task_id, ScriptedRunner(rewrite)).state == "failed"
    assert history(service, task_id) == before
    other = service.create_task("另一个任务，预算不同")
    assert history(service, other.task.id) == {"standards": [], "assessment_batches": []}


def test_conflict_is_preserved_with_multiple_input_references(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    def conflicting(request):
        result = scripted_assessment(request).model_dump()
        candidate = result["research"]["assessments"][1]
        judgment = candidate["judgments"][2]
        judgment.update(status="CONFLICT", source_type="inference", reason="冲突处理契约夹具，不代表真实证据识别",
            evidence_refs=[ref for ref, data in input_refs(request).items() if data["listing_id"] == candidate["listing_id"]])
        return result
    assert run_turn(service, task_id, ScriptedRunner(conflicting)).state == "completed"
    saved = history(service, task_id)["assessment_batches"][0]
    assert saved["result"]["assessments"][1]["judgments"][2]["status"] == "CONFLICT"
    assert saved["result"]["assessments"][1]["conclusion"] == "conditional"


def test_saved_preferences_survive_failure_without_a_fabricated_new_standard(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    run_turn(service, task_id, ScriptedRunner(scripted_assessment))
    operation = run_turn(service, task_id, ScriptedRunner(change, CodexTimeoutError("fixture")))
    assert operation.state == "failed" and "要求已保存" in operation.error_detail
    saved = history(service, task_id)
    assert len(saved["standards"]) == 1 and saved["standards"][0]["stale"]
    assert len(saved["assessment_batches"]) == 1 and saved["assessment_batches"][0]["stale"]


def test_standards_only_answer_does_not_claim_candidate_evaluation(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    def criteria_only(request):
        answer = scripted_assessment(request)
        answer.research.assessments = []
        answer.candidate_ids = []
        return answer
    assert run_turn(service, task_id, ScriptedRunner(criteria_only)).state == "completed"
    saved = history(service, task_id)
    assert len(saved["standards"]) == 1
    assert saved["assessment_batches"][0]["result"]["assessments"] == []


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_api_restores_structured_assessment_after_new_app(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f'database_path = "{(tmp_path / "db.sqlite").as_posix()}"\n', encoding="utf-8")
    settings = tmp_path / "settings.json"
    app = create_app(config, settings)
    app.state.codex_runtime = ScriptedRunner(AnswerResult(type="answer", content="等待候选", candidate_ids=[]), scripted_assessment)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            first = (await client.post("/api/tasks", json={"message": ORIGINAL})).json()
            task_id = first["task"]["id"]
            async def finish(op_id):
                for _ in range(300):
                    op = (await client.get(f"/api/operations/{op_id}")).json()["operation"]
                    if op["state"] in {"completed", "failed"}:
                        assert op["state"] == "completed", op
                        return
                    await asyncio.sleep(.01)
                raise AssertionError("not completed")
            await finish(first["operation"]["id"])
            seed_phones(app.state.conversation_service.config, task_id)
            turn = (await client.post(f"/api/tasks/{task_id}/messages", json={"message": "请逐项评估"})).json()
            await finish(turn["operation"]["id"])
            saved = (await client.get(f"/api/tasks/{task_id}")).json()["research"]
            assert len(saved["assessment_batches"][0]["result"]["assessments"]) == 4
    restarted = create_app(config, settings)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(transport=ASGITransport(app=restarted), base_url="http://127.0.0.1") as client:
            assert (await client.get(f"/api/tasks/{task_id}")).json()["research"] == saved


def test_runtime_json_schema_refs_resolve_at_document_root():
    import json
    schema = json.loads(RESULT_SCHEMA_JSON)
    def visit(value):
        if isinstance(value, dict):
            if "$ref" in value:
                target = schema
                for key in value["$ref"].removeprefix("#/").split("/"):
                    target = target[key]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(schema)


def test_saved_detail_file_change_invalidates_input(seeded_web_config):
    from shopping_agent.assessment import evidence_signature
    from pathlib import Path
    config = seeded_web_config.config
    with connect(config.database_path) as conn:
        before = evidence_signature(conn, seeded_web_config.task_id)
        path = conn.execute("SELECT text_path FROM detail_snapshots LIMIT 1").fetchone()[0]
        Path(path).write_text("证据文件已更改", encoding="utf-8")
        assert evidence_signature(conn, seeded_web_config.task_id) != before


@pytest.mark.parametrize("failure", ["timeout", "cancel", "revision_changed"])
def test_incomplete_analysis_never_saves_a_failed_purchase_judgment(tmp_path, failure):
    from shopping_agent.operation_coordinator import OperationCoordinator
    from shopping_agent.tasks import update_task_preferences
    from test_operation_coordinator import wait_state
    import threading
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    run_turn(service, task_id, ScriptedRunner(scripted_assessment))
    def failed(request):
        if failure == "timeout":
            raise CodexTimeoutError("fixture")
        result = scripted_assessment(request)
        update_task_preferences(service.config, task_id, "预算修改", "上海256GB，预算4300")
        return result
    if failure == "cancel":
        entered, released = threading.Event(), threading.Event()
        class Blocked(ScriptedRunner):
            def cancel(self, run_id):
                released.set()
        def blocked(request):
            entered.set()
            assert released.wait(5)
            return scripted_assessment(request)
        coordinator = OperationCoordinator(service, Blocked(blocked))
        operation = service.send_message(task_id, "再次评估").operation
        try:
            coordinator.start(operation.id)
            assert entered.wait(5)
            coordinator.cancel(operation.id)
            wait_state(service.store, operation.id, {"cancelled"})
        finally:
            coordinator.shutdown()
    else:
        assert run_turn(service, task_id, ScriptedRunner(failed)).state == "failed"
    batches = history(service, task_id)["assessment_batches"]
    assert len(batches) == 1
    assert batches[0]["execution_state"] == "succeeded"
    assert batches[0]["stale"] == (failure == "revision_changed")


def test_additive_migration_on_database_copy_preserves_legacy_data(tmp_path):
    from shopping_agent.config import AppConfig
    from shopping_agent.db import initialize
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    copied = tmp_path / "legacy-copy.sqlite"
    with connect(service.config.database_path) as source, connect(copied) as target:
        source.backup(target)
    with connect(copied) as conn:
        conn.execute("DROP TABLE research_assessments")
        conn.execute("DROP TABLE requirement_standards")
        before = [tuple(row) for row in conn.execute("SELECT * FROM conversation_messages")]
    initialize(copied)
    initialize(copied)
    with connect(copied) as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM conversation_messages")] == before
        assert conn.execute("SELECT COUNT(*) FROM listing_snapshots").fetchone()[0] == 4
    restored = WorkbenchService(AppConfig(database_path=copied)).get_task(task_id)
    assert restored.task.original_goal == ORIGINAL
    assert restored.research.assessment_batches == []


def test_context_never_attaches_old_standard_to_new_preference_revision(tmp_path, monkeypatch):
    from shopping_agent.operation_coordinator import OperationCoordinator
    from shopping_agent.tasks import update_task_preferences
    import shopping_agent.operation_coordinator as coordinator_module
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    run_turn(service, task_id, ScriptedRunner(scripted_assessment))
    original_read = coordinator_module.read_standards
    def concurrent_update(conn, requested_task_id):
        standards = original_read(conn, requested_task_id)
        update_task_preferences(service.config, task_id, "预算提高", "上海256GB，预算4300")
        return standards
    monkeypatch.setattr(coordinator_module, "read_standards", concurrent_update)
    request = OperationCoordinator(service, ScriptedRunner())._build_request(task_id)
    assert request.task.preference_revision_id > 0
    assert not request.current_criteria
    assert request.previous_criteria
