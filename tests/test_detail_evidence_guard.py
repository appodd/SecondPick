import asyncio

import pytest

from shopping_agent.browser.session import DetailSnapshot, _is_access_blocked
from shopping_agent.browser.session import BrowserSession
from shopping_agent.config import AppConfig
from shopping_agent.db import initialize, connect, create_search_run, upsert_listing, add_listing_snapshot
from shopping_agent.detail import capture_detail_url
from shopping_agent.safety import SafetyError


def test_visible_verification_frame_is_blocked_without_parent_text():
    assert _is_access_blocked("为你推荐", [
        "https://h5api.m.goofish.com//h5/mtop.taobao.idle.pc.detail/1.0/_____tmd_____/punish?token=unused"
    ])
    assert not _is_access_blocked("正常商品", ["https://g.alicdn.com/platform/xdomain-storage/frame.html"])


@pytest.mark.parametrize("blocked", [False, True])
def test_empty_or_blocked_detail_does_not_overwrite_search_evidence(tmp_path, monkeypatch, blocked):
    config = AppConfig(database_path=tmp_path / "test.sqlite", browser_profile_dir=tmp_path / "profile")
    initialize(config.database_path)
    url = "https://www.goofish.com/item?id=123"
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="phone", city="上海")
        listing_id = upsert_listing(conn, platform="xianyu", url=url)
        add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id,
                             title="Personal phone", price_text="4000", location="上海")

    async def capture(self, **kwargs):
        return DetailSnapshot(url=url, screenshot_path=tmp_path / "image.png",
            html_path=tmp_path / "page.html", text_path=tmp_path / "text.txt",
            links_path=tmp_path / "links.txt", images_path=tmp_path / "images.txt",
            page_title="闲鱼 - 闲不住？上闲鱼！", visible_text="为你推荐\n¥\n999\n另一台手机",
            links=[], image_urls=[], access_blocked=blocked, api_detail=None)

    monkeypatch.setattr("shopping_agent.detail.BrowserSession.capture_detail_snapshot", capture)
    with pytest.raises(SafetyError, match="Access blocked|Detail content unavailable"):
        asyncio.run(capture_detail_url(config, url, run_id=run_id))
    with connect(config.database_path) as conn:
        row = conn.execute("SELECT title,price_text FROM listing_snapshots WHERE listing_id=?", (listing_id,)).fetchone()
        assert tuple(row) == ("Personal phone", "4000")
        assert conn.execute("SELECT COUNT(*) FROM listing_snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM detail_snapshots").fetchone()[0] == 0


@pytest.mark.parametrize("cancel", [False, True])
def test_real_local_browser_keeps_verification_context_and_closes_on_exit(tmp_path, cancel):
    # An inert local fixture, never the platform's verification dialog.
    page_path = tmp_path / "challenge.html"
    page_path.write_text("<html><body>安全验证</body></html>", encoding="utf-8")

    async def run():
        entered = asyncio.Event()
        pages = []
        checks = []
        async def checked(cleared):
            checks.append(cleared)
        async def manual_signal(page):
            pages.append(page)
            entered.set()
            assert not page.is_closed()
            if cancel:
                await asyncio.Event().wait()
            elif len(pages) == 2:
                await page.locator("body").evaluate("element => element.innerText = '目标商品内容'")
        task = asyncio.create_task(BrowserSession(tmp_path / "profile", headless=True).capture_detail_snapshot(
            page_path.as_uri(), tmp_path / "shots", wait_ms=0, verification_callback=manual_signal, verification_result_callback=checked))
        await asyncio.wait_for(entered.wait(), 10)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            snapshot = await task
            assert len(pages) == 2 and pages[0] is pages[1]
            assert snapshot.visible_text == "目标商品内容"
            assert not snapshot.access_blocked
            assert checks == [False, True]
        assert pages[0].is_closed()
    asyncio.run(run())
