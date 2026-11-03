import time

import pytest

from shopping_agent.browser_jobs import BrowserJobCoordinator, BrowserJobStore, BrowserJobError
from shopping_agent.codex_runtime import ActionRequestResult, AnswerResult
from shopping_agent.operation_coordinator import OperationCoordinator
from test_browser_jobs import approved_request, service
from test_operation_coordinator import FakeRunner, wait_state


def test_collection_completion_atomically_queues_one_system_continuation(service):
    action = approved_request(service)
    store = BrowserJobStore(service.config)
    job = store.create_collection(action.task_id, action.id, "Camera", 1)
    operation_id = store.finish(job["id"], "completed", {"listing_count": 3, "run_ids": []}, continue_research=True)
    assert store.get(job["id"])["analysis_operation_id"] == operation_id
    assert service.store.get_operation(operation_id).state == "queued"
    messages = service.get_messages(action.task_id).items
    assert messages[-1].role == "system" and messages[-1].operation_id == operation_id
    assert not any(message.role == "user" and "3" in message.content for message in messages)
    assert store.analyze(job["id"]) == operation_id
    assert store.finish(job["id"], "completed", continue_research=True) is None
    assert len(service.get_messages(action.task_id).items) == len(messages)


@pytest.mark.parametrize("state", ["failed", "cancelled", "interrupted"])
def test_failed_or_stopped_collection_does_not_resume_research(service, state):
    action = approved_request(service)
    store = BrowserJobStore(service.config)
    job = store.create_collection(action.task_id, action.id, "Camera", 1)
    assert store.finish(job["id"], state, continue_research=True) is None
    assert store.get(job["id"])["analysis_operation_id"] is None
    with pytest.raises(BrowserJobError):
        store.analyze(job["id"])


def test_late_stop_wins_over_automatic_analysis(service):
    action = approved_request(service)
    store = BrowserJobStore(service.config)
    job = store.create_collection(action.task_id, action.id, "Camera", 1)
    store.update(job["id"], stop_requested=True)
    assert store.finish(job["id"], "completed", continue_research=True) is None
    assert store.get(job["id"])["state"] == "cancelled"
    assert store.get(job["id"])["analysis_operation_id"] is None


def test_successful_browser_worker_automatically_runs_reasoning(service):
    action = approved_request(service)
    store = BrowserJobStore(service.config)
    seen = []
    class Runner(FakeRunner):
        def run(self, request, **kwargs):
            seen.append(request)
            return super().run(request, **kwargs)
    class Browser:
        async def run(self, job, store, config):
            return {"listing_count": 0, "run_ids": []}
    reasoning = OperationCoordinator(service, Runner(AnswerResult(type="answer", content="这一轮没有商品，建议调整搜索范围。", candidate_ids=[])))
    browser = BrowserJobCoordinator(store, Browser(), reasoning)
    job = store.create_collection(action.task_id, action.id, "Camera", 1)
    browser.start(job["id"])
    until = time.monotonic() + 5
    operation_id = None
    while time.monotonic() < until:
        operation_id = store.get(job["id"])["analysis_operation_id"]
        if operation_id:
            break
        time.sleep(.01)
    assert operation_id
    wait_state(service.store, operation_id, {"completed"})
    assert seen[0].messages[-1].role == "system"
    assert service.get_messages(action.task_id).items[-1].content == "这一轮没有商品，建议调整搜索范围。"
    browser.shutdown()
    reasoning.shutdown()


def test_model_findings_and_search_suggestions_are_persisted(service):
    created = service.create_task("找 iPhone 15 Pro")
    result = ActionRequestResult(type="action_request", summary="补充商品搜索", risk="访问平台",
        actions=["search"], listing_ids=[], analysis="先覆盖不同容量，随后比较机况与价格。",
        search_query="iPhone 15 Pro 256G 国行", max_pages=2)
    coordinator = OperationCoordinator(service, FakeRunner(result))
    coordinator.start(created.operation.id)
    wait_state(service.store, created.operation.id, {"waiting_confirmation"})
    request = service.get_action_requests(created.task.id).items[0]
    assert request.search_query == "iPhone 15 Pro 256G 国行" and request.max_pages == 2
    assert service.get_messages(created.task.id).items[-1].content == result.analysis
    assert BrowserJobStore(service.config).status()["active_job"] is None
    coordinator.shutdown()
