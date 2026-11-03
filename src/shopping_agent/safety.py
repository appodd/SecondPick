from __future__ import annotations

import math
import random
import time
from datetime import datetime, timezone

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_platform_access_event,
    connect,
    fetch_latest_platform_access_event,
    initialize,
)


RISKY_BROWSER_PLATFORMS = {"xianyu"}


class SafetyError(RuntimeError):
    pass


def reserve_search_access(
    config: AppConfig,
    *,
    platform: str,
    query: str,
    now: datetime | None = None,
) -> None:
    if platform != "xianyu":
        return

    attempted_at = now or datetime.now(timezone.utc)
    if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
        raise ValueError("Search reservation timestamps must include a timezone.")
    attempted_at = attempted_at.astimezone(timezone.utc)
    interval = config.safety.xianyu_min_search_interval_seconds

    initialize(config.database_path)
    with connect(config.database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        latest = fetch_latest_platform_access_event(
            conn,
            platform=platform,
            operation="search",
        )
        if latest is not None:
            last_attempt = datetime.fromisoformat(latest["attempted_at"])
            elapsed = (attempted_at - last_attempt).total_seconds()
            if elapsed < interval:
                remaining = math.ceil(interval - elapsed)
                raise SafetyError(
                    "Xianyu search cooldown is active: "
                    f"{remaining} seconds remaining; last attempt was "
                    f"{latest['attempted_at']}. Reuse saved evidence instead."
                )
        add_platform_access_event(
            conn,
            platform=platform,
            operation="search",
            target=query,
            attempted_at=attempted_at.isoformat(),
        )
        conn.commit()


def enforce_browser_collection_safety(
    config: AppConfig,
    platform: str,
    headless: bool,
    acknowledged_risk: bool,
    detail_limit: int | None = None,
) -> None:
    if platform not in RISKY_BROWSER_PLATFORMS:
        return

    if config.safety.require_account_risk_confirmation and not acknowledged_risk:
        raise SafetyError(
            "Xianyu browser automation requires explicit account-risk acknowledgement. "
            "Rerun with --i-understand-account-risk after reading docs/account-risk.md."
        )

    if headless and not config.safety.xianyu_allow_headless:
        raise SafetyError(
            "Headless Xianyu access is disabled because it has triggered access blocking. "
            "Run without --headless."
        )

    if detail_limit is not None and detail_limit > config.safety.xianyu_max_detail_pages_per_run:
        raise SafetyError(
            "Requested Xianyu detail limit exceeds configured safety cap "
            f"({detail_limit} > {config.safety.xianyu_max_detail_pages_per_run})."
        )


def safety_delay(config: AppConfig, platform: str) -> None:
    if platform != "xianyu":
        return
    min_ms = config.safety.xianyu_min_delay_ms
    max_ms = config.safety.xianyu_max_delay_ms
    if max_ms <= 0:
        return
    if min_ms > max_ms:
        min_ms, max_ms = max_ms, min_ms
    time.sleep(random.uniform(min_ms, max_ms) / 1000)
