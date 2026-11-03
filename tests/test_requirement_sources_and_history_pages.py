"""Legacy requirement provenance and bounded history through normal services/API."""
import base64
import json

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.assessment import Criterion
from shopping_agent.codex_runtime import CodexTimeoutError
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.db import connect, create_research_task
from shopping_agent.history_review import HistoryReviewResult
from shopping_agent.tasks import update_task_preferences
from shopping_agent.web.app import create_app
from shopping_agent.web.services import WorkbenchService
from test_history_review import ReviewRunner
from test_structured_assessments import seed_phones, scripted_assessment
from test_web_preference_updates import ready_service, run_turn, ScriptedRunner, ORIGINAL, UPDATED, change


class LegacyRunner(ReviewRunner):
    def run(self, request, **kwargs):
        if request.phase == "chat":
            self.requests.append(request)
            criteria = scripted_assessment(request).research.criteria
            ref = f"preference_revision:{request.task.preference_revision_id}" if request.task.preference_revision_id else "task_goal"
            for criterion in criteria:
                criterion.source_message_ids = []
                criterion.source_refs = [ref]
            return HistoryReviewResult(type="history_review", summary="用已保存需求初始化旧任务标准", criteria=criteria)
        return super().run(request, **kwargs)


def legacy_service(tmp_path):
    service = ConversationService(AppConfig(database_path=tmp_path / "legacy.sqlite"))
    with connect(service.config.database_path) as conn:
        task_id = create_research_task(conn, title="旧CLI任务", goal=ORIGINAL, city="上海")
    seed_phones(service.config, task_id)
    return service, task_id


@pytest.mark.parametrize("revised", [False, True], ids=["original-task-goal", "saved-cli-revision"])
def test_legacy_task_initializes_without_fabricating_user_messages(tmp_path, revised):
    service, task_id = legacy_service(tmp_path)
    revision = update_task_preferences(service.config, task_id, "CLI修改预算与电池", UPDATED) if revised else 0
    runner = LegacyRunner()
    operation = run_turn(service, task_id, runner, "重评这个旧任务的候选")
    assert operation.state == "completed", operation
    detail = WorkbenchService(service.config).get_task(task_id)
    assert len(service.get_messages(task_id).items) == 2  # Current request + answer only.
    assert service.get_messages(task_id).items[0].content == "重评这个旧任务的候选"
    assert detail.task.original_goal == ORIGINAL
    assert detail.task.effective_goal == (UPDATED if revised else ORIGINAL)
    assert len(detail.research.standards) == 1
    for criterion in detail.research.standards[0].criteria:
        assert criterion.source_message_ids == []
        assert criterion.source_refs == ([f"preference_revision:{revision}"] if revised else ["task_goal"])
    assert runner.requests[0].allow_preference_update  # A follow-up to an already saved CLI goal.
    assert "task_goal" in runner.requests[0].requirement_sources
    restored = WorkbenchService(ConversationService(service.config).config).get_task(task_id)
    assert restored.research == detail.research
    assert run_turn(service, task_id, LegacyRunner(), "继续核对原有要求").state == "completed"
    assert len(WorkbenchService(service.config).get_task(task_id).research.standards) == 1


def test_first_web_followup_can_change_a_saved_cli_goal_without_fake_initial_message(tmp_path):
    service, task_id = legacy_service(tmp_path)
    class ChangedLegacyRunner(LegacyRunner):
        def run(self, request, **kwargs):
            if request.phase == "chat" and request.allow_preference_update:
                self.requests.append(request)
                return change(request)
            return super().run(request, **kwargs)
    runner = ChangedLegacyRunner()
    operation = run_turn(service, task_id, runner, "预算改为4300，电池至少90%，必须原装")
    assert operation.state == "completed", operation
    detail = WorkbenchService(service.config).get_task(task_id)
    assert detail.task.original_goal == ORIGINAL and detail.task.effective_goal == UPDATED
    assert len(detail.preference_revisions) == 1
    assert len(service.get_messages(task_id).items) == 2
    assert runner.requests[0].allow_preference_update and not runner.requests[1].allow_preference_update
    assert all(c.source_refs == [f"preference_revision:{detail.preference_revisions[0].id}"] for c in detail.research.standards[0].criteria)


