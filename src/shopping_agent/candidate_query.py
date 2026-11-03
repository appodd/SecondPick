from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    connect,
    fetch_detail_snapshots_for_run,
    fetch_latest_listing_snapshots_for_run,
    initialize,
)
from shopping_agent.extraction.listing_parser import parse_price_value
from shopping_agent.platforms.xianyu_detail_parser import parse_xianyu_detail_text


@dataclass
class CandidateQueryOptions:
    run_ids: list[int] = field(default_factory=list)
    goal: str | None = None
    target_city: str | None = None
    # filters
    min_price: int | None = None
    max_price: int | None = None
    price_ratio_max: float | None = None
    price_ratio_min: float | None = None
    condition: str | None = None
    condition_exclude: str | None = None
    has_detail: bool | None = None
    seller_sold_min: int | None = None
    seller_sold_max: int | None = None
    credit_level: str | None = None
    realname_verified_only: bool = False
    listing_ids: list[int] = field(default_factory=list)
    has_damage_keywords: bool | None = None
    locations: list[str] = field(default_factory=list)
    text_includes: list[str] = field(default_factory=list)
    text_excludes: list[str] = field(default_factory=list)
    text_match_mode: str = "all"
    text_scopes: list[str] = field(default_factory=list)
    # output
    sort_by: str = "price_asc"
    limit: int = 50
    include_market_context: bool = True


DAMAGE_KEYWORDS = (
    "碎", "坏", "磕碰", "闪屏", "背光", "修过", "维修",
    "瑕疵", "裂", "花屏", "黑屏", "断", "凹", "变形",
)
MINT_CONDITION_KEYWORDS = ("几乎全新", "99新", "98新", "97新", "96新", "95新", "全新")
CONDITION_LABEL_MAP = {
    "全新": ("全新",),
    "几乎全新": ("几乎全新", "99新", "98新", "97新", "96新", "95新"),
    "细微瑕疵": ("细微", "轻微", "小磕"),
    "明显瑕疵": ("明显磕碰", "磕碰划痕"),
}


def query_candidates(
    config: AppConfig,
    options: CandidateQueryOptions | None = None,
) -> dict:
    """Query a run's candidates with narrow filters; return evidence, not judgments.

    This is the interactive assistant's session-memory lookup. It does NOT label
    sellers as 个人/专业 or prices as 捡漏/硬伤; it returns structured evidence
    (sold_count, registered_days, price-to-median ratio, condition, damage
    keyword hits) so the model can answer the user's actual question per-turn.
    """
    options = options or CandidateQueryOptions()
    run_ids = list(dict.fromkeys(options.run_ids))
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        rows_by_listing = {}
        for run_id in run_ids:
            for row in fetch_latest_listing_snapshots_for_run(conn, run_id):
                rows_by_listing.setdefault(row["listing_id"], []).append((run_id, row))
        rows = []
        source_run_ids_by_listing = {}
        for listing_id, occurrences in rows_by_listing.items():
            latest_run_id, latest_row = max(
                occurrences,
                key=lambda occurrence: (
                    occurrence[1]["collected_at"] or "",
                    occurrence[1]["id"],
                ),
            )
            rows.append((latest_run_id, latest_row))
            source_run_ids_by_listing[listing_id] = sorted(
                {source_run_id for source_run_id, _ in occurrences}
            )
        detail_evidence_by_listing = _load_detail_evidence(conn, run_ids)

    priced = [parse_price_value(row["price_text"]) for _, row in rows]
    priced = sorted(p for p in priced if p is not None)
    median = _median(priced)

    candidates = []
    for run_id, row in rows:
        candidate = _row_to_query_candidate(
            run_id,
            row,
            source_run_ids_by_listing.get(row["listing_id"], [run_id]),
            detail_evidence_by_listing,
            median,
        )
        candidates.append(candidate)

    deduplicated_count = len(candidates)
    candidates = _apply_filters(candidates, options, median)
    eligible_count = len(candidates)
    candidates = _sort_candidates(candidates, options.sort_by)[: options.limit]
    candidates = [_compact_query_candidate(candidate) for candidate in candidates]

    result = {
        "run_ids": run_ids,
        "goal": options.goal,
        "deduplicated_count": deduplicated_count,
        "eligible_count": eligible_count,
        "returned_count": len(candidates),
        "limit": options.limit,
        "truncated": eligible_count > len(candidates),
        "filters_applied": _generic_filters_applied(options),
        "sort_by": options.sort_by,
        "candidates": candidates,
    }
    if options.include_market_context:
        result["market_context"] = _market_context(rows)
    result["query_hint"] = (
        "deduplicated_count 和 eligible_count 基于请求 run 的全量去重候选，"
        "returned_count 仅是展示数量。这些是结构化证据，不是购买结论；"
        "卖家类型和价格风险请由模型结合来源与不确定性判断。"
    )
    return result


