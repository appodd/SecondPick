import json
import threading
import time

import pytest

from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import ActionRequestInput
from shopping_agent.codex_runtime import AnswerResult, ActionRequestResult, CodexRuntime
from shopping_agent.operation_coordinator import OperationCoordinator
from test_web_services import seeded_web_config


class FakeRunner:
    build_request = CodexRuntime.build_request

    def __init__(self, result=None, block=False):
        self.result = result or AnswerResult(type="answer", content="Saved answer", candidate_ids=[])
        self.entered = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()

    def run(self, request, *, run_id, stage_callback):
        stage_callback("analyzing_evidence")
        self.entered.set()
        assert self.release.wait(5)
        return self.result

    def cancel(self, run_id):
        self.release.set()


@pytest.fixture
def service(tmp_path):
    return ConversationService(AppConfig(database_path=tmp_path / "test.sqlite"))


def wait_state(store, operation_id, expected):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        record = store.get_operation(operation_id)
        if record.state in expected:
            return record
        time.sleep(.01)
    raise AssertionError(f"Operation remained {record.state}")


def test_answer_is_saved_with_durable_completion(service):
    created = service.create_task("Find laptop")
    coordinator = OperationCoordinator(service, FakeRunner())
    coordinator.start(created.operation.id)
    wait_state(service.store, created.operation.id, {"completed"})
    assert [m.content for m in service.get_messages(created.task.id).items] == ["Find laptop", "Saved answer"]
    assert service.store.list_events(created.operation.id, 0)[-1].event_type == "completed"
    coordinator.shutdown()


def test_cancel_race_has_one_terminal_event_and_no_partial_answer(service):
    created = service.create_task("Find laptop")
    runner = FakeRunner(block=True)
    coordinator = OperationCoordinator(service, runner)
    coordinator.start(created.operation.id)
    assert runner.entered.wait(5)
    coordinator.cancel(created.operation.id)
    coordinator.cancel(created.operation.id)
    coordinator.shutdown()
    assert service.get_operation(created.operation.id).operation.state == "cancelled"
    assert len(service.get_messages(created.task.id).items) == 1
    events = service.store.list_events(created.operation.id, 0)
    assert [e.event_type for e in events if e.event_type in {"cancelled", "completed", "failed"}] == ["cancelled"]


@pytest.mark.parametrize("result", [
    ActionRequestResult(type="action_request", summary="Details", risk="Access", listing_ids=[999], actions=["detail"]),
    {"type": "action_request", "summary": "Bad", "risk": "Bad", "listing_ids": [], "actions": ["buy"]},
])
def test_invalid_result_creates_no_pending_request(service, result):
    created = service.create_task("Find laptop")
    coordinator = OperationCoordinator(service, FakeRunner(result))
    coordinator.start(created.operation.id)
    record = wait_state(service.store, created.operation.id, {"failed"})
    assert record.error_code == "invalid_codex_result"
    assert service.get_action_requests(created.task.id).items == []
    coordinator.shutdown()


@pytest.mark.parametrize("category,hint", [("rate_limit", "quota"), ("network", "connectivity"), ("untrusted-secret", "Saved work")])
def test_execution_failure_uses_only_allowlisted_diagnostic_hints(service, category, hint):
    from shopping_agent.codex_runtime import CodexExecutionError
    class FailedRunner(FakeRunner):
        def run(self, request, **kwargs):
            error = CodexExecutionError("raw private secret")
            error.diagnostics = {"failure_categories": [category], "message": "private secret"}
            raise error
    created = service.create_task("Find laptop")
    coordinator = OperationCoordinator(service, FailedRunner())
    coordinator.start(created.operation.id)
    record = wait_state(service.store, created.operation.id, {"failed"})
    coordinator.shutdown()
    assert record.error_code == "codex_execution_failed" and hint in record.error_detail
    assert "secret" not in record.error_detail and "private" not in record.error_detail
    assert len(service.get_messages(created.task.id).items) == 1


