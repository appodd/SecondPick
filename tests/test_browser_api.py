import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from shopping_agent.web.app import create_app
from shopping_agent.browser_jobs import BrowserJobError
from shopping_agent.browser_collection import BrowserCollectionBackend
from test_browser_jobs import approved_request
from test_operation_coordinator import FakeRunner

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeBrowser:
    def __init__(self):
        self.calls = []

    async def run(self, job, store, config):
        self.calls.append((job, config))
        if job["kind"] == "login":
            store.update(job["id"], stage="waiting_login")
            while not store.get(job["id"])["verify_requested"]:
                await asyncio.sleep(.01)
            store.set_auth("verified")
            return {"authenticated": True, "run_ids": [], "listing_count": 0}
        if job["query"] == "block":
            await asyncio.sleep(60)
        if job["query"] == "cooldown":
            raise BrowserJobError("search_cooldown", "请等待冷却")
        return {"run_ids": [], "listing_count": 2}


@pytest.fixture
async def client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f'database_path = "{(tmp_path / "db.sqlite").as_posix()}"\n', encoding="utf-8")
    app = create_app(config, tmp_path / "settings.json")
    app.state.codex_runtime = FakeRunner(block=True)
    app.state.browser_backend = FakeBrowser()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as value:
            value.app = app
            yield value


async def wait_job(client, job_id, states):
    for _ in range(200):
        job = (await client.get(f"/api/browser/jobs/{job_id}")).json()
        if job["state"] in states:
            return job
        await asyncio.sleep(.01)
    pytest.fail(f"Browser job never reached {states}: {job}")


async def test_login_requires_explicit_verification_and_restores_status(client):
    assert (await client.get("/api/browser/status")).json()["auth_status"] == "unknown"
    job = (await client.post("/api/setup/xianyu-login")).json()
    await wait_job(client, job["id"], {"running"})
    assert (await client.post("/api/setup/xianyu-login")).json()["id"] == job["id"]
    assert (await client.get("/api/browser/status")).json()["auth_status"] == "unknown"
    assert (await client.post(f"/api/browser/jobs/{job['id']}/verify")).status_code == 200
    done = await wait_job(client, job["id"], {"completed"})
    assert done["result"]["authenticated"] is True
    assert (await client.get("/api/browser/status")).json()["auth_status"] == "verified"


async def test_execution_acknowledgement_auth_scope_and_idempotence(client):
    action = approved_request(client.app.state.conversation_service)
    path = f"/api/action-requests/{action.id}/execute"
    body = {"task_id": action.task_id, "query": "Camera", "max_pages": 1, "acknowledge_risk": True}
    assert (await client.get(f"/api/action-requests/{action.id}/execution", params={"task_id": action.task_id})).json() is None
    assert client.app.state.browser_backend.calls == []  # Approval never starts collection.
    assert (await client.post(path, json=body)).json()["error"]["code"] == "login_required"
    client.app.state.browser_store.set_auth("verified")
    for invalid in [{**body, "acknowledge_risk": False}, {**body, "acknowledge_risk": 1}, {**body, "max_pages": 4}, {**body, "url": "https://evil.test"}]:
        assert (await client.post(path, json=invalid)).status_code == 422
    assert (await client.post(path, json={**body, "task_id": action.task_id + 100})).status_code == 404
    created = await client.post(path, json=body)
    assert created.status_code == 202, created.text
    job = created.json()
    done = await wait_job(client, job["id"], {"completed"})
    assert done["result"]["listing_count"] == 2
    assert (await client.post(path, json=body)).json()["id"] == job["id"]
    assert len(client.app.state.browser_backend.calls) == 1
    messages = (await client.get(f"/api/tasks/{action.task_id}/messages")).json()["items"]
    assert any(item["role"] == "system" and "2 条" in item["content"] for item in messages)


