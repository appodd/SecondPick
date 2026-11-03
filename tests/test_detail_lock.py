from __future__ import annotations

import pytest

from shopping_agent.detail import browser_profile_lock
from shopping_agent.safety import SafetyError


def test_browser_profile_lock_rejects_busy_profile(tmp_path) -> None:
    profile_dir = tmp_path / "browser-profile"
    lock_path = tmp_path / "browser-profile.lock"
    lock_path.write_text("busy", encoding="utf-8")

    with pytest.raises(SafetyError):
        with browser_profile_lock(profile_dir, timeout_seconds=0.01, stale_after_seconds=9999):
            raise AssertionError("lock should not be acquired")
