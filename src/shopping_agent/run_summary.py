from __future__ import annotations

from dataclasses import dataclass

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    connect,
    fetch_latest_listing_snapshots_for_run,
    fetch_page_snapshots_for_run,
    initialize,
)


@dataclass
class RunSummaryOptions:
    listing_limit: int = 20
    description_chars: int = 220


def build_run_summary(config: AppConfig, run_id: int, options: RunSummaryOptions | None = None) -> dict:
    options = options or RunSummaryOptions()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        pages = fetch_page_snapshots_for_run(conn, run_id)
        all_listings = fetch_latest_listing_snapshots_for_run(conn, run_id)
        returned_listings = all_listings[: options.listing_limit]

    return {
        "run_id": run_id,
        "pages": [_page_to_dict(page) for page in pages],
        "result_quality": _summarize_quality(pages, all_listings),
        "returned_listing_count": len(returned_listings),
        "listing_limit": options.listing_limit,
        "truncated": len(returned_listings) < len(all_listings),
        "listings": [
            _listing_to_dict(row, options.description_chars)
            for row in returned_listings
        ],
    }


def _page_to_dict(page) -> dict:
    return {
        "id": page["id"],
        "platform": page["platform"],
        "query": page["query_text"],
        "url": page["url"],
        "title": page["title"],
        "link_count": page["link_count"],
        "access_blocked": bool(page["access_blocked"]),
        "text_path": page["text_path"],
        "screenshot_path": page["screenshot_path"],
        "created_at": page["created_at"],
    }


def _listing_to_dict(row, description_chars: int) -> dict:
    description = row["description"] or ""
    return {
        "listing_id": row["listing_id"],
        "first_snapshot_id": row["first_snapshot_id"],
        "platform": row["platform"],
        "url": row["url"],
        "title": row["title"],
        "price_text": row["price_text"],
        "location": row["location"],
        "seller_name": row["seller_name"],
        "source_type": row["source_type"],
        "source_label": row["source_label"],
        "description_excerpt": _truncate(description, description_chars),
        "collection_state": {
            "detail_snapshot_count": row["detail_snapshot_count"],
            "product_image_count": row["product_image_count"],
            "downloaded_product_image_count": row["downloaded_product_image_count"],
            "ocr_result_count": row["ocr_result_count"],
            "has_detail": row["detail_snapshot_count"] > 0,
            "has_downloaded_images": row["downloaded_product_image_count"] > 0,
            "has_ocr": row["ocr_result_count"] > 0,
        },
        "collected_at": row["collected_at"],
    }


def _summarize_quality(pages, listings) -> dict:
    blocked_pages = [page for page in pages if page["access_blocked"]]
    priced = [row for row in listings if row["price_text"]]
    located = [row for row in listings if row["location"]]
    listing_count = len(listings)
    return {
        "page_count": len(pages),
        "access_blocked": bool(blocked_pages),
        "listing_count": listing_count,
        "priced_listing_count": len(priced),
        "located_listing_count": len(located),
        "priced_listing_ratio": _ratio(len(priced), listing_count),
        "located_listing_ratio": _ratio(len(located), listing_count),
        "has_real_listing_data": bool(priced or located),
        "candidate_for_detail_capture": bool(listings) and not blocked_pages,
    }


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "..."


def _ratio(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total, 3)
