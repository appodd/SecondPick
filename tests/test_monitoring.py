import threading
import time

import pytest

from shopping_agent.browser_jobs import BrowserJobStore, BrowserJobError
from shopping_agent.config import AppConfig
from shopping_agent.db import connect, create_research_task
from shopping_agent.monitoring import MonitorStore, MonitorCoordinator, MonitorError


@pytest.fixture
def store(tmp_path):
    value = MonitorStore(AppConfig(database_path=tmp_path / "test.sqlite"))
    with connect(value.config.database_path) as conn:
        value.task_id = create_research_task(conn, "手柄", "NS2 Pro", "上海")
        value.other_task = create_research_task(conn, "另一任务", "其他", "北京")
    return value


def create(store, **kwargs):
    return store.create(store.task_id, keyword="NS2 Pro", confirmed=True, **kwargs)


def test_confirmation_scope_and_idempotent_submissions(store):
    with pytest.raises(MonitorError):
        store.create(store.task_id, keyword="NS2 Pro", confirmed=1)
    with pytest.raises(MonitorError):
        create(store, max_pages=51)
    with pytest.raises(MonitorError):
        create(store, max_items=True)
    with pytest.raises(MonitorError):
        store.create(999, keyword="NS2 Pro", confirmed=True)
    first = create(store)
    assert create(store)["id"] == first["id"]
    assert first["state"] == "waiting"
    assert first["max_items"] == 100


def test_seller_profile_permission_is_explicit_immutable_scope(store):
    first = create(store)
    assert first["collect_seller_profiles"] is False
    with pytest.raises(MonitorError):
        create(store, collect_seller_profiles=1)
    expanded = create(store, collect_seller_profiles=True)
    assert expanded["id"] != first["id"]
    assert expanded["collect_seller_profiles"] is True
    assert create(store, collect_seller_profiles=True)["id"] == expanded["id"]
    assert len(store.list(store.task_id)) == 2


def test_additive_migration_preserves_existing_monitor_scope(tmp_path):
    import sqlite3
    from shopping_agent.db import SCHEMA, initialize
    config = AppConfig(database_path=tmp_path / "legacy.sqlite")
    old_schema = SCHEMA.replace("  collect_seller_profiles INTEGER NOT NULL DEFAULT 0,\n", "").replace("  seller_json TEXT NOT NULL DEFAULT '{}',\n", "")
    with sqlite3.connect(config.database_path) as conn:
        conn.executescript(old_schema)
        task_id = create_research_task(conn, "手柄", "NS2 Pro", "上海")
        conn.execute("""INSERT INTO monitors(task_id,keyword,max_pages,max_items,interval_seconds,max_rounds,state,created_at,updated_at)
            VALUES(?,'NS2 Pro',10,100,1800,24,'paused','test','test')""", (task_id,))
    initialize(config.database_path)
    row = MonitorStore(config).list(task_id)[0]
    assert row["state"] == "paused" and row["collect_seller_profiles"] is False
    with connect(config.database_path) as conn:
        assert "seller_json" in {r["name"] for r in conn.execute("PRAGMA table_info(monitor_import_records)")}


def test_due_claim_is_global_and_excludes_old_browser_jobs(store):
    first = create(store)
    store.create(store.other_task, keyword="其他", confirmed=True)
    claimed = store.claim_due()
    assert claimed["id"] == first["id"]
    assert store.claim_due() is None
    with pytest.raises(BrowserJobError, match="监控"):
        BrowserJobStore(store.config).create_login()
    store.finish(first["id"], dict(imported=3, error_code=None))
    assert store.claim_due()["task_id"] == store.other_task


def test_old_browser_job_prevents_monitor_claim(store):
    create(store)
    browser = BrowserJobStore(store.config)
    job = browser.create_login()
    assert store.claim_due() is None
    browser.finish(job["id"], "cancelled")
    assert store.claim_due() is not None


def test_wait_interval_and_round_budget_survive_recreation(store):
    monitor = create(store, max_rounds=2, interval_seconds=60)
    store.claim_due()
    store.finish(monitor["id"], dict(imported=5, error_code=None))
    fresh = MonitorStore(store.config)
    result = fresh.list(store.task_id)[0]
    assert result["imported"] == 5 and result["rounds"] == 1
    assert result["state"] == "waiting" and result["next_run_at"]
    assert fresh.claim_due() is None
    with fresh.transaction() as conn:
        conn.execute("UPDATE monitors SET next_run_at='2000-01-01' WHERE id=?", (monitor["id"],))
    fresh.claim_due()
    fresh.finish(monitor["id"], dict(imported=2, error_code=None))
    result = fresh.list(store.task_id)[0]
    assert result["state"] == "stopped" and result["imported"] == 7
    with pytest.raises(MonitorError):
        fresh.control(store.task_id, monitor["id"], "resume")


