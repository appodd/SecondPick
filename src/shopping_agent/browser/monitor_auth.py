"""DPAPI snapshot for monitoring, separate from legacy session restoration."""
import json
import os

from shopping_agent.browser.auth_state import _protect
from shopping_agent.db import connect
from shopping_agent.goofish_browser import monitor_cookies, CredentialError, MAX_CREDENTIAL_BYTES

MONITOR_STATE_NAME = "shopping-monitor.dpapi"


async def save_monitor_login(context, profile_dir):
    if os.name != "nt":
        return  # No plaintext fallback on platforms without the existing DPAPI provider.
    state = monitor_cookies(dict(cookies=await context.cookies()))
    payload = json.dumps(state, separators=(",", ":")).encode()
    if len(payload) > MAX_CREDENTIAL_BYTES:
        raise CredentialError("Invalid monitor credential")
    target = profile_dir / MONITOR_STATE_NAME
    pending = target.with_suffix(".tmp")
    pending.write_bytes(_protect(payload))
    pending.replace(target)


def load_monitor_login(config):
    external = config.monitor_engine.state_file
    source = external if external is not None else config.browser_profile_dir / MONITOR_STATE_NAME
    try:
        if external is None:
            with connect(config.database_path, timeout=.25) as conn:
                row = conn.execute("SELECT state FROM browser_auth WHERE id=1").fetchone()
            if not row or row["state"] != "verified":
                raise CredentialError("Monitor login required")
        with source.open("rb") as stream:
            payload = stream.read(MAX_CREDENTIAL_BYTES + 65537)
        if len(payload) > MAX_CREDENTIAL_BYTES + 65536:
            raise CredentialError("Invalid monitor credential")
        if external is None:
            payload = _protect(payload, decrypt=True)
        if len(payload) > MAX_CREDENTIAL_BYTES:
            raise CredentialError("Invalid monitor credential")
        state = monitor_cookies(json.loads(payload))
        encoded = json.dumps(state, separators=(",", ":")).encode()
        if len(encoded) > MAX_CREDENTIAL_BYTES:
            raise CredentialError("Invalid monitor credential")
        return encoded, source.stat().st_mtime, external is None
    except CredentialError:
        raise
    except Exception:
        raise CredentialError("Monitor login required") from None
