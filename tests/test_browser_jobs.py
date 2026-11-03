import asyncio
import threading

import pytest

from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import ActionRequestInput, OperationConflictError
from shopping_agent.browser_jobs import BrowserJobStore, BrowserJobCoordinator, BrowserJobError


@pytest.fixture
def service(tmp_path):
    return ConversationService(AppConfig(database_path=tmp_path / "jobs.sqlite"))


def approved_request(service, actions=None, listing_ids=None):
    created = service.create_task("Find a camera")
    service.store.transition_operation(created.operation.id, {"queued"}, "running")
    request = service.store.complete_with_action_request(created.operation.id, ActionRequestInput(
        summary="Search", risk="Access platform", actions=actions or ["search"], listing_ids=listing_ids or []))
    service.approve_action(created.task.id, request.id)
    return request


def test_requires_approval_and_explicit_valid_scope(service):
    request = approved_request(service)
    store = BrowserJobStore(service.config)
    with pytest.raises(BrowserJobError):
        store.create_collection(request.task_id + 1, request.id, "Camera", 1)
    with pytest.raises(BrowserJobError):
        store.create_collection(request.task_id, request.id, "", 1)
    job = store.create_collection(request.task_id, request.id, "Camera", 1)
    assert job["query"] == "Camera"
    assert job["request_id"] == request.id
    assert job["state"] == "queued"
    # Duplicate HTTP submission returns the same execution, never another browser.
    assert store.create_collection(request.task_id, request.id, "Camera", 1)["id"] == job["id"]
    with pytest.raises(BrowserJobError):
        store.create_collection(request.task_id, request.id, "Different", 1)


def test_cooldown_summary_explains_zero_new_records_without_echoing_raw_error(service):
    request = approved_request(service)
    store = BrowserJobStore(service.config)
    job = store.create_collection(request.task_id, request.id, "Camera", 1)
    store.finish(job["id"], "failed", error_code="search_cooldown",
                 error_detail="搜索冷却中，还需等待 1629 秒。 secret-error-body")
    from shopping_agent.db import connect
    with connect(service.config.database_path) as conn:
        text = conn.execute("SELECT content FROM conversation_messages WHERE task_id=? AND role='system' ORDER BY id DESC LIMIT 1",
                            (request.task_id,)).fetchone()[0]
    assert "本次已保存 0 条" in text
    assert "本次未进入平台搜索" in text and "1629 秒" in text
    assert "已有商品记录仍保留" in text
    assert "secret-error-body" not in text


def test_global_browser_exclusion_and_same_task_message_exclusion(service):
    request = approved_request(service)
    store = BrowserJobStore(service.config)
    store.create_collection(request.task_id, request.id, "Camera", 1)
    with pytest.raises(BrowserJobError):
        store.create_login()
    with pytest.raises(OperationConflictError):
        service.send_message(request.task_id, "Analyze")


def test_active_codex_and_unsupported_actions_cannot_execute(service):
    request = approved_request(service)
    service.send_message(request.task_id, "Analyze")
    store = BrowserJobStore(service.config)
    with pytest.raises(BrowserJobError):
        store.create_collection(request.task_id, request.id, "Camera", 1)


class FakeBrowser:
    def __init__(self):
        self.started = threading.Event()
        self.cleaned = threading.Event()

    async def run(self, job, store, config):
        self.started.set()
        try:
            await asyncio.sleep(30)
        finally:
            self.cleaned.set()
        return {"run_ids": [], "listing_count": 0}


def test_cancellation_cleans_up_before_releasing_browser(service):
    store = BrowserJobStore(service.config)
    backend = FakeBrowser()
    coordinator = BrowserJobCoordinator(store, backend)
    job = store.create_login()
    coordinator.start(job["id"])
    assert backend.started.wait(3)
    coordinator.cancel(job["id"])
    coordinator.shutdown()
    assert backend.cleaned.is_set()
    assert store.get(job["id"])["state"] == "cancelled"
    assert store.create_login()["state"] == "queued"


def test_restart_interrupts_browser_jobs_without_reexecution(service):
    store = BrowserJobStore(service.config)
    job = store.create_login()
    store.recover_interrupted()
    assert store.get(job["id"])["state"] == "interrupted"
    assert store.get(job["id"])["error_code"] == "service_restarted"


@pytest.mark.parametrize("decision", [None, "reject"])
def test_unapproved_requests_never_create_browser_jobs(service, decision):
    created = service.create_task("Camera")
    service.store.transition_operation(created.operation.id, {"queued"}, "running")
    request = service.store.complete_with_action_request(created.operation.id, ActionRequestInput(
        summary="Search", risk="Access", actions=["search"], listing_ids=[]))
    if decision:
        service.reject_action(created.task.id, request.id)
    store = BrowserJobStore(service.config)
    with pytest.raises(BrowserJobError) as error:
        store.create_collection(created.task.id, request.id, "Camera", 1)
    assert error.value.code == "approval_required"
    assert store.status()["active_job"] is None


def test_retry_cannot_change_scope_or_repeat_completed_collection(service):
    request = approved_request(service)
    store = BrowserJobStore(service.config)
    job = store.create_collection(request.task_id, request.id, "Camera", 1)
    store.finish(job["id"], "failed")
    with pytest.raises(BrowserJobError):
        store.create_collection(request.task_id, request.id, "Other", 1, retry_of=job["id"])
    retried = store.create_collection(request.task_id, request.id, "Camera", 1, retry_of=job["id"])
    assert retried["id"] != job["id"]
    assert store.create_collection(request.task_id, request.id, "Camera", 1, retry_of=job["id"])["id"] == retried["id"]
    store.finish(retried["id"], "completed")
    with pytest.raises(BrowserJobError):
        store.create_collection(request.task_id, request.id, "Camera", 1, retry_of=retried["id"])


def test_unsupported_actions_do_not_start_even_after_approval(service):
    request = approved_request(service, actions=["search", "media"])
    store = BrowserJobStore(service.config)
    with pytest.raises(BrowserJobError) as error:
        store.create_collection(request.task_id, request.id, "Camera", 1)
    assert error.value.code == "unsupported_action"
    assert store.status()["active_job"] is None