@pytest.mark.parametrize("ref", ["task_goal:2", "preference_revision:9999", "preference_revision:0", "invented", ""])
def test_unknown_requirement_sources_do_not_create_a_standard(tmp_path, ref):
    service, task_id = legacy_service(tmp_path)
    def invalid(request):
        criteria = [c.model_dump() for c in scripted_assessment(request).research.criteria]
        for item in criteria:
            item.update(source_message_ids=[], source_refs=[ref])
        return dict(type="history_review", summary="无效来源", criteria=criteria)
    operation = run_turn(service, task_id, ScriptedRunner(invalid))
    assert operation.state == "failed" and operation.error_code == "invalid_codex_result"
    detail = WorkbenchService(service.config).get_task(task_id)
    assert not detail.research.standards
    assert not detail.research.reviews
    assert detail.task.original_goal == ORIGINAL


def test_foreign_revision_cannot_initialize_this_task(tmp_path):
    service, task_id = legacy_service(tmp_path)
    other = service.create_task("另一任务")
    foreign_revision = update_task_preferences(service.config, other.task.id, "修改", "另一要求")
    def invalid(request):
        criteria = scripted_assessment(request).research.criteria
        for item in criteria:
            item.source_message_ids = []
            item.source_refs = [f"preference_revision:{foreign_revision}"]
        return HistoryReviewResult(type="history_review", summary="外任务来源", criteria=criteria)
    assert run_turn(service, task_id, ScriptedRunner(invalid)).state == "failed"
    assert not WorkbenchService(service.config).get_task(task_id).research.standards


def test_failed_legacy_initialization_preserves_goal_and_no_fake_standard(tmp_path):
    service, task_id = legacy_service(tmp_path)
    assert run_turn(service, task_id, ScriptedRunner(CodexTimeoutError("fixture"))).state == "failed"
    detail = WorkbenchService(service.config).get_task(task_id)
    assert detail.task.original_goal == ORIGINAL and not detail.research.standards
    assert len(service.get_messages(task_id).items) == 1


def test_original_goal_reference_must_match_the_server_saved_source(tmp_path):
    from shopping_agent.operation_coordinator import OperationCoordinator
    from shopping_agent.conversation_store import InvalidActionRequestError
    service, task_id = legacy_service(tmp_path)
    op = service.send_message(task_id, "提炼原有标准").operation
    service.store.transition_operation(op.id, {"queued"}, "running")
    request = OperationCoordinator(service, LegacyRunner())._build_request(task_id)
    research = scripted_assessment(request).research
    for criterion in research.criteria:
        criterion.source_message_ids = []
        criterion.source_refs = ["task_goal"]
    forged = request.model_copy(update={"requirement_sources": {"task_goal": {"text": "伪造原始预算"}}})
    with pytest.raises(InvalidActionRequestError):
        service.store.complete_with_answer(op.id, "不应保存", [], research=research, research_request=forged,
                                           expected_preference_revision_id=0)
    assert not WorkbenchService(service.config).get_task(task_id).research.standards
    assert WorkbenchService(service.config).get_task(task_id).task.original_goal == ORIGINAL


@pytest.mark.parametrize("limit", [0, 21, True])
def test_history_page_size_is_validated_at_service_boundary(tmp_path, limit):
    service, task_id = legacy_service(tmp_path)
    with pytest.raises(ValueError, match="limit"):
        WorkbenchService(service.config).get_research_history(task_id, limit)