def test_search_card_stats_and_unique_pool_count_persist_without_becoming_detail_counts(store):
    monitor = create(store)
    store.claim_due()
    result = dict(imported=0, search_cards={"imported": 405}, candidate_pool_count=405,
                  price_observations={"imported": 404}, error_code=None)
    store.finish(monitor["id"], result)
    row = MonitorStore(store.config).list(store.task_id)[0]
    assert row["result"] == result
    assert row["imported"] == 0  # Legacy cumulative detail-stage snapshot count.
    assert row["result"]["candidate_pool_count"] == 405


def test_restart_recovers_committed_live_import_before_progress_publication(store, tmp_path):
    import json
    from shopping_agent.goofish_import import import_goofish_jsonl
    from test_goofish_import import product
    monitor = create(store)
    store.claim_due()
    source = f"shopping-monitor-{monitor['id']}"
    path = tmp_path / "live.jsonl"
    records = [product(任务名称=source), product(124, 任务名称=source, _collection_stage="search_card",
                _source_round_id="round-1")]
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    import_goofish_jsonl(store.config, path=path, task_id=store.task_id, keyword="NS2 Pro", source_task=source,
                        incremental=True)
    # Simulate process loss before result_json/accounting was published.
    fresh = MonitorStore(store.config)
    fresh.recover_interrupted()
    recovered = fresh.list(store.task_id)[0]
    assert recovered["state"] == "paused" and recovered["imported"] == 1
    fresh.recover_interrupted()
    assert fresh.list(store.task_id)[0]["imported"] == 1
    fresh.control(store.task_id, monitor["id"], "resume")
    fresh.claim_due()
    fresh.finish(monitor["id"], dict(imported=0, error_code=None))
    assert fresh.list(store.task_id)[0]["imported"] == 1


def test_pause_keeps_global_ownership_until_process_exit_and_retains_partial_data(store):
    monitor = create(store)
    store.claim_due()
    row = store.control(store.task_id, monitor["id"], "pause")
    assert row["state"] == "running" and row["desired_state"] == "paused"
    assert store.requested_stop(monitor["id"])
    assert store.claim_due() is None
    with pytest.raises(MonitorError):
        store.control(store.task_id, monitor["id"], "resume")
    store.finish(monitor["id"], dict(imported=4, error_code="cancelled"))
    assert store.list(store.task_id)[0]["state"] == "paused"
    assert store.list(store.task_id)[0]["imported"] == 4
    assert store.control(store.task_id, monitor["id"], "resume")["state"] == "waiting"


def test_stopped_scope_requires_explicit_resume_and_keeps_budget_and_data(store):
    monitor = create(store)
    store.claim_due()
    store.control(store.task_id, monitor["id"], "stop")
    store.control(store.task_id, monitor["id"], "pause")
    with pytest.raises(MonitorError):
        store.control(store.task_id, monitor["id"], "resume")
    store.finish(monitor["id"], dict(imported=3, error_code="cancelled"))
    fresh = MonitorStore(store.config)
    fresh.recover_interrupted()
    stopped = fresh.list(store.task_id)[0]
    assert stopped["state"] == "stopped" and fresh.claim_due() is None
    resumed = fresh.control(store.task_id, monitor["id"], "resume")
    assert resumed["state"] == "waiting" and resumed["error_code"] is None
    assert resumed["rounds"] == 1 and resumed["imported"] == 3
    assert resumed["result"] == stopped["result"]
    for key in ("id", "task_id", "keyword", "max_pages", "max_items", "max_rounds", "interval_seconds", "collect_seller_profiles"):
        assert resumed[key] == monitor[key]
    assert fresh.control(store.task_id, monitor["id"], "resume")["next_run_at"] == resumed["next_run_at"]
    assert fresh.claim_due()["id"] == monitor["id"]


def test_failure_waits_for_user_and_scope_is_task_isolated(store):
    monitor = create(store)
    store.claim_due()
    store.finish(monitor["id"], dict(imported=1, error_code="login_required"))
    assert store.claim_due() is None
    assert store.list(store.task_id)[0]["state"] == "needs_attention"
    with pytest.raises(MonitorError):
        store.control(store.other_task, monitor["id"], "resume")
    assert store.control(store.task_id, monitor["id"], "resume")["error_code"] is None


def test_restart_pauses_active_and_waiting_authorizations(store):
    first = create(store)
    store.claim_due()
    store.create(store.other_task, keyword="另一关键词", confirmed=True)
    store.recover_interrupted()
    assert store.list(store.task_id)[0]["state"] == "paused"
    assert store.list(store.other_task)[0]["state"] == "paused"
    assert store.list(store.task_id)[0]["error_code"] == "service_restarted"
    assert store.claim_due() is None


