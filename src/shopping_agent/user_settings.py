from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    setup_completed: bool = False
    setup_mode: Literal["basic", "ai"] = "basic"
    default_city: str | None = None
    platforms: list[str] = Field(default_factory=lambda: ["xianyu"])
    allow_ocr: bool = True
    preferred_view: Literal["research", "debug"] = "research"


def load_user_settings(path: Path) -> UserSettings:
    if not path.exists():
        return UserSettings()
    return UserSettings.model_validate_json(path.read_text(encoding="utf-8"))


def save_user_settings(path: Path, settings: UserSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, path)
