"""Bounded task summaries and immutable pagination watermarks, with full goals."""
import base64
import json

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.db import connect, create_search_run, attach_run_to_task, add_listing_snapshot, upsert_listing
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.tasks import build_task_summary, update_task_preferences
from shopping_agent.web.app import create_app
from shopping_agent.web.services import WorkbenchService
from test_web_preference_updates import ready_service, ORIGINAL, run_turn
from test_history_review import ReviewRunner
from test_requirement_sources_and_history_pages import LegacyRunner
from test_structured_assessments import seed_phones


@pytest.fixture
def populated(tmp_path):
    service, task_id = ready_service(tmp_path)
    for n in range(23):
        update_task_preferences(service.config, task_id, f"修订 {n}", f"完整目标 {n}", added_preferences=[f"偏好 {n}"], removed_preferences=[f"偏好 {n-1}"] if n else [])
        with connect(service.config.database_path) as conn:
            run = create_search_run(conn, goal=f"轮次 {n}", city="上海")
            attach_run_to_task(conn, task_id=task_id, run_id=run)
            listing = upsert_listing(conn, platform="xianyu", url=f"https://example.test/{n%5}")
            add_listing_snapshot(conn, listing_id=listing, run_id=run, title=f"候选 {n}")
            for q in range(3):
                conn.execute("INSERT INTO queries(run_id,platform,query_text,created_at) VALUES (?,'xianyu',?,'fixture')", (run, f"查询 {n}/{q}"))
            conn.execute("INSERT INTO saved_reports(task_id,run_id,title,format,path,created_at) VALUES (?, ?, ?, 'md', 'private/not-exposed.md', 'fixture')", (task_id, run, f"报告 {n}"))
    return service, task_id


def test_task_detail_bounds_every_history_without_changing_current_state_or_coverage(populated):
    service, task_id = populated
    detail = WorkbenchService(service.config).get_task(task_id)
    full = build_task_summary(service.config, task_id)
    assert len(detail.preference_revisions) == len(detail.runs) == len(detail.reports) == 10
    assert detail.history_page.total_counts == dict(preference_revisions=23, runs=23, reports=23)
    assert detail.task.effective_goal == "完整目标 22"
    assert detail.preference_revision_id == full["preference_revisions"][-1]["id"]
    assert detail.current_preferences == ["偏好 22"]
    assert detail.task.original_goal == ORIGINAL
    aggregate = detail.search_coverage.model_dump()
    aggregate.pop("runs")
    assert aggregate == {k: v for k, v in full["search_coverage"].items() if k != "runs"}
    assert [r.model_dump() for r in detail.search_coverage.runs] == full["search_coverage"]["runs"][-10:]
    assert "private/not-exposed.md" not in detail.model_dump_json()
    assert len(full["reports"]) == 23  # CLI/export contract stays complete.


def test_fixed_pages_are_complete_after_appends_and_restart(populated):
    service, task_id = populated
    wb = WorkbenchService(service.config)
    page = wb.get_task_history(task_id, 4)
    expected = {k: list(range(1, 24)) for k in ("preference_revisions", "runs", "reports")}
    seen = {key: [] for key in expected}
    update_task_preferences(service.config, task_id, "追加", "最新目标")
    with connect(service.config.database_path) as conn:
        run = create_search_run(conn, goal="追加", city="上海")
        attach_run_to_task(conn, task_id=task_id, run_id=run)
        conn.execute("INSERT INTO saved_reports(task_id,title,format,path,created_at) VALUES (?, '追加', 'md', 'private', 'fixture')", (task_id,))
    while True:
        for key in expected:
            records = getattr(page, key)
            assert len(records) <= 4
            seen[key].extend(r.run_id if key == "runs" else r.id for r in records)
        assert page.history_page.total_counts == dict(preference_revisions=23, runs=23, reports=23)
        if not page.history_page.next_cursor:
            break
        wb = WorkbenchService(service.config)
        page = wb.get_task_history(task_id, 4, page.history_page.next_cursor)
    for key in expected:
        assert sorted(seen[key]) == expected[key]
    assert wb.get_task(task_id).task.effective_goal == "最新目标"
    assert wb.get_task_history(task_id).history_page.total_counts["runs"] == 24