def _row_to_query_candidate(
    run_id,
    row,
    source_run_ids,
    detail_evidence_by_listing,
    median,
):
    listing_id = row["listing_id"]
    price_value = parse_price_value(row["price_text"])
    detail_evidence = detail_evidence_by_listing.get(listing_id, {})
    detail_text = detail_evidence.get("text", "")
    persisted_attributes = detail_evidence.get("attributes", {})
    dom_attributes, dom_seller = _parse_detail_text(detail_text)
    attributes = persisted_attributes or dom_attributes
    seller_fields = _merge_seller_fields(row, dom_seller)
    price_ratio = _price_ratio_to_median(price_value, median)
    attribute_values = {
        "condition": _attribute_value(attributes, "成色"),
        "repair": _attribute_value(attributes, "拆修", "拆修和功能"),
        "memory": _attribute_value(attributes, "内存容量", "运行内存"),
        "storage": _attribute_value(attributes, "硬盘容量", "存储容量"),
        "model": _attribute_value(attributes, "型号"),
    }
    filter_fields = {
        "title": row["title"] or "",
        "search_description": row["description"] or "",
        "detail_description": detail_text,
        "attributes": " ".join(
            f"{key} {value}" for key, value in attributes.items()
        ),
    }
    return {
        "listing_id": listing_id,
        "run_id": run_id,
        "source_run_ids": source_run_ids,
        "url": row["url"],
        "title": row["title"] or "",
        "price_text": row["price_text"],
        "price_value": price_value,
        "price_ratio_to_median": price_ratio,
        "location": row["location"],
        "search_condition": row["search_condition"],
        "seller_fields": seller_fields,
        "condition": attribute_values["condition"],
        "repair": attribute_values["repair"],
        "memory": attribute_values["memory"],
        "storage": attribute_values["storage"],
        "model": attribute_values["model"],
        "filter_evidence": {
            "location_matches": [],
            "text_matches": {},
            "excluded_text_matches": {},
        },
        "_filter_fields": filter_fields,
        "has_detail": bool(detail_text),
        "damage_keyword_hits": _damage_hits(attributes.get("成色"), attributes.get("拆修"), row["description"] or ""),
        "is_mint_condition": _is_mint(attributes.get("成色")),
    }


def _compact_query_candidate(candidate: dict) -> dict:
    title = candidate["title"]
    description = candidate["_filter_fields"]["search_description"] or None
    if description == title:
        description = None
        description_status = "redundant_with_title"
    elif description is None:
        description_status = "missing"
    else:
        description_status = "distinct"
    seller_fields = candidate["seller_fields"]
    return {
        "listing_id": candidate["listing_id"],
        "source_run_ids": candidate["source_run_ids"],
        "url": candidate["url"],
        "title": title,
        "search_description": description,
        "search_description_status": description_status,
        "price_text": candidate["price_text"],
        "price_value": candidate["price_value"],
        "price_ratio_to_median": candidate["price_ratio_to_median"],
        "location": candidate["location"],
        "search_condition": candidate["search_condition"],
        "has_detail": candidate["has_detail"],
        "mechanical_facts": {
            "condition": candidate["condition"],
            "repair": candidate["repair"],
            "memory": candidate["memory"],
            "storage": candidate["storage"],
            "model": candidate["model"],
            "seller_sold_count": seller_fields["seller_sold_count"],
            "seller_credit_level": seller_fields["seller_credit_level"],
            "seller_realname_verified": seller_fields["seller_realname_verified"],
        },
        "damage_keyword_hits": candidate["damage_keyword_hits"],
        "filter_evidence": candidate["filter_evidence"],
    }


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _apply_filters(candidates: list[dict], options: CandidateQueryOptions, median) -> list[dict]:
    result = []
    for c in candidates:
        if not _matches_filters(c, options, median):
            continue
        result.append(c)
    return result


