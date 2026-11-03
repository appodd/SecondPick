from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import shopping_agent.safety as safety_module
import shopping_agent.spike as spike_module
from shopping_agent.browser.session import SearchSnapshot
from shopping_agent.config import AppConfig
from shopping_agent.db import connect, initialize


SafetyError = safety_module.SafetyError


def reserve_search_access(*args, **kwargs) -> None:
    safety_module.reserve_search_access(*args, **kwargs)


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(database_path=tmp_path / "search-cooldown.sqlite")


def test_xianyu_search_reservation_enforces_1800_second_boundary(tmp_path: Path) -> None:
    config = _config(tmp_path)
    started_at = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)

    reserve_search_access(
        config,
        platform="xianyu",
        query="富士 X-S20",
        now=started_at,
    )

    with pytest.raises(SafetyError, match="1 seconds remaining"):
        reserve_search_access(
            config,
            platform="xianyu",
            query="富士 X-S20 单机身",
            now=started_at + timedelta(seconds=1799),
        )

    reserve_search_access(
        config,
        platform="xianyu",
        query="富士 X-S20 单机身",
        now=started_at + timedelta(seconds=1800),
    )


def test_xianyu_search_cooldown_persists_across_config_instances(tmp_path: Path) -> None:
    first_config = _config(tmp_path)
    second_config = _config(tmp_path)
    started_at = datetime(2026, 8, 7, 2, 0, tzinfo=timezone.utc)

    reserve_search_access(
        first_config,
        platform="xianyu",
        query="松下 S5M2",
        now=started_at,
    )

    with pytest.raises(SafetyError, match=re.escape(started_at.isoformat())):
        reserve_search_access(
            second_config,
            platform="xianyu",
            query="松下 S5M2 单机身",
            now=started_at + timedelta(minutes=10),
        )


def test_non_xianyu_search_does_not_create_cooldown_event(tmp_path: Path) -> None:
    config = _config(tmp_path)
    now = datetime(2026, 8, 7, 3, 0, tzinfo=timezone.utc)

    reserve_search_access(config, platform="jd", query="相机", now=now)
    reserve_search_access(config, platform="jd", query="相机", now=now)

    initialize(config.database_path)
    with connect(config.database_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM platform_access_events").fetchone()[0]
    assert count == 0


def test_capture_search_spike_reserves_before_browser_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    call_order = []

    def fake_reserve(*_args, **_kwargs) -> None:
        call_order.append("reserve")

    class FakeBrowserSession:
        def __init__(self, *_args, **_kwargs) -> None:
            call_order.append("browser")

        async def capture_search_snapshot(self, **_kwargs):
            raise RuntimeError("stop after ordering assertion")

    monkeypatch.setattr(spike_module, "reserve_search_access", fake_reserve)
    monkeypatch.setattr(spike_module, "BrowserSession", FakeBrowserSession)

    with pytest.raises(RuntimeError, match="ordering assertion"):
        asyncio.run(
            spike_module.capture_search_spike(
                config,
                platform="xianyu",
                query="富士 X-S20",
            )
        )

    assert call_order == ["reserve", "browser"]


def test_capture_search_spike_persists_partial_run_before_safety_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        database_path=tmp_path / "partial-search.sqlite",
        browser_profile_dir=tmp_path / "browser-profile",
        screenshots_dir=tmp_path / "screenshots",
    )
    html_path = config.screenshots_dir / "partial.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html><body>partial first page</body></html>", encoding="utf-8")

    class FakeBrowserSession:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def capture_search_snapshot(self, **_kwargs) -> SearchSnapshot:
            return SearchSnapshot(
                platform="xianyu",
                query="索尼 A7C2 单机",
                url="https://www.goofish.com/search?q=Sony+A7C2",
                screenshot_path=config.screenshots_dir / "partial.png",
                html_path=html_path,
                page_title="索尼 A7C2 单机_闲鱼",
                visible_text="partial first page",
                links=[],
                access_blocked=False,
                api_page_count=1,
                requested_page_count=3,
                stop_reason="login_required",
            )

    monkeypatch.setattr(spike_module, "reserve_search_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(spike_module, "BrowserSession", FakeBrowserSession)

    with pytest.raises(spike_module.SearchSpikeSafetyError) as caught:
        asyncio.run(
            spike_module.capture_search_spike(
                config,
                platform="xianyu",
                query="索尼 A7C2 单机",
                max_pages=3,
            )
        )

    result = caught.value.result
    assert result.snapshot.stop_reason == "login_required"
    assert result.run_id > 0
    assert result.status_path is not None
    assert json.loads(result.status_path.read_text(encoding="utf-8")) == {
        "platform": "xianyu",
        "query": "索尼 A7C2 单机",
        "requested_page_count": 3,
        "api_page_count": 1,
        "stop_reason": "login_required",
        "access_blocked": False,
    }
    with connect(config.database_path) as conn:
        page = conn.execute(
            "SELECT run_id, access_blocked FROM page_snapshots WHERE run_id = ?",
            (result.run_id,),
        ).fetchone()
    assert page is not None
    assert page["run_id"] == result.run_id


def test_capture_search_spike_respects_disabled_access_block_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        database_path=tmp_path / "allowed-blocked-search.sqlite",
        browser_profile_dir=tmp_path / "browser-profile",
        screenshots_dir=tmp_path / "screenshots",
        safety={"stop_on_access_blocked": False},
    )
    html_path = config.screenshots_dir / "blocked.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html><body>访问受限</body></html>", encoding="utf-8")

    class FakeBrowserSession:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def capture_search_snapshot(self, **_kwargs) -> SearchSnapshot:
            return SearchSnapshot(
                platform="xianyu",
                query="test",
                url="https://www.goofish.com/search?q=test",
                screenshot_path=config.screenshots_dir / "blocked.png",
                html_path=html_path,
                page_title="访问受限",
                visible_text="访问受限",
                links=[],
                access_blocked=True,
                requested_page_count=1,
                stop_reason="access_blocked",
            )

    monkeypatch.setattr(spike_module, "reserve_search_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(spike_module, "BrowserSession", FakeBrowserSession)

    result = asyncio.run(
        spike_module.capture_search_spike(
            config,
            platform="xianyu",
            query="test",
        )
    )

    assert result.snapshot.stop_reason == "access_blocked"
