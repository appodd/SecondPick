import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from shopping_agent.goofish_control_flow import CompatibilityError, repair_detail_control_flow


class RiskControlError(Exception):
    pass


class LoginRequiredError(Exception):
    pass


class PlaywrightTimeoutError(Exception):
    pass


def fixture(mode):
    path = Path(__file__).parent / "fixtures/goofish_detail_loop.py"
    spec = importlib.util.spec_from_file_location("native_detail_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls, closed, sleeps = [], [], []

    class Page:
        ok = True

        def __init__(self, number):
            self.number, self.url = number, "about:blank"

        def expect_response(self, *args, **kwargs):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def goto(self, url, **kwargs):
            calls.append(self.number)
            self.url = "https://passport.goofish.com/mini_login" if self.number == 1 and mode in {"login", "login_timeout"} else url
            if self.number == 1 and mode in {"timeout", "login_timeout", "dialog_timeout"}:
                raise PlaywrightTimeoutError()
            if self.number == 1 and mode == "ordinary_error":
                raise ValueError("synthetic malformed item")

        def locator(self, selector):
            async def is_visible():
                return self.number == 1 and (mode in {"dialog", "dialog_timeout"} and "baxia" in selector
                                            or mode == "middleware" and "MIDDLEWARE" in selector)
            return SimpleNamespace(is_visible=is_visible)

        async def json(self):
            return {"ret": ["FAIL_SYS_USER_VALIDATE"] if self.number == 1 and mode == "api" else ["SUCCESS"]}

        @property
        def value(self):
            async def result():
                return self
            return result()

        async def close(self):
            closed.append(self.number)

    async def safe_get(data, key, default):
        return data.get(key, default)

    async def sleep(*args):
        sleeps.append(args)

    module.__dict__.update(RiskControlError=RiskControlError, LoginRequiredError=LoginRequiredError,
        PlaywrightTimeoutError=PlaywrightTimeoutError, safe_get=safe_get, random_sleep=sleep,
        asyncio=SimpleNamespace(sleep=sleep), random=SimpleNamespace(randint=lambda *args: 39),
        make_page=Page, saved=[], pages=[], _is_login_url=lambda url: "passport.goofish.com" in url)
    return module, calls, closed, sleeps


def test_native_bug_reproduction_continues_after_validation(capsys):
    module, calls, closed, sleeps = fixture("api")
    asyncio.run(module.scrape_xianyu({}))
    assert calls == closed == list(range(6))
    assert module.saved == [0, 2, 3, 4, 5]
    assert (39,) in sleeps
    assert "FAIL_SYS_USER_VALIDATE" in capsys.readouterr().out


@pytest.mark.parametrize("mode,error", [("api", RiskControlError), ("dialog", RiskControlError),
    ("middleware", RiskControlError), ("dialog_timeout", RiskControlError),
    ("login", LoginRequiredError), ("login_timeout", LoginRequiredError)])
def test_control_failure_exits_before_third_item_and_next_page(mode, error):
    module, calls, closed, sleeps = fixture(mode)
    repair_detail_control_flow(module)
    with pytest.raises(error):
        asyncio.run(module.scrape_xianyu({}))
    assert calls == closed == [0, 1]
    assert module.saved == [0] and module.pages == [0]
    assert not any(len(s) == 1 for s in sleeps)  # No delayed "exit" sleep.


@pytest.mark.parametrize("mode", ["normal", "timeout", "ordinary_error"])
def test_normal_collection_and_ordinary_item_failures_keep_native_policy(mode):
    module, calls, closed, sleeps = fixture(mode)
    repair_detail_control_flow(module)
    asyncio.run(module.scrape_xianyu({}))
    assert calls == closed == list(range(6))
    assert module.saved == (list(range(6)) if mode == "normal" else [0, 2, 3, 4, 5])


def test_unknown_contract_is_rejected_without_changing_function():
    module, calls, _, _ = fixture("normal")
    original = module.scrape_xianyu
    module.scrape_xianyu = test_unknown_contract_is_rejected_without_changing_function
    with pytest.raises(CompatibilityError, match="Unsupported monitor detail contract"):
        repair_detail_control_flow(module)
    assert module.scrape_xianyu is test_unknown_contract_is_rejected_without_changing_function
    assert not calls
    module.scrape_xianyu = original


def test_detected_control_reason_is_published_before_a_cleanup_error():
    module, calls, _, _ = fixture("api")
    events = []
    make_page = module.make_page
    def make_failing_page(number):
        page = make_page(number)
        if number == 1:
            async def close():
                events.append("cleanup")
                raise RuntimeError("synthetic close failure")
            page.close = close
        return page
    module.make_page = make_failing_page
    repair_detail_control_flow(module, on_control_failure=events.append)
    with pytest.raises(RuntimeError, match="synthetic close failure"):
        asyncio.run(module.scrape_xianyu({}))
    assert events == ["verification_required", "cleanup"]
    assert calls == [0, 1] and module.saved == [0]


def test_reporting_failure_cannot_turn_verification_into_a_continuable_item_error():
    module, calls, closed, _ = fixture("api")
    def broken_report(code):
        raise OSError("synthetic full diagnostics storage")
    repair_detail_control_flow(module, on_control_failure=broken_report)
    with pytest.raises(RiskControlError):
        asyncio.run(module.scrape_xianyu({}))
    assert calls == closed == [0, 1] and module.saved == [0]


def test_real_local_browser_validation_stops_before_third_navigation():
    from urllib.parse import urlsplit, parse_qs
    from playwright.async_api import async_playwright, TimeoutError as NativeTimeout
    from shopping_agent.goofish_browser import protected_playwright
    module, _, _, _ = fixture("normal")
    requests = []

    async def run():
        async with protected_playwright(async_playwright, {"cookies": [], "origins": []})() as p:
            browser = await p.chromium.launch()
            try:
                context = await browser.new_context()
                async def route_handler(route):
                    url = urlsplit(route.request.url)
                    if url.hostname != "monitor.test":
                        await route.abort()
                        return
                    number = int(parse_qs(url.query)["id"][0])
                    requests.append((url.path, number))
                    if url.path == "/detail":
                        await route.fulfill(json={"ret": ["FAIL_SYS_USER_VALIDATE"] if number == 101 else ["SUCCESS"]})
                    else:
                        await route.fulfill(content_type="text/html", body=f'<script>fetch("/detail?id={number}")</script>')
                await context.route("**/*", route_handler)
                pages = [await context.new_page() for _ in range(6)]
                module.make_page = lambda number: pages[number]
                module.DETAIL_API_URL_PATTERN = "/detail?"
                module.PlaywrightTimeoutError = NativeTimeout
                repair_detail_control_flow(module)
                with pytest.raises(RiskControlError):
                    await module.scrape_xianyu({})
                assert module.saved == [0] and module.pages == [0]
                assert [number for path, number in requests if path == "/item"] == [100, 101]
                assert pages[0].is_closed() and pages[1].is_closed()
            finally:
                await browser.close()
    asyncio.run(run())
