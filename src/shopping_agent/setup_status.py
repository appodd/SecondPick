from __future__ import annotations

import shutil
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict

from shopping_agent.config import AppConfig
from shopping_agent.doctor import run_doctor
from shopping_agent.user_settings import UserSettings


class SetupCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    ok: bool
    detail: str


class CodexStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    cli_available: bool
    auth_available: bool
    process_running: bool = False
    detail: str


class XianyuStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_present: bool
    auth_status: Literal["unknown", "verified", "invalid"]
    detail: str


class SetupStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    setup_completed: bool
    environment: list[SetupCheck]
    codex: CodexStatus
    xianyu: XianyuStatus
    can_browse_existing_data: bool = True
    can_start_research: bool


def check_codex_availability(timeout_seconds: int = 10) -> CodexStatus:
    codex_path = shutil.which("codex")
    if codex_path is None:
        return CodexStatus(
            cli_available=False,
            auth_available=False,
            detail="check failed",
        )

    try:
        result = subprocess.run(
            [codex_path, "login", "status"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return CodexStatus(
            cli_available=True,
            auth_available=False,
            detail="check failed",
        )

    authenticated = result.returncode == 0
    return CodexStatus(
        cli_available=True,
        auth_available=authenticated,
        detail="authenticated" if authenticated else "authentication required",
    )


def build_setup_status(
    config: AppConfig,
    settings: UserSettings,
    check_browser: bool = True,
) -> SetupStatus:
    del check_browser
    environment = [
        SetupCheck(name=result.name, ok=result.ok, detail=result.detail)
        for result in run_doctor(config, check_browser=False)
    ]
    codex = check_codex_availability()
    try:
        profile_present = config.browser_profile_dir.is_dir() and any(
            config.browser_profile_dir.iterdir()
        )
    except OSError:
        profile_present = False
    xianyu = XianyuStatus(
        profile_present=profile_present,
        auth_status="unknown",
        detail=(
            "profile present; authentication unknown"
            if profile_present
            else "profile not present; authentication unknown"
        ),
    )
    can_start_research = (
        settings.setup_completed
        and all(check.ok for check in environment)
        and codex.auth_available
        and xianyu.auth_status == "verified"
    )
    return SetupStatus(
        setup_completed=settings.setup_completed,
        environment=environment,
        codex=codex,
        xianyu=xianyu,
        can_start_research=can_start_research,
    )
