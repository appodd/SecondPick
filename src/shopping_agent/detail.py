from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from shopping_agent.browser.session import BrowserSession, DetailSnapshot
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_listing_snapshot,
    add_media_asset,
    add_detail_snapshot,
    add_seller_items,
    connect,
    create_query,
    create_search_run,
    fetch_listing_urls_for_run,
    initialize,
    listing_url_belongs_to_run as db_listing_url_belongs_to_run,
    upsert_listing,
)
from shopping_agent.platforms.xianyu_detail_parser import parse_xianyu_detail_api, parse_xianyu_detail_text
from shopping_agent.platforms.xianyu_images import select_xianyu_product_images
from shopping_agent.safety import SafetyError, safety_delay


@dataclass
class DetailCaptureResult:
    url: str
    listing_id: int
    run_id: int | None
    snapshot: DetailSnapshot
    detail_snapshot_id: int


async def capture_detail_url(
    config: AppConfig,
    url: str,
    platform: str = "xianyu",
    run_id: int | None = None,
    wait_ms: int = 5000,
    headless: bool = False,
    source_type: str = "web_search",
    source_label: str = "网页搜索",
    profile_lock_timeout_seconds: float = 120.0,
    profile_lock_stale_after_seconds: float = 600.0,
    verification_callback=None,
    verification_result_callback=None,
) -> DetailCaptureResult:
    with browser_profile_lock(config.browser_profile_dir, timeout_seconds=profile_lock_timeout_seconds,
                              stale_after_seconds=profile_lock_stale_after_seconds):
        session = BrowserSession(config.browser_profile_dir, headless=headless)
        snapshot = await session.capture_detail_snapshot(
            url=url,
            output_dir=config.screenshots_dir,
            wait_ms=wait_ms,
            **({"verification_callback": verification_callback} if verification_callback is not None else {}),
            **({"verification_result_callback": verification_result_callback} if verification_result_callback is not None else {}),
        )
    if snapshot.login_required:
        raise SafetyError("Login required while capturing detail page.")
    if snapshot.access_blocked and config.safety.stop_on_access_blocked:
        raise SafetyError(f"Access blocked while capturing detail page: {url}")

    parsed = parse_xianyu_detail_api(snapshot.api_detail) if platform == "xianyu" else None
    attributes_source = "xianyu_api_item_labels" if parsed is not None else None
    if parsed is None and platform == "xianyu":
        parsed = parse_xianyu_detail_text(snapshot.visible_text)
        attributes_source = "detail_dom_fallback"
    if platform == "xianyu" and (parsed is None or not parsed.description.strip() or not parsed.price_text):
        # A shell, recommendation feed or verification overlay is not evidence
        # for the requested item. Never overwrite a useful search snapshot.
        raise SafetyError("Detail content unavailable; target item was not loaded.")

    initialize(config.database_path)
    with connect(config.database_path) as conn:
        listing_id = upsert_listing(conn, platform=platform, url=url)
        effective_run_id = run_id
        if effective_run_id is None:
            effective_run_id = create_search_run(
                conn,
                goal=f"Manual candidate URL: {url}",
                city=config.default_city,
            )
            create_query(
                conn,
                run_id=effective_run_id,
                platform=platform,
                query_text=f"manual-url:{url}",
            )
        if parsed is not None:
            add_listing_snapshot(
                conn,
                listing_id=listing_id,
                run_id=effective_run_id,
                title=snapshot.api_detail.get("item", {}).get("title") or snapshot.page_title if snapshot.api_detail else snapshot.page_title,
                price_text=parsed.price_text,
                location=parsed.seller_location,
                seller_name=parsed.seller_name,
                description=parsed.description,
                source_type=source_type,
                source_label=source_label,
                seller_credit_level=parsed.seller_credit_level,
                seller_registered_days=parsed.seller_registered_days,
                seller_sold_count=parsed.seller_sold_count,
                seller_good_rate=parsed.seller_good_rate,
                seller_realname_verified=parsed.seller_realname_verified,
                seller_reply_rate_24h=parsed.seller_reply_rate_24h,
            )
        detail_snapshot_id = add_detail_snapshot(
            conn,
            listing_id=listing_id,
            run_id=effective_run_id,
            url=url,
            title=snapshot.page_title,
            screenshot_path=snapshot.screenshot_path,
            html_path=snapshot.html_path,
            text_path=snapshot.text_path,
            links_path=snapshot.links_path,
            images_path=snapshot.images_path,
            link_count=len(snapshot.links),
            image_count=len(snapshot.image_urls),
            access_blocked=snapshot.access_blocked,
            attributes_json=json.dumps(
                parsed.attributes if parsed is not None else {},
                ensure_ascii=False,
            ),
            attributes_source=attributes_source,
        )
        for image_url in _select_product_images(platform, snapshot.image_urls):
            add_media_asset(
                conn,
                listing_id=listing_id,
                media_type="product_image_url",
                source_url=image_url,
                local_path="",
            )
        if platform == "xianyu" and snapshot.api_detail:
            seller_items = (snapshot.api_detail.get("seller") or {}).get("sellerItems") or []
            if seller_items:
                add_seller_items(
                    conn,
                    seller_listing_id=listing_id,
                    seller_name=parsed.seller_name if parsed else None,
                    items=seller_items,
                    source_run_id=effective_run_id,
                )

    return DetailCaptureResult(
        url=url,
        listing_id=listing_id,
        run_id=effective_run_id,
        snapshot=snapshot,
        detail_snapshot_id=detail_snapshot_id,
    )


def get_listing_urls_for_run(config: AppConfig, run_id: int, limit: int) -> list[str]:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        return fetch_listing_urls_for_run(conn, run_id=run_id, limit=limit)


def listing_url_belongs_to_run(config: AppConfig, run_id: int, url: str) -> bool:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        return db_listing_url_belongs_to_run(conn, run_id=run_id, url=url)


def wait_between_detail_pages(config: AppConfig, platform: str) -> None:
    safety_delay(config, platform)


def _likely_product_images(image_urls: list[str]) -> list[str]:
    seen = set()
    results = []
    for url in image_urls:
        if "xy_item" not in url and "mtopupload" not in url:
            continue
        normalized = url.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    return results


def _select_product_images(platform: str, image_urls: list[str]) -> list[str]:
    if platform == "xianyu":
        return select_xianyu_product_images(image_urls)
    return _likely_product_images(image_urls)


@contextmanager
def browser_profile_lock(
    profile_dir: Path,
    timeout_seconds: float = 120.0,
    stale_after_seconds: float = 600.0,
):
    lock_path = profile_dir.parent / f"{profile_dir.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.monotonic()
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            _remove_stale_lock(lock_path, stale_after_seconds)
            if time.monotonic() - started_at >= timeout_seconds:
                raise SafetyError(
                    "Browser profile is already in use. Run detail captures serially to avoid "
                    "account and browser-profile risk."
                )
            time.sleep(0.5)
    try:
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _remove_stale_lock(lock_path: Path, stale_after_seconds: float) -> None:
    try:
        age = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return
    if age < stale_after_seconds:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
