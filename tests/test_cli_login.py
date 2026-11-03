from __future__ import annotations

import sys
from pathlib import Path

import pytest

import shopping_agent.cli as cli_module
from shopping_agent.browser.session import LoginResult
from shopping_agent.config import AppConfig


def _run_login(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    result: LoginResult,
) -> None:
    config = AppConfig(browser_profile_dir=tmp_path / "browser-profile")

    class FakeBrowserSession:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def open_for_login(self, _platform: str) -> LoginResult:
            return result

    monkeypatch.setattr(cli_module, "load_config", lambda _path: config)
    monkeypatch.setattr(cli_module, "BrowserSession", FakeBrowserSession)
    monkeypatch.setattr(sys, "argv", ["shopping-agent", "login", "xianyu"])
    cli_module.main()


def test_login_command_exits_when_xianyu_login_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        _run_login(
            monkeypatch,
            tmp_path,
            LoginResult(platform="xianyu", authenticated=False),
        )

    assert caught.value.code == 2
    assert "Login was not completed" in capsys.readouterr().out


def test_login_command_reports_verified_xianyu_login(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_login(
        monkeypatch,
        tmp_path,
        LoginResult(platform="xianyu", authenticated=True),
    )

    assert "Login verified" in capsys.readouterr().out
