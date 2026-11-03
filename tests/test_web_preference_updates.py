"""Real API/store path with deterministic model outputs; no platform access."""
import asyncio
import threading

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.codex_runtime import (
    AnswerResult, ActionRequestResult, CodexRuntime, CodexTimeoutError,
    InvalidCodexResult, PreferenceUpdateResult,
)
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import InvalidActionRequestError
from shopping_agent.operation_coordinator import OperationCoordinator
from shopping_agent.tasks import build_task_summary, update_task_preferences
from shopping_agent.web.app import create_app
from test_operation_coordinator import wait_state


ORIGINAL = "iPhone 15 Pro 256GB，上海面交，预算3800，电池至少88%，尽量原装"
UPDATED = "iPhone 15 Pro 256GB，上海面交，预算4300，电池至少90%，必须全原，换屏不要"


def change(request):
    return PreferenceUpdateResult(
        type="preference_update", source_message_id=request.trigger_message_id,
        base_revision_id=request.task.preference_revision_id, effective_goal=UPDATED,
        added_preferences=["预算4300", "电池至少90%", "必须全原，换屏不要"],
        removed_preferences=["预算3800", "电池至少88%", "尽量原装"],
    )


class ScriptedRunner:
    build_request = CodexRuntime.build_request

    def __init__(self, *steps):
        self.steps = iter(steps)
        self.requests = []

    def run(self, request, *, run_id, stage_callback):
        self.requests.append(request)
        stage_callback("analyzing_evidence")
        result = next(self.steps)
        if isinstance(result, Exception):
            raise result
        return result(request) if callable(result) else result

    def cancel(self, run_id):
        pass


def ready_service(tmp_path):
    service = ConversationService(AppConfig(database_path=tmp_path / "test.sqlite"))
    created = service.create_task(ORIGINAL)
    service.store.transition_operation(created.operation.id, {"queued"}, "completed")
    return service, created.task.id


def run_turn(service, task_id, runner, message="预算到4300，电池至少90%，必须全原", *, completion_timeout=5):
    operation = service.send_message(task_id, message).operation
    finished = threading.Event()

    class CompletingCoordinator(OperationCoordinator):
        def _run(self, operation_id):
            try:
                super()._run(operation_id)
            finally:
                finished.set()

    coordinator = CompletingCoordinator(service, runner)
    try:
        coordinator.start(operation.id)
        # Wait for the real worker, rather than repeatedly opening SQLite while
        # it is persisting batches. A finite budget still exposes stalled work.
        assert finished.wait(completion_timeout), f"Operation {operation.id} worker did not finish within {completion_timeout}s"
        result = service.store.get_operation(operation.id)
        assert result.state in {"completed", "failed", "waiting_confirmation"}, result
        return result
    finally:
        coordinator.shutdown()


def test_update_is_saved_before_followup_failure_and_rebuilt_after_restart(tmp_path):
    service, task_id = ready_service(tmp_path)
    runner = ScriptedRunner(change, CodexTimeoutError("timeout"))
    operation = run_turn(service, task_id, runner)
    assert operation.error_code == "codex_timeout"
    assert "要求已保存" in operation.error_detail
    summary = build_task_summary(service.config, task_id)
    assert summary["task"]["original_goal"] == ORIGINAL
    assert summary["task"]["effective_goal"] == UPDATED
    assert len(summary["preference_revisions"]) == 1
    assert runner.requests[0].allow_preference_update
    assert not runner.requests[1].allow_preference_update
    assert runner.requests[1].task.effective_goal == UPDATED
    restored = ConversationService(service.config)
    request = OperationCoordinator(restored, ScriptedRunner())._build_request(task_id)
    assert request.task.effective_goal == UPDATED
    assert request.task.preference_revision_id == summary["preference_revisions"][0]["id"]
    assert len(restored.get_messages(task_id).items) == 2  # No fabricated assistant answer.


def test_hypothetical_answer_does_not_create_a_revision_or_second_call(tmp_path):
    service, task_id = ready_service(tmp_path)
    runner = ScriptedRunner(AnswerResult(type="answer", content="只比较假设，不改当前要求", candidate_ids=[]))
    run_turn(service, task_id, runner, "如果预算多500会怎样？")
    assert build_task_summary(service.config, task_id)["preference_revisions"] == []
    assert len(runner.requests) == 1