@pytest.fixture(scope="module")
def history_template(tmp_path_factory):
    root = tmp_path_factory.mktemp("bounded-history-template")
    service, task_id = ready_service(root)
    seed_phones(service.config, task_id)
    for _ in range(12):
        assert run_turn(service, task_id, ReviewRunner(), "重评历史").state == "completed"
    for _ in range(12):
        assert run_turn(service, task_id, ScriptedRunner(scripted_assessment), "比较已有候选").state == "completed"
    return service.config, task_id


@pytest.fixture
def populated(tmp_path, history_template):
    config, task_id = history_template
    copied = tmp_path / "history.sqlite"
    with connect(config.database_path) as source, connect(copied) as target:
        source.backup(target)
    service = ConversationService(AppConfig(database_path=copied))
    return service, task_id


def test_task_response_and_research_pages_are_bounded_and_complete(populated):
    service, task_id = populated
    workbench = WorkbenchService(service.config)
    detail = workbench.get_task(task_id)
    assert len(detail.research.assessment_batches) == len(detail.research.reviews) == len(detail.research.comparisons) == 10
    assert detail.research.page.has_more
    assert detail.research.page.total_counts.model_dump() == dict(assessment_batches=13, reviews=12, comparisons=12)
    cursor = None
    seen = {key: [] for key in ("assessment_batches", "reviews", "comparisons")}
    for _ in range(20):
        page = workbench.get_research_history(task_id, limit=2, cursor=cursor)
        for key in seen:
            values = getattr(page, key)
            assert len(values) <= 2
            seen[key].extend(item.id for item in values)
        cursor = page.page.next_cursor
        if cursor is None:
            break
    assert cursor is None
    for key, ids in seen.items():
        assert len(ids) == len(set(ids)) == getattr(detail.research.page.total_counts, key)
    first_id = min(seen["assessment_batches"])
    batch = workbench.get_assessment(task_id, first_id)
    assert batch.id == first_id
    # Only references actually cited by judgments are returned, not the entire prompt.
    used = {ref for a in batch.result.assessments for j in a.judgments for ref in j.evidence_refs}
    assert set(batch.evidence_refs) == used
    assert "input_json" not in batch.model_dump()


def test_keyset_cursor_keeps_original_watermark_when_new_records_arrive(populated):
    service, task_id = populated
    workbench = WorkbenchService(service.config)
    first = workbench.get_research_history(task_id, limit=2)
    watermark_ids = [a.id for a in first.assessment_batches]
    assert run_turn(service, task_id, ScriptedRunner(scripted_assessment)).state == "completed"
    new_page = workbench.get_research_history(task_id, limit=2)
    newest = new_page.assessment_batches[-1].id
    assert newest > max(watermark_ids)
    cursor = first.page.next_cursor
    while cursor:
        page = workbench.get_research_history(task_id, 2, cursor)
        assert page.page.total_counts.assessment_batches == 13
        watermark_ids.extend(a.id for a in page.assessment_batches)
        cursor = page.page.next_cursor
    assert len(watermark_ids) == len(set(watermark_ids)) == 13
    assert newest not in watermark_ids


@pytest.mark.parametrize("changed", ["requirements", "evidence"])
def test_older_pages_keep_their_watermark_but_use_current_validity(populated, changed):
    service, task_id = populated
    workbench = WorkbenchService(service.config)
    first = workbench.get_research_history(task_id, 2)
    if changed == "requirements":
        update_task_preferences(service.config, task_id, "修改要求", UPDATED)
    else:
        with connect(service.config.database_path) as conn:
            conn.execute("UPDATE listing_snapshots SET description='新增保存证据' WHERE listing_id=1")
    next_page = workbench.get_research_history(task_id, 2, first.page.next_cursor)
    assert next_page.page.total_counts == first.page.total_counts
    assert all(item.stale for item in [*next_page.assessment_batches, *next_page.reviews, *next_page.comparisons])
    if changed == "requirements":
        assert next_page.page.preference_revision_id > first.page.preference_revision_id
    else:
        assert next_page.page.evidence_signature != first.page.evidence_signature
    assert all(item.evidence_signature == first.page.evidence_signature for item in next_page.comparisons)


