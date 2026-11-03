from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from shopping_agent.config import AppConfig, load_effective_config
from shopping_agent.user_settings import UserSettings, load_user_settings
from shopping_agent.web.services import WorkbenchService


def get_config_path(request: Request) -> Path:
    return request.app.state.config_path


def get_settings_path(request: Request) -> Path:
    return request.app.state.settings_path


def get_config(
    config_path: Annotated[Path, Depends(get_config_path)],
    settings_path: Annotated[Path, Depends(get_settings_path)],
) -> AppConfig:
    return load_effective_config(config_path, settings_path)


def get_settings(
    settings_path: Annotated[Path, Depends(get_settings_path)],
) -> UserSettings:
    return load_user_settings(settings_path)


def get_workbench_service(
    config: Annotated[AppConfig, Depends(get_config)],
) -> WorkbenchService:
    return WorkbenchService(config)