def test_preference_update_is_idempotent_and_rejects_other_message(tmp_path):
    service, task_id = ready_service(tmp_path)
    operation = service.send_message(task_id, "预算到4300，电池90%，全原").operation
    service.store.transition_operation(operation.id, {"queued"}, "running")
    request = OperationCoordinator(service, ScriptedRunner())._build_request(task_id).model_copy(
        update={"trigger_message_id": service.store.get_operation(operation.id).user_message_id})
    update = change(request)
    with pytest.raises(InvalidActionRequestError):
        service.store.apply_preference_update(operation.id, update.model_copy(update={"source_message_id": 999}))
    first = service.store.apply_preference_update(operation.id, update)
    assert service.store.apply_preference_update(operation.id, update) == first
    assert len(build_task_summary(service.config, task_id)["preference_revisions"]) == 1
    with pytest.raises(InvalidActionRequestError):
        service.store.apply_preference_update(operation.id, update.model_copy(update={"effective_goal": "different"}))


def test_stale_model_revision_cannot_overwrite_a_newer_update(tmp_path):
    service, task_id = ready_service(tmp_path)

    def concurrent_change(request):
        update_task_preferences(service.config, task_id, "新要求", "上海256GB，预算4500")
        return change(request)

    operation = run_turn(service, task_id, ScriptedRunner(concurrent_change))
    assert operation.error_code == "requirements_changed"
    summary = build_task_summary(service.config, task_id)
    assert summary["task"]["effective_goal"] == "上海256GB，预算4500"
    assert len(summary["preference_revisions"]) == 1


def test_model_cannot_guess_a_new_revision_to_bypass_its_input_version(tmp_path):
    service, task_id = ready_service(tmp_path)

    def forged_base(request):
        revision = update_task_preferences(service.config, task_id, "修改", "上海256GB，预算4500")
        return change(request).model_copy(update={"base_revision_id": revision})

    operation = run_turn(service, task_id, ScriptedRunner(forged_base))
    assert operation.error_code == "requirements_changed"
    summary = build_task_summary(service.config, task_id)
    assert summary["task"]["effective_goal"] == "上海256GB，预算4500"
    assert len(summary["preference_revisions"]) == 1


@pytest.mark.parametrize("answer", [
    AnswerResult(type="answer", content="旧要求结论", candidate_ids=[]),
    ActionRequestResult(type="action_request", summary="旧要求搜索", risk="access", listing_ids=[], actions=["search"]),
])
def test_stale_answer_and_collection_request_are_not_published(tmp_path, answer):
    service, task_id = ready_service(tmp_path)

    def concurrent_change(request):
        update_task_preferences(service.config, task_id, "修改", UPDATED)
        return answer

    operation = run_turn(service, task_id, ScriptedRunner(concurrent_change))
    assert operation.error_code == "requirements_changed"
    assert all(message.role != "assistant" for message in service.get_messages(task_id).items)
    assert service.get_action_requests(task_id).items == []


def test_repeated_update_is_rejected_without_a_third_model_call(tmp_path):
    service, task_id = ready_service(tmp_path)
    runner = ScriptedRunner(change, change)
    operation = run_turn(service, task_id, runner)
    assert operation.error_code == "invalid_codex_result"
    assert len(runner.requests) == 2
    assert len(build_task_summary(service.config, task_id)["preference_revisions"]) == 1


def test_initial_goal_cannot_be_rewritten_by_model(tmp_path):
    service = ConversationService(AppConfig(database_path=tmp_path / "test.sqlite"))
    created = service.create_task(ORIGINAL)
    runner = ScriptedRunner(change)
    coordinator = OperationCoordinator(service, runner)
    try:
        coordinator.start(created.operation.id)
        operation = wait_state(service.store, created.operation.id, {"failed"})
        assert operation.error_code == "invalid_codex_result"
        assert build_task_summary(service.config, created.task.id)["preference_revisions"] == []
    finally:
        coordinator.shutdown()


