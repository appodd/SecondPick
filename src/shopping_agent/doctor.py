from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from shopping_agent.config import AppConfig
from shopping_agent.db import initialize


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_doctor(config: AppConfig, check_browser: bool = True) -> list[CheckResult]:
    results = [
        CheckResult("config", True, f"default_city={config.default_city}"),
    ]

    try:
        initialize(config.database_path)
        results.append(CheckResult("database", True, str(config.database_path)))
    except Exception as exc:  # pragma: no cover - defensive CLI reporting
        results.append(CheckResult("database", False, str(exc)))

    if check_browser:
        results.append(_check_playwright())

    return results


def _check_playwright() -> CheckResult:
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return CheckResult("playwright", True, "chromium headless launch ok")
    except PlaywrightError as exc:
        return CheckResult("playwright", False, str(exc))
    except Exception as exc:  # pragma: no cover - environment-specific
        return CheckResult("playwright", False, str(exc))
