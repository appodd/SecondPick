import asyncio
from types import SimpleNamespace

import pytest

from shopping_agent.browser_collection import BrowserCollectionBackend, verified_login, safe_listing_url
from shopping_agent.browser_jobs import BrowserJobStore, BrowserJobError
from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.conversation_store import ActionRequestInput
from shopping_agent.browser.session import _closing_context
from shopping_agent.safety import SafetyError
from shopping_agent.db import connect, create_search_run, upsert_listing, add_listing_snapshot, attach_run_to_task
from test_browser_jobs import approved_request


def test_login_requires_positive_account_evidence_not_merely_absent_dialog():
    assert not verified_login("闲鱼首页 搜索", [])
    assert not verified_login("我的闲鱼 退出登录", ["https://passport.goofish.com/mini_login"])
    assert verified_login("个人中心 我买到的 我卖出的", [])
    assert not verified_login("安全验证 我买到的 我卖出的", [])
    assert not verified_login("登录\n我买到的\n我卖出的", [])
    assert not verified_login("请登录\n退出登录", [])


@pytest.mark.parametrize("url", ["http://127.0.0.1/item?id=1", "https://www.goofish.com.evil.test/item?id=1", "file:///secret", "https://evil.test/?url=goofish.com/item", "https://www.goofish.com@evil.test/item?id=1"])
def test_only_platform_listing_urls_are_accepted(url):
    assert not safe_listing_url(url)


def test_search_persists_result_in_requested_task(monkeypatch, tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite", screenshots_dir=tmp_path / "shots", browser_profile_dir=tmp_path / "profile")
    service = ConversationService(config)
    request = approved_request(service)
    store = BrowserJobStore(config)
    store.set_auth("verified")
    job = store.create_collection(request.task_id,request.id,"iPhone 15 Pro",1)
    seen = []
    async def capture(**kwargs):
        seen.append(kwargs)
        with connect(config.database_path) as conn:
            run = create_search_run(conn,goal="iPhone 15 Pro",city="上海")
            listing = upsert_listing(conn,platform="xianyu",url="https://www.goofish.com/item?id=1")
            add_listing_snapshot(conn,listing_id=listing,run_id=run,title="iPhone 15 Pro",price_text="3000")
        return SimpleNamespace(run_id=run,parsed_listings=1,snapshot=SimpleNamespace(stop_reason=None))
    monkeypatch.setattr("shopping_agent.browser_collection.capture_search_spike",capture)
    result = asyncio.run(BrowserCollectionBackend().run(job,store,config))
    assert result["listing_count"] == 1
    assert seen[0]["headless"] is False
    assert seen[0]["query"] == "iPhone 15 Pro"
    assert seen[0]["max_pages"] == 1
    with connect(config.database_path) as conn:
        assert conn.execute("SELECT run_id FROM task_runs WHERE task_id=?",(request.task_id,)).fetchone()["run_id"] == result["run_ids"][0]


def test_unverified_login_cannot_start_platform_capture(monkeypatch,tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite")
    service = ConversationService(config)
    request = approved_request(service)
    store = BrowserJobStore(config)
    job = store.create_collection(request.task_id,request.id,"Camera",1)
    with pytest.raises(BrowserJobError,match="登录"):
        asyncio.run(BrowserCollectionBackend().run(job,store,config))


def test_real_context_wrapper_closes_on_cancellation():
    closed = []
    class Context:
        async def close(self):
            closed.append(True)
    async def launch():
        return Context()
    async def capture():
        async with _closing_context(launch()):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(capture())
    assert closed == [True]


def test_cooldown_reports_remaining_time_without_invalidating_login(monkeypatch, tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite", browser_profile_dir=tmp_path / "profile")
    service = ConversationService(config)
    request = approved_request(service)
    store = BrowserJobStore(config)
    store.set_auth("verified")
    job = store.create_collection(request.task_id, request.id, "Camera", 1)
    async def blocked(**kwargs):
        raise SafetyError("Xianyu search cooldown is active: 120 seconds remaining;")
    monkeypatch.setattr("shopping_agent.browser_collection.capture_search_spike", blocked)
    with pytest.raises(BrowserJobError) as error:
        asyncio.run(BrowserCollectionBackend().run(job, store, config))
    assert error.value.code == "search_cooldown"
    assert "120" in str(error.value)
    assert store.status()["auth_status"] == "verified"


@pytest.mark.parametrize("url,allowed", [("https://www.goofish.com/item?id=123", True), ("https://evil.test/item?id=123", False)])
def test_detail_resolves_only_task_owned_platform_urls(monkeypatch, tmp_path, url, allowed):
    config = AppConfig(database_path=tmp_path / "db.sqlite")
    service = ConversationService(config)
    task = service.create_task("Camera")
    with connect(config.database_path) as conn:
        run = create_search_run(conn, goal="Camera", city="上海")
        attach_run_to_task(conn, task_id=task.task.id, run_id=run)
        listing = upsert_listing(conn, platform="xianyu", url=url)
        add_listing_snapshot(conn, listing_id=listing, run_id=run, title="Camera", price_text="3000")
    service.store.transition_operation(task.operation.id, {"queued"}, "running")
    request = service.store.complete_with_action_request(task.operation.id, ActionRequestInput(
        summary="Detail", risk="Access", actions=["detail"], listing_ids=[listing]))
    service.approve_action(task.task.id, request.id)
    store = BrowserJobStore(config)
    store.set_auth("verified")
    job = store.create_collection(task.task.id, request.id, "", 1)
    calls = []
    async def capture(config, target, **kwargs):
        calls.append((target, kwargs))
        return SimpleNamespace(run_id=run)
    monkeypatch.setattr("shopping_agent.browser_collection.capture_detail_url", capture)
    if allowed:
        result = asyncio.run(BrowserCollectionBackend().run(job, store, config))
        assert result == {"run_ids": [run], "listing_count": 1}
        assert calls[0][0] == url and calls[0][1]["run_id"] == run
        assert calls[0][1]["headless"] is False
    else:
        with pytest.raises(BrowserJobError) as error:
            asyncio.run(BrowserCollectionBackend().run(job, store, config))
        assert error.value.code == "invalid_scope"
        assert calls == []
