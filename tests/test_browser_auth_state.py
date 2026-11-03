import asyncio
import os

import pytest
from playwright.async_api import async_playwright

from shopping_agent.browser.auth_state import (
    STATE_NAME, _protect, restore_session_cookies, save_session_cookies,
)
from shopping_agent.browser.session import _closing_context


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI session handoff")
def test_encrypted_session_handoff_survives_real_chromium_restart(tmp_path):
    """Local-only reproducer for login working until the browser is reopened."""
    async def run():
        profile = tmp_path / "profile"
        async with async_playwright() as playwright:
            async with _closing_context(playwright.chromium.launch_persistent_context(
                str(profile), headless=True), profile) as first:
                await first.add_cookies([{"name": "session_probe", "value": "local-secret-test",
                                         "url": "http://127.0.0.1"}])
            saved = (profile / STATE_NAME).read_bytes()
            assert b"local-secret-test" not in saved
            assert b"session_probe" not in saved
            async with _closing_context(playwright.chromium.launch_persistent_context(
                str(profile), headless=True), profile) as reopened:
                cookies = await reopened.cookies("http://127.0.0.1")
                assert any(cookie["name"] == "session_probe" and cookie["value"] == "local-secret-test"
                           for cookie in cookies)
                # A normal logout removes the saved session too.
                await reopened.clear_cookies()
            async with _closing_context(playwright.chromium.launch_persistent_context(
                str(profile), headless=True), profile) as logged_out:
                assert not await logged_out.cookies("http://127.0.0.1")
    asyncio.run(run())


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI session handoff")
def test_corrupt_encrypted_state_allows_manual_login(tmp_path):
    (tmp_path / STATE_NAME).write_bytes(b"damaged-local-state")
    class Context:
        async def add_cookies(self, cookies):
            pytest.fail("Corrupt state must not inject cookies")
    asyncio.run(restore_session_cookies(Context(), tmp_path))


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI session handoff")
def test_failed_save_leaves_previous_encrypted_state_intact(tmp_path):
    original = _protect(b"[]")
    (tmp_path / STATE_NAME).write_bytes(original)
    class ClosedContext:
        async def cookies(self):
            raise RuntimeError("Browser already closed")
    with pytest.raises(RuntimeError):
        asyncio.run(save_session_cookies(ClosedContext(), tmp_path))
    assert (tmp_path / STATE_NAME).read_bytes() == original
