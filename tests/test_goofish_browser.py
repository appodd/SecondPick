import asyncio
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from shopping_agent.goofish_browser import CredentialError, monitor_cookies, protected_playwright


def cookie(domain=".goofish.com", **changes):
    return {"name": "probe", "value": "synthetic-secret", "domain": domain, "path": "/", "expires": -1, **changes}


def test_cookie_scope_drops_other_accounts_headers_origins_and_generated_metadata():
    state = monitor_cookies(dict(cookies=[cookie(), cookie(".taobao.com"), cookie("goofish.com.evil.test")],
                                headers={"Authorization": "private"}, origins=[{"origin": "https://private.test"}]))
    assert len(state["cookies"]) == 1 and state["origins"] == []
    assert "headers" not in state
    assert state["cookies"][0]["value"] == "synthetic-secret"


@pytest.mark.parametrize("changes", [{"value": []}, {"expires": float("nan")}, {"secure": 1},
    {"path": "bad"}, {"name": ""}, {"value": "x" * 16385}])
def test_invalid_credentials_rejected_without_raw_errors(changes):
    with pytest.raises(CredentialError, match="Invalid monitor credential"):
        monitor_cookies({"cookies": [cookie(**changes)]})


@pytest.mark.parametrize('channel', [None, 'chromium'])
def test_browser_boundary_forces_protection_and_memory_state(channel):
    calls = []
    class NativeBrowser:
        async def new_context(self, **kwargs):
            calls.append(("context", kwargs))
            return "context"
    class BrowserType:
        async def launch(self, **kwargs):
            calls.append(("launch", kwargs))
            return NativeBrowser()
    class Manager:
        async def __aenter__(self):
            return SimpleNamespace(chromium=BrowserType())
        async def __aexit__(self, *args):
            pass
    state = monitor_cookies({"cookies": [cookie()]})
    async def run():
        async with protected_playwright(Manager, state, browser_channel=channel)() as p:
            browser = await p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-web-security"],
                                              chromium_sandbox=False, executable_path="untrusted")
            assert await browser.new_context(storage_state="private-path", permissions=["geolocation"],
                geolocation={"latitude": 0, "longitude": 0}, ignore_https_errors=True,
                extra_http_headers={"Authorization": "private"}, viewport={"width": 400, "height": 600}) == "context"
    asyncio.run(run())
    launch, context = calls[0][1], calls[1][1]
    assert launch == dict(headless=True, chromium_sandbox=True, args=["--disable-dev-shm-usage", "--enable-automation"], **({'channel': channel} if channel else {}))
    assert context["storage_state"] == state and context["storage_state"] is not state
    assert context["permissions"] == [] and not context["ignore_https_errors"] and not context["accept_downloads"]
    assert "extra_http_headers" not in context and "geolocation" not in context


def test_real_local_chromium_uses_sandbox_without_platform_requests():
    async def run():
        async with protected_playwright(async_playwright, monitor_cookies({"cookies": [cookie()]}))() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-web-security"])
            try:
                context = await browser.new_context()
                assert (await context.cookies())[0]["value"] == "synthetic-secret"
                cdp = await browser.new_browser_cdp_session()
                args = (await cdp.send("Browser.getBrowserCommandLine"))["arguments"]
                assert "--no-sandbox" not in args and "--disable-web-security" not in args
                assert not any("IsolateOrigins,site-per-process" in arg for arg in args)
                await context.close()
            finally:
                await browser.close()
    asyncio.run(run())


@pytest.mark.parametrize("kwargs", [{"proxy": {"server": "http://unapproved.test"}}, {"channel": "unknown"}])
def test_unapproved_proxy_or_channel_is_rejected_before_browser_launch(kwargs):
    class Native:
        async def launch(self, **options):
            pytest.fail("Unsupported configuration must not launch")
    class Manager:
        async def __aenter__(self):
            return SimpleNamespace(chromium=Native())
        async def __aexit__(self, *args):
            pass
    async def run():
        async with protected_playwright(Manager, monitor_cookies({"cookies": [cookie()]}))() as p:
            with pytest.raises(RuntimeError, match="Unsupported monitor browser configuration"):
                await p.chromium.launch(**kwargs)
    asyncio.run(run())
