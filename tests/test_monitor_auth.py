import asyncio
import json
import os

import pytest

from shopping_agent.browser.monitor_auth import save_monitor_login, load_monitor_login, MONITOR_STATE_NAME
from shopping_agent.browser_jobs import BrowserJobStore
from shopping_agent.config import AppConfig, MonitorEngineConfig
from shopping_agent.goofish_browser import CredentialError
from test_goofish_browser import cookie


def test_admin_fallback_is_filtered_without_copying_plaintext(tmp_path):
    source = tmp_path / "provided.json"
    source.write_text(json.dumps(dict(cookies=[cookie(), cookie(".taobao.com")], headers={"secret": "private"})))
    config = AppConfig(monitor_engine=MonitorEngineConfig(state_file=source))
    payload, mtime, shared = load_monitor_login(config)
    assert not shared and mtime == source.stat().st_mtime
    assert len(json.loads(payload)["cookies"]) == 1 and "private" not in payload.decode()
    assert list(tmp_path.iterdir()) == [source]


def test_encoded_credential_size_is_checked_before_pipe_launch(tmp_path):
    source = tmp_path / "provided.json"
    source.write_text(json.dumps(dict(cookies=[cookie(name=f"probe-{n}", value="中" * 15000) for n in range(20)]),
                                ensure_ascii=False), encoding="utf-8")
    assert source.stat().st_size < 1024 * 1024
    config = AppConfig(monitor_engine=MonitorEngineConfig(state_file=source))
    with pytest.raises(CredentialError, match="Invalid monitor credential"):
        load_monitor_login(config)


@pytest.mark.skipif(os.name != "nt", reason="Existing credential provider uses Windows DPAPI")
def test_dpapi_monitor_export_is_scoped_encrypted_and_requires_verified_login(tmp_path):
    config = AppConfig(database_path=tmp_path / "db.sqlite", browser_profile_dir=tmp_path / "profile")
    config.browser_profile_dir.mkdir()
    store = BrowserJobStore(config)
    class Context:
        async def cookies(self):
            return [cookie(), cookie(name="persistent_probe", expires=2e9), cookie(".taobao.com", value="other-account")]
    asyncio.run(save_monitor_login(Context(), config.browser_profile_dir))
    encrypted = (config.browser_profile_dir / MONITOR_STATE_NAME).read_bytes()
    assert b"synthetic-secret" not in encrypted and b"persistent_probe" not in encrypted
    with pytest.raises(CredentialError):
        load_monitor_login(config)
    store.set_auth("verified")
    payload, _, shared = load_monitor_login(config)
    assert shared and len(json.loads(payload)["cookies"]) == 2
    assert b"other-account" not in payload
    store.set_auth("invalid")
    with pytest.raises(CredentialError):
        load_monitor_login(config)


@pytest.mark.skipif(os.name != "nt", reason="Existing credential provider uses Windows DPAPI")
def test_failed_monitor_export_preserves_previous_encrypted_snapshot(tmp_path):
    class Context:
        async def cookies(self):
            return [cookie()]
    asyncio.run(save_monitor_login(Context(), tmp_path))
    path = tmp_path / MONITOR_STATE_NAME
    before = path.read_bytes()
    class Closed:
        async def cookies(self):
            raise RuntimeError("closed browser")
    with pytest.raises(RuntimeError):
        asyncio.run(save_monitor_login(Closed(), tmp_path))
    assert path.read_bytes() == before