def _matches_filters(c: dict, options: CandidateQueryOptions, median) -> bool:
    price = c["price_value"]
    if options.min_price is not None and (price is None or price < options.min_price):
        return False
    if options.max_price is not None and (price is None or price > options.max_price):
        return False
    price_ratio = c.get("price_ratio_to_median")
    if options.price_ratio_max is not None:
        if price_ratio is None or price_ratio > options.price_ratio_max:
            return False
    if options.price_ratio_min is not None:
        if price_ratio is None or price_ratio < options.price_ratio_min:
            return False
    if options.condition:
        wanted = CONDITION_LABEL_MAP.get(options.condition, (options.condition,))
        if not c.get("condition") or not any(w in c["condition"] for w in wanted):
            return False
    if options.condition_exclude:
        if c.get("condition") and options.condition_exclude in c["condition"]:
            return False
    if options.has_detail is not None and c["has_detail"] != options.has_detail:
        return False
    seller = c["seller_fields"]
    sold = seller.get("seller_sold_count")
    if options.seller_sold_min is not None and (sold is None or sold < options.seller_sold_min):
        return False
    if options.seller_sold_max is not None and (sold is None or sold > options.seller_sold_max):
        return False
    if options.credit_level:
        cl = seller.get("seller_credit_level")
        if not cl or options.credit_level not in str(cl):
            return False
    if options.realname_verified_only and not seller.get("seller_realname_verified"):
        return False
    if options.listing_ids and c["listing_id"] not in options.listing_ids:
        return False
    if options.has_damage_keywords is True and not c["damage_keyword_hits"]:
        return False
    if options.has_damage_keywords is False and c["damage_keyword_hits"]:
        return False
    generic_evidence = _match_generic_filters(c, options)
    if generic_evidence is None:
        return False
    c["filter_evidence"] = generic_evidence
    return True


def _match_generic_filters(c: dict, options: CandidateQueryOptions) -> dict | None:
    location = c.get("location") or ""
    location_matches = [
        {"term": term, "value": location}
        for term in options.locations
        if term and term in location
    ]
    if options.locations and not location_matches:
        return None

    scopes = options.text_scopes or [
        "title",
        "search_description",
        "detail_description",
        "attributes",
    ]
    fields = c.get("_filter_fields") or {}
    text_matches = {
        term: [scope for scope in scopes if term and term in str(fields.get(scope) or "")]
        for term in options.text_includes
    }
    if options.text_includes:
        matched = [bool(matches) for matches in text_matches.values()]
        if options.text_match_mode == "any":
            if not any(matched):
                return None
        elif not all(matched):
            return None

    excluded_matches = {
        term: [scope for scope in scopes if term and term in str(fields.get(scope) or "")]
        for term in options.text_excludes
    }
    if any(excluded_matches.values()):
        return None

    return {
        "location_matches": location_matches,
        "text_matches": {term: matches for term, matches in text_matches.items() if matches},
        "excluded_text_matches": {},
    }