@pytest.mark.parametrize("mutation", ["garbage", "deep_json", "wrong_task", "boolean_id", "boolean_bound", "negative_position", "too_large", "extra_key"])
def test_malformed_or_cross_task_cursor_is_rejected(populated, mutation):
    service, task_id = populated
    workbench = WorkbenchService(service.config)
    cursor = workbench.get_research_history(task_id, 2).page.next_cursor
    data = json.loads(base64.urlsafe_b64decode(cursor))
    if mutation == "garbage":
        cursor = "%%%"
    elif mutation == "deep_json":
        cursor = base64.urlsafe_b64encode(("["*1100 + "0" + "]"*1100).encode()).decode()
    else:
        if mutation == "wrong_task": data["task_id"] = task_id+1
        elif mutation == "boolean_id": data["task_id"] = True
        elif mutation == "boolean_bound": data["upper"]["reviews"] = True
        elif mutation == "negative_position": data["before"]["reviews"] = -1
        elif mutation == "too_large": data["upper"]["reviews"] = 2**80
        else: data["unexpected"] = "field"
        cursor = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    with pytest.raises(ValueError, match="cursor"):
        workbench.get_research_history(task_id, 2, cursor)


def test_older_message_only_standard_is_compatible_without_rewriting_it(populated):
    service, task_id = populated
    with connect(service.config.database_path) as conn:
        row = conn.execute("SELECT * FROM requirement_standards WHERE task_id=?", (task_id,)).fetchone()
        criteria = json.loads(row["criteria_json"])
        for item in criteria:
            item.pop("source_refs", None)
        old_json = json.dumps(criteria, ensure_ascii=False)
        conn.execute("UPDATE requirement_standards SET criteria_json=? WHERE id=?", (old_json, row["id"]))
    assert run_turn(service, task_id, ScriptedRunner(scripted_assessment)).state == "completed"
    with connect(service.config.database_path) as conn:
        assert conn.execute("SELECT criteria_json FROM requirement_standards WHERE id=?", (row["id"],)).fetchone()[0] == old_json
        assert conn.execute("SELECT COUNT(*) FROM requirement_standards WHERE task_id=?", (task_id,)).fetchone()[0] == 1


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_history_api_paging_restart_scope_and_direct_reference(populated, tmp_path):
    service, task_id = populated
    other = service.create_task("同库不同任务")
    config = tmp_path / "config.toml"
    config.write_text(f'database_path = "{service.config.database_path.as_posix()}"\n', encoding="utf-8")
    settings = tmp_path / "settings.json"
    app = create_app(config, settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            response = await client.get(f"/api/tasks/{task_id}/research?limit=2")
            assert response.status_code == 200
            first = response.json()
            cursor = first["page"]["next_cursor"]
            assessment_id = first["comparisons"][0]["result"]["ranked_candidates"][0]["assessment_id"]
            assert assessment_id not in [a["id"] for a in first["assessment_batches"]]
            direct = await client.get(f"/api/tasks/{task_id}/research/assessments/{assessment_id}")
            assert direct.status_code == 200 and direct.json()["id"] == assessment_id
            assert (await client.get(f"/api/tasks/{other.task.id}/research/assessments/{assessment_id}")).status_code == 404
            assert (await client.get(f"/api/tasks/{other.task.id}/research", params={"cursor": cursor})).status_code == 400
            assert (await client.get(f"/api/tasks/99999/research")).status_code == 404
            assert (await client.get(f"/api/tasks/{task_id}/research?limit=21")).status_code == 422
    restarted = create_app(config, settings)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(transport=ASGITransport(app=restarted), base_url="http://127.0.0.1") as client:
            next_page = await client.get(f"/api/tasks/{task_id}/research", params={"limit": 2, "cursor": cursor})
            assert next_page.status_code == 200
            assert {a["id"] for a in next_page.json()["assessment_batches"]}.isdisjoint(a["id"] for a in first["assessment_batches"])