class BlockingEngine:
    def __init__(self):
        self.started = threading.Event()
        self.cleaned = threading.Event()

    def run(self, monitor, stop):
        self.started.set()
        stop.wait(10)
        self.cleaned.set()
        return dict(imported=2, error_code="cancelled")


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    pytest.fail("Condition not reached")


def test_coordinator_pause_cancels_worker_and_keeps_saved_results(store):
    monitor = create(store)
    engine = BlockingEngine()
    coordinator = MonitorCoordinator(store, engine)
    coordinator.start()
    try:
        assert engine.started.wait(5)
        store.control(store.task_id, monitor["id"], "pause")
        wait_for(lambda: store.list(store.task_id)[0]["state"] == "paused")
        assert engine.cleaned.is_set()
        assert store.list(store.task_id)[0]["imported"] == 2
    finally:
        coordinator.shutdown()


def test_shutdown_cancels_inflight_work_before_returning(store):
    create(store)
    engine = BlockingEngine()
    coordinator = MonitorCoordinator(store, engine)
    coordinator.start()
    assert engine.started.wait(5)
    coordinator.shutdown()
    assert engine.cleaned.is_set() and not coordinator.thread.is_alive()
    assert store.list(store.task_id)[0]["state"] == "paused"


def test_automatic_rounds_observe_interval_pause_resume_and_budget(store):
    from datetime import datetime, timedelta, timezone
    clock = [datetime(2026, 10, 20, tzinfo=timezone.utc)]
    fresh = MonitorStore(store.config, clock=lambda: clock[0])
    monitor = fresh.create(store.task_id, keyword="手柄", max_rounds=3, interval_seconds=60, confirmed=True)
    class Engine:
        calls = 0
        def run(self, monitor, stop):
            self.calls += 1
            return dict(imported=1, error_code=None)
    engine = Engine()
    coordinator = MonitorCoordinator(fresh, engine, poll_interval=.01)
    coordinator.start()
    try:
        wait_for(lambda: fresh.list(store.task_id)[0]["rounds"] == 1)
        assert fresh.list(store.task_id)[0]["next_run_at"] == (clock[0] + timedelta(seconds=60)).isoformat()
        clock[0] += timedelta(seconds=59)
        time.sleep(.04)
        assert engine.calls == 1
        clock[0] += timedelta(seconds=1)
        wait_for(lambda: fresh.list(store.task_id)[0]["rounds"] == 2)
        fresh.control(store.task_id, monitor["id"], "pause")
        clock[0] += timedelta(days=1)
        time.sleep(.04)
        assert engine.calls == 2
        fresh.control(store.task_id, monitor["id"], "resume")
        wait_for(lambda: fresh.list(store.task_id)[0]["state"] == "stopped")
        row = fresh.list(store.task_id)[0]
        assert row["rounds"] == row["imported"] == engine.calls == 3
        assert row["next_run_at"] is None
        fresh.recover_interrupted()
        assert fresh.list(store.task_id)[0]["state"] == "stopped"
    finally:
        coordinator.shutdown()


def test_transient_database_busy_does_not_repeat_a_platform_round(store, monkeypatch):
    import sqlite3
    monitor = create(store, max_rounds=1)
    claim, finish = store.claim_due, store.finish
    failures = {"claim": 0, "finish": 0}
    def busy_claim():
        if failures["claim"] == 0:
            failures["claim"] += 1
            raise sqlite3.OperationalError("database is locked")
        return claim()
    def busy_finish(*args):
        finish(*args)
        if failures["finish"] == 0:
            failures["finish"] += 1
            raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(store, "claim_due", busy_claim)
    monkeypatch.setattr(store, "finish", busy_finish)
    class Engine:
        calls = 0
        def run(self, monitor, stop):
            self.calls += 1
            return dict(imported=2, error_code=None)
    engine = Engine()
    coordinator = MonitorCoordinator(store, engine, poll_interval=.01)
    coordinator.start()
    try:
        wait_for(lambda: store.list(store.task_id)[0]["state"] == "stopped")
        time.sleep(.04)
        assert coordinator.thread.is_alive() and engine.calls == 1
        row = store.list(store.task_id)[0]
        assert row["rounds"] == 1 and row["imported"] == 2 and failures == {"claim": 1, "finish": 1}
    finally:
        coordinator.shutdown()


def test_lost_stop_control_channel_cancels_active_collection(store, monkeypatch):
    import sqlite3
    create(store)
    def unavailable(*args):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(store, "requested_stop", unavailable)
    engine = BlockingEngine()
    coordinator = MonitorCoordinator(store, engine, poll_interval=.01)
    coordinator.start()
    try:
        wait_for(lambda: store.list(store.task_id)[0]["state"] == "needs_attention")
        assert engine.cleaned.is_set()
        assert store.list(store.task_id)[0]["error_code"] == "engine_sync_failed"
    finally:
        coordinator.shutdown()
