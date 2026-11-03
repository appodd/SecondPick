from pathlib import Path
from subprocess import CompletedProcess

import pytest
from pydantic import ValidationError

from shopping_agent.config import AppConfig
from shopping_agent.setup_status import (
    CodexStatus,
    SetupCheck,
    build_setup_status,
    check_codex_availability,
)
from shopping_agent.user_settings import UserSettings


def test_codex_check_separates_installation_and_authentication(monkeypatch) -> None:
    calls: list[tuple[object, dict[str, object]]] = []

    monkeypatch.setattr(
        "shopping_agent.setup_status.shutil.which", lambda _: "C:/bin/codex.exe"
    )

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return CompletedProcess(args[0], 0, "Logged in using sk-secret-value", "")

    monkeypatch.setattr("shopping_agent.setup_status.subprocess.run", fake_run)

    result = check_codex_availability(timeout_seconds=2)

    assert result.cli_available is True
    assert result.auth_available is True
    assert result.process_running is False
    assert result.detail == "authenticated"
    assert calls == [
        (
            (["C:/bin/codex.exe", "login", "status"],),
            {
                "capture_output": True,
                "text": True,
                "timeout": 2,
                "shell": False,
            },
        )
    ]


def test_codex_check_redacts_failed_authentication_output(monkeypatch) -> None:
    monkeypatch.setattr(
        "shopping_agent.setup_status.shutil.which", lambda _: "C:/bin/codex.exe"
    )
    monkeypatch.setattr(
        "shopping_agent.setup_status.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(
            args[0], 1, "", "API key sk-secret-value is invalid"
        ),
    )

    result = check_codex_availability()

    assert result.cli_available is True
    assert result.auth_available is False
    assert result.detail == "authentication required"
    assert "secret" not in result.model_dump_json()


def test_codex_check_reports_missing_cli_without_starting_a_process(monkeypatch) -> None:
    monkeypatch.setattr("shopping_agent.setup_status.shutil.which", lambda _: None)

    def unexpected_run(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called without a CLI")

    monkeypatch.setattr("shopping_agent.setup_status.subprocess.run", unexpected_run)

    result = check_codex_availability()

    assert result == CodexStatus(
        cli_available=False,
        auth_available=False,
        process_running=False,
        detail="check failed",
    )


def test_codex_check_redacts_execution_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "shopping_agent.setup_status.shutil.which", lambda _: "C:/bin/codex.exe"
    )

    def failed_run(*args, **kwargs):
        raise OSError("sk-secret-value leaked from the environment")

    monkeypatch.setattr("shopping_agent.setup_status.subprocess.run", failed_run)

    result = check_codex_availability()

    assert result.cli_available is True
    assert result.auth_available is False
    assert result.detail == "check failed"
    assert "secret" not in result.model_dump_json()


def test_setup_status_does_not_claim_xianyu_auth_from_profile_directory(
    tmp_path: Path, monkeypatch
) -> None:
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    (profile / "Preferences").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "shopping_agent.setup_status.check_codex_availability",
        lambda: CodexStatus(
            cli_available=True,
            auth_available=True,
            detail="authenticated",
        ),
    )

    status = build_setup_status(
        AppConfig(database_path=tmp_path / "db.sqlite", browser_profile_dir=profile),
        UserSettings(),
        check_browser=False,
    )

    assert status.xianyu.profile_present is True
    assert status.xianyu.auth_status == "unknown"
    assert status.can_browse_existing_data is True
    assert status.can_start_research is False
    assert [check.name for check in status.environment] == ["config", "database"]


@pytest.mark.parametrize("profile_kind", ["missing", "empty", "file"])
def test_setup_status_requires_nonempty_profile_directory(
    tmp_path: Path, monkeypatch, profile_kind: str
) -> None:
    profile = tmp_path / "browser-profile"
    if profile_kind == "empty":
        profile.mkdir()
    elif profile_kind == "file":
        profile.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(
        "shopping_agent.setup_status.check_codex_availability",
        lambda: CodexStatus(
            cli_available=True,
            auth_available=True,
            detail="authenticated",
        ),
    )

    status = build_setup_status(
        AppConfig(database_path=tmp_path / "db.sqlite", browser_profile_dir=profile),
        UserSettings(),
        check_browser=False,
    )

    assert status.xianyu.profile_present is False


def test_setup_status_default_check_is_browser_free(tmp_path: Path, monkeypatch) -> None:
    doctor_calls: list[bool] = []

    def fake_run_doctor(config, check_browser=True):
        doctor_calls.append(check_browser)
        return []

    monkeypatch.setattr("shopping_agent.setup_status.run_doctor", fake_run_doctor)
    monkeypatch.setattr(
        "shopping_agent.setup_status.check_codex_availability",
        lambda: CodexStatus(
            cli_available=True,
            auth_available=True,
            detail="authenticated",
        ),
    )

    build_setup_status(
        AppConfig(
            database_path=tmp_path / "db.sqlite",
            browser_profile_dir=tmp_path / "browser-profile",
        ),
        UserSettings(),
    )

    assert doctor_calls == [False]


def test_setup_status_models_are_immutable() -> None:
    check = SetupCheck(name="config", ok=True, detail="ready")

    with pytest.raises(ValidationError):
        check.ok = False
