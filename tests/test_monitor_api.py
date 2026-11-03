import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

from shopping_agent.db import connect, create_research_task
from shopping_agent.web.app import create_app
from test_monitoring import BlockingEngine
from test_operation_coordinator import FakeRunner

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f'database_path="{(tmp_path / "test.sqlite").as_posix()}"\n[monitor_engine]\nenabled=true\n', encoding="utf-8")
    app = create_app(config, tmp_path / "settings.json")
    app.state.monitor_engine = BlockingEngine()
    app.state.codex_runtime = FakeRunner(block=True)
    async with app.router.lifespan_context(app):
        app.state.browser_store.set_auth("verified")
        with connect(app.state.monitor_store.config.database_path) as conn:
            task_id = create_research_task(conn, "手柄", "NS2 Pro", "上海")
            other_task = create_research_task(conn, "其他", "其他", "上海")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as value:
            value.app, value.task_id, value.other_task = app, task_id, other_task
            yield value


async def test_one_scope_confirmation_then_pause_and_stop_without_reconfirmation(client):
    url = f"/api/tasks/{client.task_id}/monitors"
    for body in ({"keyword": "NS2 Pro"}, {"keyword": "NS2 Pro", "confirmed": 1},
                 {"keyword": "NS2 Pro", "confirmed": True, "max_pages": 100},
                 {"keyword": "NS2 Pro", "confirmed": True, "collect_seller_profiles": 1},
                 {"keyword": "NS2 Pro", "confirmed": True, "state_file": "forbidden"}):
        assert (await client.post(url, json=body)).status_code == 422
    response = await client.post(url, json={"keyword": "NS2 Pro", "confirmed": True})
    assert response.status_code == 202
    monitor = response.json()
    # Repeated authorized submission returns the same monitor, not another collector.
    assert (await client.post(url, json={"keyword": "NS2 Pro", "confirmed": True})).json()["id"] == monitor["id"]
    for _ in range(200):
        if client.app.state.monitor_engine.started.is_set():
            break
        await asyncio.sleep(.01)
    assert client.app.state.monitor_engine.started.is_set()
    assert (await client.post(f"{url}/{monitor['id']}/pause")).status_code == 200
    for _ in range(200):
        current = (await client.get(url)).json()["items"][0]
        if current["state"] == "paused":
            break
        await asyncio.sleep(.01)
    assert current["state"] == "paused" and current["imported"] == 2
    assert client.app.state.monitor_engine.cleaned.is_set()
    assert (await client.post(f"{url}/{monitor['id']}/stop")).json()["state"] == "stopped"
    resumed = await client.post(f"{url}/{monitor['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["id"] == monitor["id"] and resumed.json()["rounds"] == current["rounds"]
    assert resumed.json()["imported"] == 2
    assert "state_file" not in response.text


async def test_environment_check_is_explicit_cached_and_exposes_no_config_paths(client, monkeypatch):
    import shopping_agent.web.monitor_routes as module
    calls = []
    expected = dict(ready=True, checks=[dict(code="browser", ok=True)], checked_at="test")
    monkeypatch.setattr(module, "check_monitor_environment", lambda config: calls.append(config) or expected)
    assert (await client.get("/api/monitor-engine/check")).json() == {"result": None}
    assert not calls
    response = await client.post("/api/monitor-engine/check")
    assert response.json() == expected and len(calls) == 1
    assert (await client.get("/api/monitor-engine/check")).json() == {"result": expected}
    assert len(calls) == 1 and "root" not in response.text and "python" not in response.text
    rejected = await client.post("/api/monitor-engine/check", headers={"Origin": "https://evil.test"})
    assert rejected.status_code == 403 and len(calls) == 1


async def test_failed_environment_check_blocks_start_but_never_blocks_stop(client):
    url = f"/api/tasks/{client.task_id}/monitors"
    monitor = (await client.post(url, json={"keyword": "NS2 Pro", "confirmed": True})).json()
    client.app.state.monitor_environment_result = dict(ready=False, checks=[], checked_at="test")
    assert (await client.post(url, json={"keyword": "另一个范围", "confirmed": True})).status_code == 409
    assert (await client.post(f"{url}/{monitor['id']}/pause")).status_code == 200
    assert (await client.post(f"{url}/{monitor['id']}/resume")).status_code == 409
    assert (await client.post(f"{url}/{monitor['id']}/stop")).status_code == 200


@pytest.mark.parametrize("auth", ["unknown", "invalid"])
async def test_unverified_login_rejects_start_and_resume_without_spending_rounds(client, auth):
    client.app.state.monitor_coordinator.shutdown()
    store = client.app.state.monitor_store
    monitor = store.create(client.task_id, keyword="NS2 Pro", confirmed=True)
    store.control(client.task_id, monitor["id"], "stop")
    before = store.list(client.task_id)[0]
    client.app.state.browser_store.set_auth(auth)
    url = f"/api/tasks/{client.task_id}/monitors"
    assert (await client.post(url, json={"keyword": "另一个范围", "confirmed": True})).status_code == 409
    response = await client.post(f"{url}/{monitor['id']}/resume")
    assert response.status_code == 409 and "登录" in response.text
    assert store.list(client.task_id) == [before]
    assert not client.app.state.monitor_engine.started.is_set()
    assert (await client.post(f"{url}/{monitor['id']}/stop")).status_code == 200
    client.app.state.browser_store.set_auth("verified")
    assert (await client.post(f"{url}/{monitor['id']}/resume")).status_code == 200


async def test_explicit_external_credential_configuration_keeps_its_engine_preflight(client, tmp_path):
    client.app.state.browser_store.set_auth("unknown")
    client.app.state.monitor_store.config.monitor_engine.state_file = tmp_path / "admin-state.json"
    response = await client.post(f"/api/tasks/{client.task_id}/monitors", json={"keyword": "NS2 Pro", "confirmed": True})
    assert response.status_code == 202  # Fake engine; real engine still validates the external file.


async def test_console_log_api_reads_filtered_output_and_rejects_other_tasks(client):
    from shopping_agent.monitor_logs import ConsoleLog, monitor_directory
    monitor = (await client.post(f"/api/tasks/{client.task_id}/monitors", json={"keyword": "NS2 Pro", "confirmed": True})).json()
    config = client.app.state.monitor_store.config
    # Fixture work_dir must be temporary too, even though no engine is launched.
    config.monitor_engine.work_dir = config.database_path.parent / "engine"
    log = ConsoleLog(monitor_directory(config, monitor["id"]) / "logs", "a" * 32)
    log.write("page 1 ready"); log.write("Cookie: synthetic-private-value"); log.close()
    url = f"/api/tasks/{client.task_id}/monitors/{monitor['id']}/logs"
    response = await client.get(url + "?limit=1")
    assert response.status_code == 200 and "synthetic-private-value" not in response.text
    data = response.json()
    assert data["has_more"] and data["round_id"] == "a" * 32
    assert (await client.get(url + "?round_id=../../credentials")).status_code == 422
    assert (await client.get(f"/api/tasks/{client.other_task}/monitors/{monitor['id']}/logs")).status_code == 400


async def test_cross_task_control_and_cross_origin_creation_are_rejected(client):
    url = f"/api/tasks/{client.task_id}/monitors"
    monitor = (await client.post(url, json={"keyword": "NS2 Pro", "confirmed": True})).json()
    assert (await client.post(f"/api/tasks/{client.other_task}/monitors/{monitor['id']}/stop")).status_code == 400
    denied = await client.post(url, headers={"Origin": "https://evil.test"}, json={"keyword": "NS2 Pro", "confirmed": True})
    assert denied.status_code == 403
    assert (await client.get(f"/api/tasks/{client.other_task}/monitors")).json()["items"] == []


async def test_pool_count_uses_unique_task_candidates_and_includes_existing_data(client):
    from shopping_agent.db import create_search_run, attach_run_to_task, upsert_listing, add_listing_snapshot
    with connect(client.app.state.monitor_store.config.database_path) as conn:
        listing = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=123")
        for number in range(2):
            run = create_search_run(conn, goal="existing", city="上海")
            attach_run_to_task(conn, task_id=client.task_id, run_id=run)
            add_listing_snapshot(conn, listing_id=listing, run_id=run, title="手柄", price_text=str(399-number))
    page = (await client.get(f"/api/tasks/{client.task_id}/monitors")).json()
    assert page["candidate_pool_count"] == 1 and page["platform_enabled"] is True
    assert page["items"] == []
    other = (await client.get(f"/api/tasks/{client.other_task}/monitors")).json()
    assert other["candidate_pool_count"] == 0


async def test_disabled_configuration_does_not_start_monitoring(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f'database_path="{(tmp_path / "db.sqlite").as_posix()}"\n', encoding="utf-8")
    app = create_app(config, tmp_path / "settings.json")
    app.state.codex_runtime = FakeRunner(block=True)
    async with app.router.lifespan_context(app):
        with connect(app.state.monitor_store.config.database_path) as conn:
            task_id = create_research_task(conn, "手柄", "NS2 Pro", "上海")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            response = await client.post(f"/api/tasks/{task_id}/monitors", json={"keyword": "NS2 Pro", "confirmed": True})
            assert response.status_code == 409
            assert app.state.monitor_coordinator.thread is None


async def test_diagnostic_api_is_paginated_and_rejects_other_task(client):
    from shopping_agent.monitor_diagnostics import MonitorDiagnostics
    url = f"/api/tasks/{client.task_id}/monitors"
    monitor = (await client.post(url, json={"keyword": "NS2 Pro", "confirmed": True})).json()
    log = MonitorDiagnostics(client.app.state.monitor_store.config, monitor, "a" * 32)
    log.emit("process", "round_started", cookie="private-cookie")
    log.emit("finished", "engine_timeout", imported=2)
    events = f"{url}/{monitor['id']}/events"
    response = await client.get(events + "?limit=1")
    assert response.status_code == 200 and "private-cookie" not in response.text
    page = response.json()
    assert page["items"][0]["code"] == "engine_timeout" and page["has_more"]
    last = await client.get(events + f"?before_id={page['next_before_id']}&limit=1")
    assert last.json()["items"][0]["code"] == "round_started"
    assert (await client.get(events + "?limit=101")).status_code == 422
    assert (await client.get(events + "?before_id=0")).status_code == 422
    assert (await client.get(f"/api/tasks/{client.other_task}/monitors/{monitor['id']}/events")).status_code == 400


async def test_second_service_rejected_before_it_can_recover_running_monitor(client):
    url = f"/api/tasks/{client.task_id}/monitors"
    monitor = (await client.post(url, json={"keyword": "NS2 Pro", "confirmed": True})).json()
    for _ in range(200):
        if client.app.state.monitor_engine.started.is_set():
            break
        await asyncio.sleep(.01)
    second = create_app(client.app.state.config_path, client.app.state.settings_path)
    second.state.codex_runtime = FakeRunner(block=True)
    with pytest.raises(RuntimeError, match="服务锁"):
        async with second.router.lifespan_context(second):
            pytest.fail("Second service must not reach recovery")
    row = (await client.get(url)).json()["items"][0]
    assert row["id"] == monitor["id"] and row["state"] == "running"


async def test_clean_shutdown_releases_service_lock_and_failed_shutdown_retains_it(tmp_path):
    from shopping_agent.service_lease import ServiceLease
    database = tmp_path / "db.sqlite"
    config = tmp_path / "config.toml"
    config.write_text(f'database_path="{database.as_posix()}"\n', encoding="utf-8")
    app = create_app(config, tmp_path / "settings.json")
    app.state.codex_runtime = FakeRunner(block=True)
    async with app.router.lifespan_context(app):
        pass
    with ServiceLease(database):
        pass
    second = create_app(config, tmp_path / "settings.json")
    second.state.codex_runtime = FakeRunner(block=True)
    original = None
    cleanup_calls = []
    try:
        with pytest.raises(RuntimeError, match="simulated shutdown"):
            async with second.router.lifespan_context(second):
                original = second.state.monitor_coordinator.shutdown
                def fail():
                    raise RuntimeError("simulated shutdown")
                second.state.monitor_coordinator.shutdown = fail
                browser_shutdown = second.state.browser_coordinator.shutdown
                operation_shutdown = second.state.coordinator.shutdown
                def close_browser():
                    cleanup_calls.append("browser")
                    browser_shutdown()
                def close_operations():
                    cleanup_calls.append("operations")
                    operation_shutdown()
                second.state.browser_coordinator.shutdown = close_browser
                second.state.coordinator.shutdown = close_operations
        assert cleanup_calls == ["browser", "operations"]
        with pytest.raises(RuntimeError, match="服务锁"):
            with ServiceLease(database):
                pass
    finally:
        if original:
            original()
        second.state.browser_coordinator.shutdown()
        second.state.coordinator.shutdown()
        second.state.service_lease.release()  # This fixture never started a worker.
