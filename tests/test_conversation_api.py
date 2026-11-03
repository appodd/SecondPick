import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.web.app import create_app
from test_operation_coordinator import FakeRunner
from shopping_agent.codex_runtime import ActionRequestResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f'database_path = "{(tmp_path / "db.sqlite").as_posix()}"\n', encoding="utf-8")
    app = create_app(config, tmp_path / "settings.json")
    app.state.codex_runtime = FakeRunner(block=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as value:
            value.app = app
            yield value


async def test_create_conflict_cancel_and_rename(client):
    response = await client.post("/api/tasks", json={"message": "找相机"})
    assert response.status_code == 202
    body = response.json()
    task_id, operation_id = body["task"]["id"], body["operation"]["id"]
    assert body["task"]["original_goal"] == "找相机"
    assert body["operation"]["state"] == "queued"
    candidates = await client.get(f"/api/tasks/{task_id}/candidates")
    assert candidates.status_code == 200
    assert candidates.json()["candidates"] == []
    conflict = await client.post(f"/api/tasks/{task_id}/messages", json={"message": "Second"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "operation_conflict"
    for _ in range(2):
        cancelled = await client.post(f"/api/operations/{operation_id}/cancel")
        assert cancelled.json()["operation"]["state"] == "cancelled"
    messages = await client.get(f"/api/tasks/{task_id}/messages")
    assert len(messages.json()["items"]) == 1
    renamed = await client.patch(f"/api/tasks/{task_id}", json={"title": "My camera"})
    assert renamed.json()["title"] == "My camera"
    assert renamed.json()["original_goal"] == "找相机"
    bad = await client.patch(f"/api/tasks/{task_id}", json={"title": "Bad", "original_goal": "Replace"})
    assert bad.status_code == 422
    events = await client.get(f"/api/operations/{operation_id}/events", headers={"Last-Event-ID": "1"})
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: cancelled" in events.text
    assert "id: 1\n" not in events.text
    bad_cursor = await client.get(f"/api/operations/{operation_id}/events", headers={"Last-Event-ID": "invalid"})
    assert bad_cursor.status_code == 422


async def test_action_decision_history_and_scope(client):
    runner = client.app.state.codex_runtime
    runner.result = ActionRequestResult(type="action_request", summary="Search", risk="Access platform", actions=["search"], listing_ids=[])
    runner.release.set()
    created = (await client.post("/api/tasks", json={"message": "Camera"})).json()
    task_id = created["task"]["id"]
    for _ in range(100):
        history = (await client.get(f"/api/tasks/{task_id}/action-requests")).json()
        if history["items"]:
            break
        await asyncio.sleep(.01)
    request_id = history["items"][0]["id"]
    bad = await client.post(f"/api/action-requests/{request_id}/approve", json={"task_id": task_id + 100})
    assert bad.status_code in {400, 404}
    for _ in range(2):
        approved = await client.post(f"/api/action-requests/{request_id}/approve", json={"task_id": task_id})
        assert approved.json()["action_request"]["state"] == "approved"
    reversed_decision = await client.post(f"/api/action-requests/{request_id}/reject", json={"task_id": task_id})
    assert reversed_decision.status_code == 409
    history = (await client.get(f"/api/tasks/{task_id}/action-requests")).json()
    assert history["items"][0]["state"] == "approved"


async def test_unknown_ids_and_input_security(client):
    for path in ["/api/operations/999", "/api/tasks/999/messages"]:
        assert (await client.get(path)).status_code == 404
    assert (await client.post("/api/tasks", json={"message": "x", "codex_bin": "bad"})).status_code == 422
    assert (await client.post("/api/tasks", json={"message": " "})).status_code == 422
    assert (await client.post("/api/tasks", json={"message": "x"}, headers={"Origin": "https://evil.example"})).status_code == 403


async def test_new_task_does_not_inherit_legacy_global_city(client):
    saved = await client.patch("/api/settings", json={"default_city": "Beijing"})
    assert saved.status_code == 200
    created = await client.post("/api/tasks", json={"message": "Find a camera"})
    assert created.status_code == 202
    # The legacy setting remains saved, but location preferences come from the user's goal.
    assert saved.json()["default_city"] == "Beijing"
    assert created.json()["task"]["city"] == ""
