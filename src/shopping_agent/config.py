from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


class SafetyConfig(BaseModel):
    auto_cover_cache_enabled: bool = True  # Basic thumbnails; independent of visual-model gates.
    allow_send_message: bool = False
    allow_purchase: bool = False
    allow_payment: bool = False
    allow_account_settings_change: bool = False
    allow_submit_forms: bool = False
    require_account_risk_confirmation: bool = True
    xianyu_allow_headless: bool = False
    xianyu_max_detail_pages_per_run: int = 12
    xianyu_min_search_interval_seconds: int = 1800
    xianyu_min_delay_ms: int = 3000
    xianyu_max_delay_ms: int = 8000
    stop_on_access_blocked: bool = True


class MonitorEngineConfig(BaseModel):
    enabled: bool = False
    capture_logs: bool = True
    root: Path | None = None
    python: Path | None = None
    state_file: Path | None = None
    work_dir: Path = Path("data/monitor-engine")
    timeout_seconds: int = Field(default=1800, ge=10, le=7200)


class AppConfig(BaseModel):
    default_city: str = "上海"
    codex_bin: str = "codex"
    codex_timeout_seconds: int = 300
    database_path: Path = Path("data/shopping.sqlite")
    browser_profile_dir: Path = Path("data/browser-profile")
    reports_dir: Path = Path("data/reports")
    screenshots_dir: Path = Path("data/screenshots")
    media_dir: Path = Path("data/media")
    platforms: list[str] = Field(default_factory=lambda: ["xianyu"])
    allow_login: bool = True
    allow_favorite: bool = False
    allow_ocr: bool = True
    max_pages_per_platform: int = 3
    max_listings_per_platform: int = 50
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    monitor_engine: MonitorEngineConfig = Field(default_factory=MonitorEngineConfig)


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        return tomllib.load(file)


def load_config(path: Path = Path("config/default.toml")) -> AppConfig:
    if not path.exists():
        return AppConfig()
    return AppConfig.model_validate(_load_toml(path))


def load_effective_config(
    default_path: Path = Path("config/default.toml"),
    settings_path: Path = Path("data/settings.json"),
) -> AppConfig:
    from shopping_agent.user_settings import load_user_settings

    config = load_config(default_path)
    settings = load_user_settings(settings_path)
    updates: dict[str, object] = {
        "platforms": settings.platforms,
        "allow_ocr": settings.allow_ocr,
    }
    if settings.default_city:
        updates["default_city"] = settings.default_city
    return config.model_copy(update=updates)


def ensure_runtime_dirs(config: AppConfig) -> None:
    for path in (
        config.database_path.parent,
        config.browser_profile_dir,
        config.reports_dir,
        config.screenshots_dir,
        config.media_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
