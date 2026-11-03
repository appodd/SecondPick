from __future__ import annotations

import asyncio
from dataclasses import dataclass

from shopping_agent.analysis import ImageAnalysisRecord, analyze_downloaded_images
from shopping_agent.config import AppConfig
from shopping_agent.detail import capture_detail_url, wait_between_detail_pages
from shopping_agent.db import (
    connect,
    fetch_listing_urls_for_run_needing_detail,
    initialize,
)
from shopping_agent.evidence import build_listing_evidence, evidence_bundle_to_dict
from shopping_agent.media import MediaDownloadResult, download_pending_media
from shopping_agent.run_summary import RunSummaryOptions, build_run_summary
from shopping_agent.safety import SafetyError, enforce_browser_collection_safety


@dataclass
class DetailPrepared:
    url: str
    detail_snapshot_id: int


@dataclass
class PrepareEvidenceResult:
    run_id: int
    captured_details: list[DetailPrepared]
    downloaded_media: list[MediaDownloadResult]
    analyzed_images: list[ImageAnalysisRecord]
    ready_listing_ids: list[int]
    summary: dict
    evidence_bundles: list[dict]


async def prepare_run_evidence(
    config: AppConfig,
    run_id: int,
    platform: str = "xianyu",
    detail_limit: int = 3,
    media_limit: int = 0,
    ocr_limit: int = 0,
    wait_ms: int = 5000,
    headless: bool = False,
    acknowledged_risk: bool = False,
    ocr_backend: str = "auto",
    build_evidence_limit: int = 3,
    evidence_ocr_chars: int = 800,
) -> PrepareEvidenceResult:
    if detail_limit > 0:
        enforce_browser_collection_safety(
            config=config,
            platform=platform,
            headless=headless,
            acknowledged_risk=acknowledged_risk,
            detail_limit=detail_limit,
        )

    captured_details = await _capture_missing_details(
        config=config,
        run_id=run_id,
        platform=platform,
        detail_limit=detail_limit,
        wait_ms=wait_ms,
        headless=headless,
    )
    downloaded_media = download_pending_media(
        config,
        limit=media_limit,
        media_type="product_image_url",
        run_id=run_id,
    )
    analyzed_images = analyze_downloaded_images(
        config,
        media_type="product_image_url",
        limit=ocr_limit,
        backend=ocr_backend,
        run_id=run_id,
    )
    summary = build_run_summary(
        config,
        run_id=run_id,
        options=RunSummaryOptions(listing_limit=max(build_evidence_limit, detail_limit, 1)),
    )
    ready_listing_ids = _ready_listing_ids(summary, limit=build_evidence_limit)
    evidence_bundles = []
    for listing_id in ready_listing_ids:
        try:
            bundle = build_listing_evidence(config, listing_id=listing_id)
        except ValueError:
            continue
        evidence_bundles.append(_compact_evidence_bundle(evidence_bundle_to_dict(bundle), evidence_ocr_chars))

    return PrepareEvidenceResult(
        run_id=run_id,
        captured_details=captured_details,
        downloaded_media=downloaded_media,
        analyzed_images=analyzed_images,
        ready_listing_ids=ready_listing_ids,
        summary=summary,
        evidence_bundles=evidence_bundles,
    )


async def _capture_missing_details(
    config: AppConfig,
    run_id: int,
    platform: str,
    detail_limit: int,
    wait_ms: int,
    headless: bool,
) -> list[DetailPrepared]:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        urls = fetch_listing_urls_for_run_needing_detail(conn, run_id=run_id, limit=detail_limit)

    captured = []
    for index, url in enumerate(urls, start=1):
        if index > 1:
            wait_between_detail_pages(config, platform)
        try:
            result = await capture_detail_url(
                config=config,
                url=url,
                platform=platform,
                run_id=run_id,
                wait_ms=wait_ms,
                headless=headless,
            )
        except SafetyError:
            raise
        captured.append(DetailPrepared(url=url, detail_snapshot_id=result.detail_snapshot_id))
    return captured


def _ready_listing_ids(summary: dict, limit: int) -> list[int]:
    ready = []
    for listing in summary.get("listings", []):
        state = listing.get("collection_state", {})
        if state.get("has_detail"):
            ready.append(int(listing["listing_id"]))
        if len(ready) >= limit:
            break
    return ready


def _compact_evidence_bundle(bundle: dict, ocr_chars: int) -> dict:
    compact = dict(bundle)
    compact["ocr_evidence"] = [_compact_ocr_item(item, ocr_chars) for item in bundle.get("ocr_evidence", [])]
    return compact


def _compact_ocr_item(item: dict, ocr_chars: int) -> dict:
    ocr_text = str(item.get("ocr_text") or "")
    compact = dict(item)
    compact["ocr_text_chars"] = len(ocr_text)
    compact["ocr_text"] = _truncate(ocr_text, ocr_chars)
    return compact


def _truncate(value: str, max_chars: int) -> str:
    if max_chars < 0 or len(value) <= max_chars:
        return value
    if max_chars == 0:
        return ""
    return value[: max_chars - 1] + "..."


def prepare_run_evidence_sync(
    config: AppConfig,
    **kwargs,
) -> PrepareEvidenceResult:
    return asyncio.run(prepare_run_evidence(config, **kwargs))