def test_cancel_between_revision_and_followup_keeps_saved_requirements(tmp_path):
    service, task_id = ready_service(tmp_path)
    entered, release = threading.Event(), threading.Event()

    class BlockingRunner(ScriptedRunner):
        def cancel(self, run_id):
            release.set()

    def blocked_answer(request):
        entered.set()
        assert release.wait(5)
        return AnswerResult(type="answer", content="取消后的迟到回答", candidate_ids=[])

    runner = BlockingRunner(change, blocked_answer)
    operation = service.send_message(task_id, "预算到4300，电池90%，全原").operation
    coordinator = OperationCoordinator(service, runner)
    try:
        coordinator.start(operation.id)
        assert entered.wait(5)
        coordinator.cancel(operation.id)
    finally:
        release.set()
        coordinator.shutdown()
    assert service.store.get_operation(operation.id).state == "cancelled"
    assert build_task_summary(service.config, task_id)["task"]["effective_goal"] == UPDATED
    assert all(message.role != "assistant" for message in service.get_messages(task_id).items)


@pytest.mark.parametrize("patch", [
    {"effective_goal": " "}, {"base_revision_id": -1}, {"source_message_id": 0},
    {"added_preferences": [], "removed_preferences": []},
    {"added_preferences": ["原装"], "removed_preferences": ["原装"]},
    {"added_preferences": ["预算", "预算"]},
])
def test_invalid_update_contract_is_rejected(tmp_path, patch):
    payload = dict(type="preference_update", source_message_id=2, base_revision_id=0,
                   effective_goal=UPDATED, added_preferences=["预算4300"], removed_preferences=[])
    runtime = CodexRuntime(tmp_path)
    import json
    with pytest.raises(InvalidCodexResult):
        runtime.parse_result(json.dumps({**payload, **patch}), allowed_listing_ids=set())


def test_prompt_exposes_current_revision_and_hypothetical_boundary(tmp_path):
    service, task_id = ready_service(tmp_path)
    request = OperationCoordinator(service, ScriptedRunner())._build_request(task_id)
    prompt = CodexRuntime._build_prompt(request)
    assert '"preference_revision_id":0' in prompt
    assert "hypothetical question" in prompt
    assert "Preserve all unchanged requirements" in prompt
    assert "seller reply" in prompt


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_normal_web_api_and_new_app_restore_preferences(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f'database_path = "{(tmp_path / "db.sqlite").as_posix()}"\n', encoding="utf-8")
    settings = tmp_path / "settings.json"
    app = create_app(config, settings)
    app.state.codex_runtime = ScriptedRunner(
        AnswerResult(type="answer", content="已有目标", candidate_ids=[]), change,
        AnswerResult(type="answer", content="按新要求继续比较，未知仍需核实", candidate_ids=[]))

    async def finished(client, operation_id):
        for _ in range(200):
            detail = (await client.get(f"/api/operations/{operation_id}")).json()
            if detail["operation"]["state"] in {"completed", "failed"}:
                return detail
            await asyncio.sleep(.01)
        raise AssertionError("operation did not finish")

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            first = (await client.post("/api/tasks", json={"message": ORIGINAL})).json()
            task_id = first["task"]["id"]
            await finished(client, first["operation"]["id"])
            changed = await client.post(f"/api/tasks/{task_id}/messages", json={"message": "预算到4300，电池90%，必须全原"})
            assert changed.status_code == 202
            detail = await finished(client, changed.json()["operation"]["id"])
            assert detail["operation"]["state"] == "completed"
            saved = (await client.get(f"/api/tasks/{task_id}")).json()
            assert saved["task"]["effective_goal"] == UPDATED
            assert len(saved["preference_revisions"]) == 1

    restarted = create_app(config, settings)
    restarted.state.codex_runtime = ScriptedRunner(AnswerResult(type="answer", content="只讨论假设", candidate_ids=[]))
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(transport=ASGITransport(app=restarted), base_url="http://127.0.0.1") as client:
            restored = (await client.get(f"/api/tasks/{task_id}")).json()
            assert restored["task"]["original_goal"] == ORIGINAL
            assert restored["task"]["effective_goal"] == UPDATED
            response = await client.post(f"/api/tasks/{task_id}/messages", json={"message": "如果预算多500会怎样？"})
            await finished(client, response.json()["operation"]["id"])
            final = (await client.get(f"/api/tasks/{task_id}")).json()
            assert len(final["preference_revisions"]) == 1
            request = restarted.state.codex_runtime.requests[0]
            assert request.task.effective_goal == UPDATED
