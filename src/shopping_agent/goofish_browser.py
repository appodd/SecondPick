"""Standalone collection browser boundary; credentials remain in memory."""
import copy
import math
import os
from types import SimpleNamespace

MAX_CREDENTIAL_BYTES = 1024 * 1024


def collection_environment():
    keys = {"PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA",
            "APPDATA", "HOME", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PLAYWRIGHT_BROWSERS_PATH", "LANG", "LC_ALL"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keys}
    env.update(RUN_HEADLESS="true", SKIP_AI_ANALYSIS="true", AI_DEBUG_MODE="false",
               ACCOUNT_ROTATION_ENABLED="false", PROXY_ROTATION_ENABLED="false", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    return env


class CredentialError(ValueError):
    pass


def monitor_cookies(state):
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
        raise CredentialError("Invalid monitor credential")
    cookies = []
    if len(state["cookies"]) > 1000:
        raise CredentialError("Invalid monitor credential")
    for item in state["cookies"]:
        if not isinstance(item, dict):
            raise CredentialError("Invalid monitor credential")
        domain = item.get("domain", "")
        if not isinstance(domain, str):
            raise CredentialError("Invalid monitor credential")
        host = domain.lstrip(".").lower()
        if host != "goofish.com" and not host.endswith(".goofish.com"):
            continue
        if domain.startswith("..") or any(not label or label.startswith("-") or label.endswith("-") for label in host.split(".")):
            raise CredentialError("Invalid monitor credential")
        selected = {}
        for key, limit in (("name", 1024), ("value", 16384), ("path", 2048), ("domain", 253)):
            value = item.get(key)
            if not isinstance(value, str) or len(value) > limit or "\x00" in value:
                raise CredentialError("Invalid monitor credential")
            selected[key] = value
        if not selected["name"] or not selected["path"].startswith("/") or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in host):
            raise CredentialError("Invalid monitor credential")
        expires = item.get("expires", -1)
        if type(expires) not in (int, float) or not math.isfinite(expires) or expires < 0 and expires != -1:
            raise CredentialError("Invalid monitor credential")
        selected["expires"] = expires
        for key in ("httpOnly", "secure"):
            value = item.get(key, False)
            if type(value) is not bool:
                raise CredentialError("Invalid monitor credential")
            selected[key] = value
        same_site = item.get("sameSite", "Lax")
        if same_site not in ("Lax", "Strict", "None"):
            raise CredentialError("Invalid monitor credential")
        selected["sameSite"] = same_site
        cookies.append(selected)
    if not cookies:
        raise CredentialError("Monitor login required")
    return dict(cookies=cookies, origins=[])


def protected_playwright(factory, state):
    """Keep native navigation while enforcing launch/context protection."""
    class Browser:
        def __init__(self, native):
            self.native = native

        def __getattr__(self, name):
            return getattr(self.native, name)

        async def new_context(self, **kwargs):
            allowed = {key: kwargs[key] for key in ("user_agent", "viewport", "device_scale_factor", "is_mobile",
                "has_touch", "locale", "timezone_id", "color_scheme") if key in kwargs}
            return await self.native.new_context(**allowed, storage_state=copy.deepcopy(state),
                permissions=[], ignore_https_errors=False, accept_downloads=False, service_workers="block")

    class BrowserType:
        def __init__(self, native):
            self.native = native

        async def launch(self, **kwargs):
            channel = kwargs.get("channel")
            if channel not in (None, "chrome", "msedge", "chromium") or kwargs.get("proxy"):
                raise RuntimeError("Unsupported monitor browser configuration")
            return Browser(await self.native.launch(headless=True, chromium_sandbox=True,
                args=["--disable-dev-shm-usage", "--enable-automation"], **({"channel": channel} if channel else {})))

    class Manager:
        def __init__(self):
            self.manager = factory()

        async def __aenter__(self):
            playwright = await self.manager.__aenter__()
            return SimpleNamespace(chromium=BrowserType(playwright.chromium))

        async def __aexit__(self, *args):
            return await self.manager.__aexit__(*args)

    return Manager