@pytest.mark.parametrize("kind", ["garbage", "task", "bool", "negative", "large", "extra", "deep"])
def test_history_cursor_rejects_invalid_input_and_task_confusion(populated, kind):
    service, task_id = populated
    wb = WorkbenchService(service.config)
    token = wb.get_task_history(task_id, 2).history_page.next_cursor
    data = json.loads(base64.urlsafe_b64decode(token))
    if kind == "task": data["task_id"] += 1
    if kind == "bool": data["before"]["runs"] = True
    if kind == "negative": data["upper"]["reports"] = -1
    if kind == "large": data["upper"]["reports"] = 2**63
    if kind == "extra": data["extra"] = 1
    token = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    if kind == "garbage": token = "not-a-cursor"
    if kind == "deep": token = base64.urlsafe_b64encode(("["*1100 + "0" + "]"*1100).encode()).decode()
    with pytest.raises(ValueError, match="Invalid task history"):
        wb.get_task_history(task_id, 2, token)


def test_empty_task_and_page_limits(tmp_path):
    service, task_id = ready_service(tmp_path)
    wb = WorkbenchService(service.config)
    page = wb.get_task_history(task_id)
    assert page.history_page.total_counts == dict(preference_revisions=0, runs=0, reports=0)
    assert not page.history_page.has_more
    assert wb.get_task(task_id).preference_revision_id == 0
    for limit in [0, 21, True]:
        with pytest.raises(ValueError): wb.get_task_history(task_id, limit)
    with pytest.raises(ValueError): wb.get_task_history(99999)


def test_old_preference_delta_remains_effective_outside_recent_page(populated):
    service, task_id = populated
    with connect(service.config.database_path) as conn:
        conn.execute("UPDATE task_preference_revisions SET added_preferences_json='[\"old retained\"]',removed_preferences_json='[]' WHERE id=1")
    detail = WorkbenchService(service.config).get_task(task_id)
    assert "old retained" in detail.current_preferences and len(detail.preference_revisions) == 10


def test_per_run_query_previews_and_preference_list_have_explicit_limits(populated):
    service, task_id = populated
    with connect(service.config.database_path) as conn:
        for n in range(30):
            conn.execute("INSERT INTO queries(run_id,platform,query_text,created_at) VALUES (23,'xianyu',?,'fixture')", (f"extra{n}",))
    update_task_preferences(service.config, task_id, "大量偏好", "完整目标保持", added_preferences=[f"item{n}" for n in range(60)])
    detail = WorkbenchService(service.config).get_task(task_id)
    run = detail.runs[-1]
    assert run.query_count == 33 and len(run.source_queries) == 20 and run.source_queries_truncated
    assert len(detail.current_preferences) == 50 and detail.current_preferences_truncated
    assert detail.task.effective_goal == "完整目标保持"


def test_runtime_reads_referenced_old_revision_by_id_instead_of_recent_page(tmp_path):
    service, task_id = ready_service(tmp_path)
    seed_phones(service.config, task_id)
    first = update_task_preferences(service.config, task_id, "最早需求", ORIGINAL)
    assert run_turn(service, task_id, LegacyRunner()).state == "completed"
    for n in range(25): update_task_preferences(service.config, task_id, f"后续{n}", ORIGINAL)
    runner = ReviewRunner()
    request = OperationCoordinator(service, runner)._build_request(task_id)
    assert request.task.preference_revision_id > first
    assert request.requirement_sources[f"preference_revision:{first}"]["text"] == ORIGINAL
    assert len(WorkbenchService(service.config).get_task(task_id).preference_revisions) == 10


@pytest.mark.anyio
async def test_api_pages_are_scoped_and_do_not_expose_report_paths(populated, tmp_path):
    service, task_id = populated
    config = tmp_path / "config.toml"
    config.write_text(f'database_path = "{service.config.database_path.as_posix()}"\n', encoding="utf-8")
    async with AsyncClient(transport=ASGITransport(app=create_app(config, settings_path=tmp_path / "settings.json")), base_url="http://127.0.0.1") as client:
        detail = (await client.get(f"/api/tasks/{task_id}")).json()
        assert len(detail["runs"]) == 10
        page = await client.get(f"/api/tasks/{task_id}/history", params={"limit": 2})
        assert page.status_code == 200 and len(page.json()["reports"]) == 2
        assert "private/not-exposed.md" not in page.text
        other = service.create_task("另一任务")
        cursor = page.json()["history_page"]["next_cursor"]
        assert (await client.get(f"/api/tasks/{other.task.id}/history", params={"cursor": cursor})).status_code == 400
        assert (await client.get(f"/api/tasks/{task_id}/history", params={"limit": 21})).status_code == 422


@pytest.fixture
def anyio_backend(): return "asyncio"
