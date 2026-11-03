from datetime import datetime, timedelta, timezone

import pytest

from shopping_agent.browser_jobs import BrowserJobStore, BrowserJobCoordinator, BrowserJobError
from shopping_agent.config import AppConfig
from shopping_agent.db import connect


def test_audit_is_durable_bounded_and_counts_across_executions(tmp_path):
    config = AppConfig(database_path=tmp_path / "audit.sqlite")
    store = BrowserJobStore(config)
    first = store.create_login()
    store.record_attempt(first["id"], {"operation": "login", "page_kind": "home"})
    store.finish(first["id"], "completed")
    store.finish(first["id"], "completed")
    second = store.create_login()
    store.record_attempt(second["id"], {"operation": "login", "page_kind": "account"})
    saved = BrowserJobStore(config).events(second["id"])["items"]
    assert saved[0]["metadata"]["recent_attempt_count_30m"] == 2
    assert saved[0]["metadata"]["since_previous_attempt_ms"] >= 0
    assert [event["event_type"] for event in store.events(first["id"])["items"]] == ["page_attempt", "job_finished"]
    assert store.events(first["id"], 1)["has_more"] is True
    assert store.events(first["id"], 1)["items"][0]["event_type"] == "job_finished"
    with connect(config.database_path) as conn:
        conn.execute("UPDATE browser_job_events SET created_at=? WHERE job_id=? AND event_type='page_attempt'",
                     ((datetime.now(timezone.utc)-timedelta(minutes=40)).isoformat(), first["id"]))
    store.record_attempt(second["id"], {"operation": "login"})
    assert store.events(second["id"])["items"][-1]["metadata"]["recent_attempt_count_30m"] == 2


def test_audit_rejects_sensitive_or_unstructured_metadata_and_records_restart(tmp_path):
    store = BrowserJobStore(AppConfig(database_path=tmp_path / "audit.sqlite"))
    job = store.create_login()
    with pytest.raises(ValueError):
        store.record_event(job["id"], "verification_required", {"cookie": "must-not-store"})
    with pytest.raises(ValueError):
        store.record_event(job["id"], "verification_check", {"cleared": {"token": "must-not-store"}})
    assert store.events(job["id"])["items"] == []
    store.recover_interrupted()
    assert store.events(job["id"])["items"][-1]["metadata"] == {"state": "interrupted", "error_code": "service_restarted"}
    with pytest.raises(BrowserJobError):
        store.events(999)