async def test_cancel_retry_and_live_settings(client):
    action = approved_request(client.app.state.conversation_service)
    client.app.state.browser_store.set_auth("verified")
    path = f"/api/action-requests/{action.id}/execute"
    body = {"task_id": action.task_id, "query": "block", "acknowledge_risk": True}
    job = (await client.post(path, json=body)).json()
    await wait_job(client, job["id"], {"running"})
    conflict = await client.post(f"/api/tasks/{action.task_id}/messages", json={"message": "Analyze"})
    assert conflict.status_code == 409
    await client.post(f"/api/browser/jobs/{job['id']}/cancel")
    await wait_job(client, job["id"], {"cancelled"})
    assert (await client.get(f"/api/browser/jobs/{job['id']}/audit")).json()["items"][-1]["metadata"]["state"] == "cancelled"
    retry = (await client.post(path, json={**body, "retry_of": job["id"]})).json()
    assert retry["id"] != job["id"]
    assert (await client.post(path, json={**body, "retry_of": job["id"]})).json()["id"] == retry["id"]
    await client.post(f"/api/browser/jobs/{retry['id']}/cancel")
    await wait_job(client, retry["id"], {"cancelled"})
    await client.patch("/api/settings", json={"platforms": []})
    assert (await client.post("/api/setup/xianyu-login")).status_code == 400
    assert (await client.post(path, json=body)).status_code == 400


async def test_detail_verification_waits_for_explicit_signal(client):
    from shopping_agent.db import connect, create_search_run, attach_run_to_task, upsert_listing, add_listing_snapshot
    action = approved_request(client.app.state.conversation_service)
    store = client.app.state.browser_store
    with connect(store.config.database_path) as conn:
        run = create_search_run(conn, goal="Camera", city="上海")
        attach_run_to_task(conn, task_id=action.task_id, run_id=run)
        listing = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=123")
        add_listing_snapshot(conn, listing_id=listing, run_id=run, title="Camera")
        conn.execute("UPDATE action_requests SET actions_json='[\"detail\"]',listing_ids_json=? WHERE id=?",
                     (f"[{listing}]", action.id))
    class Page:
        def is_closed(self): return False
        async def wait_for_timeout(self, ms): await asyncio.sleep(.01)
    class WaitingBrowser:
        async def run(self, job, store, config):
            await BrowserCollectionBackend._wait_for_detail_verification(Page(), job, store)
            return {"run_ids": [run], "listing_count": 1}
    client.app.state.browser_coordinator.backend = WaitingBrowser()
    store.set_auth("verified")
    job = (await client.post(f"/api/action-requests/{action.id}/execute", json={
        "task_id": action.task_id, "acknowledge_risk": True})).json()
    await wait_job(client, job["id"], {"running"})
    for _ in range(100):
        if store.get(job["id"])["stage"] == "waiting_verification": break
        await asyncio.sleep(.01)
    assert store.get(job["id"])["stage"] == "waiting_verification"
    assert (await client.get("/api/browser/status")).json()["active_job"]["id"] == job["id"]
    endpoint = f"/api/browser/jobs/{job['id']}/resume-verification"
    assert (await client.post(endpoint)).status_code == 200
    done = await wait_job(client, job["id"], {"completed"})
    assert done["result"]["listing_count"] == 1
    assert (await client.post(endpoint)).status_code == 409
    audit = (await client.get(f"/api/browser/jobs/{job['id']}/audit")).json()
    assert [event["event_type"] for event in audit["items"]] == ["verification_required", "manual_continue", "job_finished"]
    limited = await client.get(f"/api/browser/jobs/{job['id']}/audit?limit=1")
    assert limited.json()["has_more"] and len(limited.json()["items"]) == 1
    assert (await client.get("/api/browser/jobs/999999/audit")).status_code == 404
    assert (await client.get(f"/api/browser/jobs/{job['id']}/audit?limit=201")).status_code == 422


async def test_resume_cannot_signal_login_search_or_stopping_job(client):
    store = client.app.state.browser_store
    login = store.create_login()
    assert (await client.post(f"/api/browser/jobs/{login['id']}/resume-verification")).status_code == 409
    store.finish(login["id"], "cancelled")
    action = approved_request(client.app.state.conversation_service)
    search = store.create_collection(action.task_id, action.id, "Camera", 1)
    store.claim(search["id"])
    store.update(search["id"], stage="waiting_verification")
    assert (await client.post(f"/api/browser/jobs/{search['id']}/resume-verification")).status_code == 409