def test_recovery_interrupts_running_but_preserves_confirmation(service):
    first = service.create_task("First")
    service.store.transition_operation(first.operation.id, {"queued"}, "running")
    second = service.create_task("Second")
    service.store.transition_operation(second.operation.id, {"queued"}, "running")
    service.store.complete_with_action_request(second.operation.id, ActionRequestInput(summary="Search", risk="Access", actions=["search"], listing_ids=[]))
    OperationCoordinator(service, FakeRunner()).recover_interrupted()
    assert service.store.get_operation(first.operation.id).state == "interrupted"
    assert service.store.list_events(first.operation.id, 0)[-1].event_type == "interrupted"
    assert service.store.get_operation(second.operation.id).state == "waiting_confirmation"


def test_tasks_run_concurrently_and_shutdown_cancels(service):
    first, second = service.create_task("First"), service.create_task("Second")
    runner = FakeRunner(block=True)
    coordinator = OperationCoordinator(service, runner)
    coordinator.start(first.operation.id)
    coordinator.start(first.operation.id)
    coordinator.start(second.operation.id)
    wait_state(service.store, first.operation.id, {"running"})
    wait_state(service.store, second.operation.id, {"running"})
    coordinator.shutdown()
    assert service.store.get_operation(first.operation.id).state == "cancelled"
    assert service.store.get_operation(second.operation.id).state == "cancelled"


def test_request_includes_task_scoped_detail_evidence(seeded_web_config):
    service = ConversationService(seeded_web_config.config)
    coordinator = OperationCoordinator(service, FakeRunner())
    request = coordinator._build_request(seeded_web_config.task_id)
    from shopping_agent.match_semantics import MATCH_SEMANTICS
    assert request.messages[0].role == 'system' and request.messages[0].content == MATCH_SEMANTICS
    assert request.evidence
    serialized = request.model_dump_json()
    assert "xianyu_api_item_labels" in serialized
    assert "Outside candidate" not in serialized
    assert seeded_web_config.outside_listing_id not in request.allowed_listing_ids


def test_late_shortlist_and_captured_details_are_included_in_bounded_context(seeded_web_config, monkeypatch):
    from shopping_agent.db import connect, upsert_listing, add_listing_snapshot
    from shopping_agent.web.services import WorkbenchService

    config = seeded_web_config.config
    task_id = seeded_web_config.task_id
    service = ConversationService(config)
    run_id = WorkbenchService(config).get_task(task_id).runs[0].run_id
    with connect(config.database_path) as conn:
        for index in range(25):
            last_id = upsert_listing(conn, platform="xianyu", url=f"https://example.test/more/{index}")
            add_listing_snapshot(conn, listing_id=last_id, run_id=run_id,
                                 title=f"Candidate {index}", price_text="5000")
        conn.commit()
    operation = service.send_message(task_id, "Compare this shortlist").operation
    service.store.transition_operation(operation.id, {"queued"}, "running")
    service.store.complete_with_answer(operation.id, "Selected candidate", [last_id])
    original = WorkbenchService.get_candidates

    def captured_last(self, *args, **kwargs):
        page = original(self, *args, **kwargs)
        return page.model_copy(update={"candidates": sorted(page.candidates, key=lambda item: item.has_detail)})

    monkeypatch.setattr(WorkbenchService, "get_candidates", captured_last)
    request = OperationCoordinator(service, FakeRunner())._build_request(task_id)
    ids = [item.listing_id for item in request.evidence]
    assert len(ids) == 20
    assert ids[0] == last_id
    assert seeded_web_config.captured_listing_id in ids
    captured = next(item for item in request.evidence if item.listing_id == seeded_web_config.captured_listing_id)
    assert json.loads(captured.data["evidence_json"])["detail"]["attributes_source"] == "xianyu_api_item_labels"
    assert seeded_web_config.outside_listing_id not in ids


def test_sidebar_restores_latest_operation_state(service):
    from shopping_agent.web.services import WorkbenchService
    created = service.create_task("Find camera")
    items = WorkbenchService(service.config).list_tasks().items
    assert items[0].operation_state == "queued"
    service.store.transition_with_event(created.operation.id, {"queued"}, "interrupted")
    assert WorkbenchService(service.config).list_tasks().items[0].operation_state == "interrupted"
