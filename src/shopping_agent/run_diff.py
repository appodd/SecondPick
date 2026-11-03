from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from shopping_agent.config import AppConfig
from shopping_agent.db import connect, fetch_latest_listing_snapshots_for_run, initialize
from shopping_agent.extraction.listing_parser import parse_price_value


def build_run_diff(config: AppConfig, before_run_id: int, after_run_id: int, goal: str | None = None) -> dict:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        before_rows = fetch_latest_listing_snapshots_for_run(conn, before_run_id)
        after_rows = fetch_latest_listing_snapshots_for_run(conn, after_run_id)

    before = _rows_by_identity(before_rows, before_run_id)
    after = _rows_by_identity(after_rows, after_run_id)
    before_keys = set(before)
    after_keys = set(after)
    common_keys = sorted(before_keys & after_keys)

    price_changes = []
    text_changes = []
    for key in common_keys:
        old = before[key]
        new = after[key]
        price_change = _price_change(old, new)
        if price_change is not None:
            price_changes.append(price_change)
        changed_fields = _changed_fields(old, new)
        if changed_fields:
            text_changes.append(
                {
                    "identity_key": key,
                    "before": old,
                    "after": new,
                    "changed_fields": changed_fields,
                }
            )

    return {
        "goal": goal,
        "before_run_id": before_run_id,
        "after_run_id": after_run_id,
        "decision_owner": "llm",
        "is_final_recommendation": False,
        "summary": {
            "before_count": len(before),
            "after_count": len(after),
            "common_count": len(common_keys),
            "new_count": len(after_keys - before_keys),
            "missing_count": len(before_keys - after_keys),
            "price_change_count": len(price_changes),
            "text_change_count": len(text_changes),
            "price_drop_count": sum(1 for item in price_changes if item["direction"] == "down"),
            "price_increase_count": sum(1 for item in price_changes if item["direction"] == "up"),
        },
        "new_listings": [after[key] for key in sorted(after_keys - before_keys)],
        "missing_listings": [before[key] for key in sorted(before_keys - after_keys)],
        "price_changes": price_changes,
        "text_changes": text_changes,
        "notes": [
            "This compares local search snapshots only. Missing from the later run does not prove the listing expired.",
            "Price and text changes are evidence for the LLM; they are not purchase recommendations.",
            "For Xianyu, identity keys prefer item id over full URL so category/tracking URL differences do not create false new listings.",
        ],
    }


def _rows_by_identity(rows, run_id: int) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        item = _row_to_item(row, run_id)
        existing = result.get(item["identity_key"])
        if existing is None or _item_quality(item) > _item_quality(existing):
            result[item["identity_key"]] = item
    return result


def _row_to_item(row, run_id: int) -> dict:
    price_text = row["price_text"]
    return {
        "identity_key": _listing_identity_key(row["platform"], row["url"]),
        "run_id": run_id,
        "listing_id": row["listing_id"],
        "platform": row["platform"],
        "url": row["url"],
        "title": row["title"],
        "price_text": price_text,
        "price_value": parse_price_value(price_text),
        "location": row["location"],
        "seller_name": row["seller_name"],
        "description_excerpt": _truncate(row["description"] or "", 180),
        "collected_at": row["collected_at"],
    }


def _price_change(before: dict, after: dict) -> dict | None:
    before_price = before.get("price_value")
    after_price = after.get("price_value")
    if before_price is None or after_price is None or before_price == after_price:
        return None
    delta = after_price - before_price
    return {
        "identity_key": after["identity_key"],
        "direction": "down" if delta < 0 else "up",
        "delta": delta,
        "delta_abs": abs(delta),
        "before_price": before_price,
        "after_price": after_price,
        "before": before,
        "after": after,
    }


def _changed_fields(before: dict, after: dict) -> list[str]:
    fields = []
    for field in ("title", "price_text", "location", "seller_name"):
        if (before.get(field) or "") != (after.get(field) or ""):
            fields.append(field)
    return fields


def _item_quality(item: dict) -> int:
    score = 0
    for field in ("price_text", "location", "title", "seller_name"):
        if item.get(field):
            score += 1
    return score


def _listing_identity_key(platform: str, url: str) -> str:
    parsed = urlparse(url)
    if platform == "xianyu" or "goofish.com" in parsed.netloc:
        query_id = parse_qs(parsed.query).get("id")
        if query_id and query_id[0]:
            return f"xianyu:item:{query_id[0]}"
        match = re.search(r"/item/(\d+)", parsed.path)
        if match:
            return f"xianyu:item:{match.group(1)}"
    return f"{platform}:url:{url}"
def _truncate(value: str, max_chars: int) -> str:
    value = " ".join(value.split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "..."