def _generic_filters_applied(options: CandidateQueryOptions) -> dict:
    return {
        "locations": list(options.locations),
        "text_includes": list(options.text_includes),
        "text_excludes": list(options.text_excludes),
        "text_match_mode": options.text_match_mode,
        "text_scopes": list(options.text_scopes),
    }


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def _sort_candidates(candidates: list[dict], sort_by: str) -> list[dict]:
    sorters = {
        "price_asc": lambda c: c["price_value"] if c["price_value"] is not None else 10**12,
        "price_desc": lambda c: -(c["price_value"] if c["price_value"] is not None else -1),
        "condition_best": lambda c: (0 if c.get("is_mint_condition") else 1, c["price_value"] or 10**12),
        "seller_most_active": lambda c: -(c["seller_fields"].get("seller_sold_count") or 0),
        "credit_best": lambda c: _credit_sort_key(c["seller_fields"]),
        "recent": lambda c: c["listing_id"],
    }
    key = sorters.get(sort_by, sorters["price_asc"])
    return sorted(candidates, key=key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_detail_evidence(conn, run_ids: list[int]) -> dict[int, dict]:
    """Load saved detail facts for mechanical filtering without returning raw text."""
    latest_by_listing: dict[int, tuple[tuple[str, int], dict]] = {}
    for run_id in run_ids:
        for drow in fetch_detail_snapshots_for_run(conn, run_id):
            listing_id = drow["listing_id"] if "listing_id" in drow.keys() else None
            if listing_id is None:
                continue
            text = _read_text_file(drow["text_path"])
            attributes = _read_attributes_json(drow["attributes_json"])
            if not text and not attributes:
                continue
            detail_key = (drow["created_at"] or "", drow["id"])
            current = latest_by_listing.get(listing_id)
            if current is None or detail_key > current[0]:
                latest_by_listing[listing_id] = (
                    detail_key,
                    {
                        "text": text,
                        "attributes": attributes,
                        "attributes_source": drow["attributes_source"],
                    },
                )
    return {
        listing_id: selected[1]
        for listing_id, selected in latest_by_listing.items()
    }


def _read_attributes_json(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in decoded.items()
        if key and item is not None
    }


def _attribute_value(attributes: dict, *keys: str) -> str | None:
    for key in keys:
        value = attributes.get(key)
        if value:
            return str(value)
    return None


def _read_text_file(text_path: str | None) -> str:
    if not text_path:
        return ""
    path = Path(text_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_detail_text(detail_text: str) -> tuple[dict, dict]:
    if not detail_text:
        return {}, {}
    try:
        parsed = parse_xianyu_detail_text(detail_text)
    except Exception:
        return {}, {}
    return parsed.attributes, parse_dom_seller_stats(parsed.seller_stats)


def parse_dom_seller_stats(seller_stats: list[str]) -> dict:
    result: dict = {}
    for line in seller_stats or []:
        m = re.search(r"来闲鱼(\d+)年", line)
        if m:
            result["seller_registered_days"] = int(m.group(1)) * 365
            continue
        m = re.search(r"来闲鱼(\d+)天", line)
        if m:
            result["seller_registered_days"] = int(m.group(1))
            continue
        m = re.search(r"卖出(\d+)件", line)
        if m:
            result["seller_sold_count"] = int(m.group(1))
            continue
        m = re.search(r"好评率(\d+(?:\.\d+)?)%", line)
        if m:
            result["seller_good_rate"] = m.group(1) + "%"
    return result


def _merge_seller_fields(row, dom_seller: dict) -> dict:
    db_fields = {
        "seller_credit_level": row["seller_credit_level"],
        "seller_registered_days": row["seller_registered_days"],
        "seller_sold_count": row["seller_sold_count"],
        "seller_good_rate": row["seller_good_rate"],
        "seller_realname_verified": bool(row["seller_realname_verified"])
        if row["seller_realname_verified"] is not None
        else None,
        "seller_reply_rate_24h": row["seller_reply_rate_24h"],
    }
    merged = {}
    has_db = False
    for key, value in db_fields.items():
        if value is not None:
            merged[key] = value
            has_db = True
        elif key in dom_seller:
            merged[key] = dom_seller[key]
        else:
            merged[key] = None
    merged["source"] = "db" if has_db else ("dom" if dom_seller else "none")
    return merged


def _damage_hits(condition: str | None, repair: str | None, description: str) -> list[str]:
    parts = [description]
    if condition:
        parts.append(condition)
    if repair and not any(neg in repair for neg in ("无", "未", "没")):
        parts.append(repair)
    text_pool = " ".join(parts)
    return [kw for kw in DAMAGE_KEYWORDS if kw in text_pool]


def _is_mint(condition: str | None) -> bool:
    if not condition:
        return False
    return any(kw in condition for kw in MINT_CONDITION_KEYWORDS)


def _price_ratio_to_median(price_value, median):
    if price_value is None or not median or median == 0:
        return None
    return round(price_value / median, 3)


def _median(values: list) -> float | None:
    priced = sorted(v for v in values if v is not None)
    if not priced:
        return None
    n = len(priced)
    if n == 1:
        return float(priced[0])
    mid = n // 2
    if n % 2:
        return float(priced[mid])
    return (priced[mid - 1] + priced[mid]) / 2


def _credit_sort_key(seller: dict) -> tuple:
    rank_map = {"信用极好": 0, "信用优秀": 1, "信用良好": 2, "信用较差": 3}
    cl = seller.get("seller_credit_level")
    if cl and cl in rank_map:
        return (rank_map[cl], 0)
    return (4, -(seller.get("seller_sold_count") or 0))


def _market_context(rows) -> dict:
    priced = []
    for _, row in rows:
        p = parse_price_value(row["price_text"])
        if p is not None:
            priced.append(p)
    priced.sort()
    if not priced:
        return {"priced_count": 0, "median": None, "min": None, "max": None}
    return {
        "priced_count": len(priced),
        "min": priced[0],
        "max": priced[-1],
        "median": _median(priced),
        "p25": _quantile(priced, 0.25),
        "p75": _quantile(priced, 0.75),
    }


def _quantile(priced: list, fraction: float):
    n = len(priced)
    if n == 1:
        return priced[0]
    idx = min(int(round(fraction * (n - 1))), n - 1)
    return priced[idx]
