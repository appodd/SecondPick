from __future__ import annotations

from shopping_agent.region_preference import region_preference

import re
from dataclasses import dataclass

from shopping_agent.config import AppConfig
from shopping_agent.db import connect, fetch_latest_listing_snapshots_for_run, initialize
from shopping_agent.extraction.listing_parser import parse_price_value
from shopping_agent.asking_prices import apply_quote
from shopping_agent.candidate_context import _load_scoped_candidates


@dataclass
class CandidatePoolOptions:
    goal: str | None = None
    limit: int = 600
    shortlist_limit: int = 12
    target_city: str | None = None


def build_candidate_pool(
    config: AppConfig,
    run_ids: list[int],
    options: CandidatePoolOptions | None = None,
) -> dict:
    options = options or CandidatePoolOptions()
    initialize(config.database_path)
    rows = []
    with connect(config.database_path) as conn:
        for run_id in run_ids:
            for row in fetch_latest_listing_snapshots_for_run(conn, run_id):
                rows.append((run_id, row))
        saved={c['listing_id']:c for c in _load_scoped_candidates(conn,run_ids)[0]}

    candidates = [_row_to_candidate(run_id, row, options) for run_id, row in rows]
    candidates = _dedupe_candidates(candidates)
    for candidate in candidates:
        context=saved.get(candidate['listing_id'],{})
        apply_quote(candidate,context.get('current_quote'))
        for key in ('market_attributes','market_provenance','market_page_fields'):
            if key in context:candidate[key]=context[key]
        supplement=context.get('monitor_evidence') or {}
        attributes=((supplement.get('fields') or {}).get('monitor_detail') or {}).get('商品属性')
        if attributes:
            candidate['monitor_evidence']=dict(fields={'monitor_detail':{'商品属性':attributes}},
                field_sources={'monitor_detail':{'商品属性':((supplement.get('field_sources') or {}).get('monitor_detail') or {}).get('商品属性',{})}},
                independently_verified=False)
    candidates = sorted(
        candidates,
        key=lambda item: (
            -item["tool_priority_score"],
            item["price_value"] if item["price_value"] is not None else 10**12,
            item["first_seen_run_id"],
            item["first_snapshot_id"],
        ),
    )[: options.limit]
    near_duplicate_groups = _build_near_duplicate_groups(candidates)
    _enrich_price_context(candidates)
    price_distribution = _price_distribution(candidates)
    return {
        "goal": options.goal,
        "region_preference": region_preference(options.goal, explicit_city=options.target_city),
        "run_ids": run_ids,
        "candidate_count": len(candidates),
        "notes": [
            "This candidate pool is a tool-layer summary, not a final purchase recommendation.",
            "The LLM should use these signals to choose search expansion, detail capture, evidence building, and final report rows.",
            "Scores favor likely relevance, explicitly requested city preference only, useful evidence state, and non-service listings; they are not price/value judgments.",
            "near_duplicate_groups are possible same-source or same-spec price anchors; verify details before treating them as the same machine.",
            "price_distribution and each candidate price_percentile_in_pool let the model judge whether a price is anomalous relative to this pool; prefer them over the fixed suspicious_low_price_for_target hint, which is a conservative floor, not a model-specific verdict.",
        ],
        "all_candidates": candidates,
        "shortlist_for_next_evidence": _shortlist_candidates(candidates, options.shortlist_limit),
        "near_duplicate_groups": near_duplicate_groups,
        "price_distribution": price_distribution,
        "suggested_next_actions": _suggest_next_actions(candidates, options, near_duplicate_groups),
    }


def _enrich_price_context(candidates: list[dict]) -> None:
    """Attach each candidate price percentile within the whole pool.

    Additive model-facing context: lets the LLM judge whether a price is an
    outlier relative to the actual collected pool instead of relying on the
    fixed suspicious_low_price_for_target floor. Mutates candidates in place.
    """
    priced = [c["price_value"] for c in candidates if c.get("price_value") is not None]
    total = len(priced)
    for candidate in candidates:
        price_value = candidate.get("price_value")
        if price_value is None or total == 0:
            candidate["price_percentile_in_pool"] = None
            continue
        at_or_below = sum(1 for price in priced if price <= price_value)
        candidate["price_percentile_in_pool"] = round(at_or_below / total, 3)


def _price_distribution(candidates: list[dict]) -> dict:
    priced = sorted(c["price_value"] for c in candidates if c.get("price_value") is not None)
    count = len(priced)
    if count == 0:
        return {"priced_count": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None}

    def _quantile(fraction: float) -> int | float:
        if count == 1:
            return priced[0]
        index = min(int(round(fraction * (count - 1))), count - 1)
        return priced[index]

    return {
        "priced_count": count,
        "min": priced[0],
        "p25": _quantile(0.25),
        "median": _quantile(0.5),
        "p75": _quantile(0.75),
        "max": priced[-1],
    }


def _row_to_candidate(run_id: int, row, options: CandidatePoolOptions) -> dict:
    text = " ".join(
        str(part or "")
        for part in (row["title"], row["description"], row["location"], row["seller_name"])
    )
    price_value = parse_price_value(row["price_text"])
    signals = _signals(text=text, row=row, options=options)
    return {
        "listing_id": row["listing_id"],
        "first_seen_run_id": run_id,
        "first_snapshot_id": row["first_snapshot_id"],
        "platform": row["platform"],
        "url": row["url"],
        "title": row["title"],
        "price_text": row["price_text"],
        "price_value": price_value,
        "location": row["location"],
        "seller_name": row["seller_name"],
        "seller_credit_level": row["seller_credit_level"],
        "seller_registered_days": row["seller_registered_days"],
        "seller_sold_count": row["seller_sold_count"],
        "seller_good_rate": row["seller_good_rate"],
        "seller_realname_verified": bool(row["seller_realname_verified"]) if row["seller_realname_verified"] is not None else None,
        "seller_reply_rate_24h": row["seller_reply_rate_24h"],
        "source_type": row["source_type"],
        "source_label": row["source_label"],
        "description_excerpt": _truncate(row["description"] or "", 260),
        "signals": signals,
        "collection_state": {
            "detail_snapshot_count": row["detail_snapshot_count"],
            "product_image_count": row["product_image_count"],
            "downloaded_product_image_count": row["downloaded_product_image_count"],
            "ocr_result_count": row["ocr_result_count"],
            "has_detail": row["detail_snapshot_count"] > 0,
            "has_downloaded_images": row["downloaded_product_image_count"] > 0,
            "has_ocr": row["ocr_result_count"] > 0,
        },
        "tool_priority_score": _tool_priority_score(signals, row),
        "near_duplicate_group_ids": [],
        "collected_at": row["collected_at"],
    }


def _signals(text: str, row, options: CandidatePoolOptions) -> dict:
    lowered = text.lower()
    target_city = region_preference(options.goal, explicit_city=options.target_city)['city']
    price_value = parse_price_value(row["price_text"])
    family = _target_family(options.goal, text)
    likely_non_target_size = _likely_non_target_size(text, family)
    signals = {
        "target_family": family,
        "target_city_hint": bool(target_city and row["location"] and target_city in str(row["location"])),
        "likely_service_listing": _likely_service_listing(text),
        "likely_accessory_or_parts": _likely_accessory_or_parts(text),
        "likely_non_target_size": likely_non_target_size,
    }
    if family == "macbook":
        target_subtype = _macbook_subtype(options.goal)
        target_screen_sizes = _target_macbook_screen_sizes(options.goal)
        detected_screen_sizes = _macbook_screen_sizes(text)
        non_target_screen_sizes = detected_screen_sizes - target_screen_sizes
        has_target_size = bool(target_screen_sizes & detected_screen_sizes)
        likely_non_target_size = bool(target_screen_sizes and detected_screen_sizes and not has_target_size)
        signals.update(
            {
                "target_subtype": target_subtype,
                "target_screen_sizes": sorted(target_screen_sizes),
                "detected_screen_sizes": sorted(detected_screen_sizes),
                "mentions_target_screen_size": has_target_size,
                "mentions_non_target_screen_size": bool(target_screen_sizes and non_target_screen_sizes),
                "likely_non_target_size": likely_non_target_size,
                "mentions_macbook": "macbook" in lowered or "苹果笔记本" in text or "苹果电脑" in text,
                "mentions_macbook_pro": "macbook pro" in lowered or "macbookpro" in lowered,
                "mentions_macbook_air": "macbook air" in lowered or "macbookair" in lowered,
                "mentions_13": _mentions_screen_size(text, ("13", "13.3", "13.6")),
                "mentions_14": _mentions_screen_size(text, ("14", "14.2")),
                "mentions_16": _mentions_screen_size(text, ("16", "16.2")),
                "mentions_m_series": bool(re.search(r"\bm[1-5]\b", lowered)) or any(f"M{i}" in text for i in range(1, 6)),
                "mentions_32g": bool(re.search(r"32\s*(g|gb|G|GB)", text)),
                "mentions_512": "512" in text,
                "mentions_1t": "1t" in lowered or "1TB" in text or "1 T" in text,
                "suspicious_low_price_for_target": price_value is not None and price_value < 1500,
            }
        )
        return signals
    signals.update(
        {
            "mentions_imac": "imac" in lowered or "一体机" in text,
            "mentions_27": bool(re.search(r"27\s*(寸|英寸|inch|in\b)?", lowered)),
            "mentions_21_5": bool(re.search(r"21\.?5\s*(寸|英寸|inch|in\b)?", lowered)),
            "target_year_hint": "2019" in text,
            "adjacent_year_hint": "2020" in text,
            "mentions_5k": "5k" in lowered,
            "mentions_i9": "i9" in lowered,
            "mentions_580x": "580x" in lowered,
            "mentions_fusion": "fusion" in lowered or "融合硬盘" in text,
            "mentions_ssd": "ssd" in lowered or "固态" in text,
            "suspicious_low_price_for_target": family=='imac' and price_value is not None and price_value < 800,
        }
    )
    return signals


def _target_family(goal: str | None, text: str) -> str:
    source = f"{goal or ''} {text}".lower()
    if "macbook" in source or "苹果笔记本" in source:
        return "macbook"
    if "imac" in source or "一体机" in source:
        return "imac"
    return "generic"


def _macbook_subtype(goal: str | None) -> str | None:
    source = (goal or "").lower()
    if "macbook pro" in source or "macbookpro" in source:
        return "pro"
    if "macbook air" in source or "macbookair" in source:
        return "air"
    return None


def _mentions_screen_size(text: str, sizes: tuple[str, ...]) -> bool:
    lowered = text.lower()
    suffix = r"(?:寸|英寸|吋|inch|in\b)"
    for size in sizes:
        escaped_size = re.escape(size)
        if re.search(rf"(?<!\d){escaped_size}\s*{suffix}", lowered):
            return True
        if re.search(rf"(?<!\d){escaped_size}\s*[-~至到]\s*\d+(?:\.\d+)?\s*{suffix}", lowered):
            return True
    return False


def _target_macbook_screen_sizes(goal: str | None) -> set[str]:
    if not goal:
        return set()
    source = goal.lower()
    sizes = _macbook_screen_sizes(goal)
    if "macbook" not in source and "苹果笔记本" not in goal and "苹果电脑" not in goal:
        return sizes
    for size in ("13", "14", "16"):
        if re.search(rf"(?<!\d){size}(?!\d)(?!\s*(?:g|gb|核|core))", source):
            sizes.add(size)
    return sizes


def _macbook_screen_sizes(text: str) -> set[str]:
    sizes = set()
    if _mentions_screen_size(text, ("13", "13.3", "13.6")):
        sizes.add("13")
    if _mentions_screen_size(text, ("14", "14.2")):
        sizes.add("14")
    if _mentions_screen_size(text, ("16", "16.2")):
        sizes.add("16")
    return sizes


def _tool_priority_score(signals: dict, row) -> int:
    score = 0
    family = signals.get("target_family")
    if family == "macbook":
        target_subtype = signals.get("target_subtype")
        weighted_keys = [
            ("mentions_macbook", 25),
            ("mentions_macbook_pro", 16),
            ("mentions_m_series", 12),
            ("mentions_32g", 14),
            ("mentions_512", 5),
            ("mentions_1t", 7),
            ("target_city_hint", 15),
        ]
        if signals.get("target_screen_sizes"):
            weighted_keys.append(("mentions_target_screen_size", 18))
        else:
            weighted_keys.extend((("mentions_14", 14), ("mentions_16", 10)))
    else:
        weighted_keys = (
            ("mentions_imac", 25),
            ("mentions_27", 20),
            ("target_year_hint", 20),
            ("adjacent_year_hint", 12),
            ("mentions_5k", 8),
            ("target_city_hint", 15),
            ("mentions_ssd", 4),
        )
    for key, weight in weighted_keys:
        if signals.get(key):
            score += weight
    if family == "macbook":
        if target_subtype == "pro" and signals.get("mentions_macbook_air"):
            score -= 30
        elif target_subtype == "air" and signals.get("mentions_macbook_air"):
            score += 16
        elif target_subtype is None and signals.get("mentions_macbook_air"):
            score += 5
    if row["detail_snapshot_count"] > 0:
        score += 10
    if row["downloaded_product_image_count"] > 0:
        score += 8
    if row["ocr_result_count"] > 0:
        score += 10
    if signals.get("likely_service_listing"):
        score -= 25
    if signals.get("likely_accessory_or_parts"):
        score -= 80
    if signals.get("likely_non_target_size"):
        score -= 70
    if signals.get("suspicious_low_price_for_target"):
        score -= 80
    return score


def _suggest_next_actions(candidates: list[dict], options: CandidatePoolOptions, near_duplicate_groups: list[dict]) -> list[str]:
    actions = []
    total = len(candidates)
    family = _target_family(options.goal, "")
    if near_duplicate_groups:
        group_count = len(near_duplicate_groups)
        listing_ids = ", ".join(
            str(listing_id)
            for group in near_duplicate_groups[:3]
            for listing_id in group["listing_ids"][:3]
        )
        actions.append(
            f"检测到 {group_count} 组近似候选：建议大模型把这些 listing 当作价格锚点或同源库存线索检查，先核对详情/OCR/卖家信息，不要直接当成独立优质候选。代表 listing：{listing_ids}。"
        )
    if total < 30:
        if family == "macbook":
            actions.append("候选数量偏少：建议由大模型继续扩展 MacBook 搜索词，例如 macbook pro 32g、A2442 32G、M1pro 32 512、21款 14寸 32G。")
        elif family == "imac":
            actions.append("候选数量偏少：建议由大模型继续扩展搜索词，例如 iMac 27 5K 上海、2019 iMac 27、2020 iMac 27 上海、iMac 27 580X。")
        else:
            actions.append("候选数量偏少：建议由大模型根据目标商品继续扩展搜索词，并保留原始搜索 run 用于审计。")
    if family == "imac" and not any(item["signals"].get("adjacent_year_hint") for item in candidates):
        actions.append("当前候选里缺少相邻年份样本：如果用户接受，建议补搜 2020 iMac 27 作为价格/配置参照。")
    if family == "macbook" and not any(item["signals"].get("mentions_14") or item["signals"].get("mentions_16") for item in candidates):
        actions.append("当前候选里缺少 14/16 寸高性能 MacBook 样本：如果用户目标是 Pro 机型，建议补搜 A2442、M1 Pro 14、MacBook Pro 14 32G。")
    shortlist = _shortlist_candidates(candidates, options.shortlist_limit)
    detail_missing = [item for item in shortlist if not item["collection_state"]["has_detail"]]
    if detail_missing:
        ids = ", ".join(str(item["listing_id"]) for item in detail_missing[:5])
        actions.append(f"优先补抓这些候选的详情和图片证据：{ids}。")
    if not actions:
        actions.append("候选池已具备下一轮评估基础：建议对前排候选 build-evidence，并由大模型查官方规格和市场价后生成 HTML 横向对比。")
    return actions


def _likely_accessory_or_parts(text: str) -> bool:
    from shopping_agent.market_comparability import sale_type
    return sale_type(text)=='accessory'


def _likely_service_listing(text: str) -> bool:
    service_negations = ("非维修升级服务", "不是维修升级服务", "不是升级服务", "非升级服务")
    normalized_text = text
    for negation in service_negations:
        normalized_text = normalized_text.replace(negation, "")
    for term in ('无维修','未维修','没维修','没有维修','无拆无修'):
        normalized_text=normalized_text.replace(term,'')
    service_terms = ("回收服务", "维修服务", "维修报价", "出租", "租赁", "上门维修", "拆机升级服务")
    if any(term in normalized_text for term in service_terms):
        return True
    if "升级" in normalized_text and any(
        term in normalized_text for term in ("内存", "固态", "硬盘", "CPU", "显卡", "上门", "维修")
    ):
        return True
    if "安装双系统" in normalized_text and any(
        term in normalized_text for term in ("服务", "上门", "维修", "升级", "店铺", "门店")
    ):
        return True
    return "新到货" in normalized_text and any(term in normalized_text for term in ("台", "批", "门店", "实体"))


def _likely_non_target_size(text: str, family: str) -> bool:
    if family != "imac":
        return False
    if re.search(r"21\.?5\s*(寸|英寸|inch|in\b)?", text.lower()):
        return True
    return "21寸" in text or "21 英寸" in text


def _shortlist_candidates(candidates: list[dict], limit: int) -> list[dict]:
    clean = [
        candidate
        for candidate in candidates
        if not candidate["signals"].get("likely_accessory_or_parts")
        and not candidate["signals"].get("likely_non_target_size")
        and not candidate["signals"].get("suspicious_low_price_for_target")
        and not candidate["signals"].get("likely_service_listing")
    ]
    if len(clean) >= limit:
        return clean[:limit]
    fallback = [
        candidate
        for candidate in candidates
        if candidate not in clean
        and not candidate["signals"].get("likely_accessory_or_parts")
        and not candidate["signals"].get("likely_non_target_size")
        and not candidate["signals"].get("suspicious_low_price_for_target")
    ]
    return (clean + fallback)[:limit]


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    best_by_url: dict[str, dict] = {}
    for candidate in candidates:
        url = candidate["url"]
        existing = best_by_url.get(url)
        if existing is None or (candidate.get('collected_at') or '',candidate.get('first_snapshot_id',0)) > (existing.get('collected_at') or '',existing.get('first_snapshot_id',0)):
            best_by_url[url] = candidate
    return list(best_by_url.values())


def _build_near_duplicate_groups(candidates: list[dict], limit: int = 12) -> list[dict]:
    groupable = [candidate for candidate in candidates if _is_groupable_for_near_duplicate(candidate)]
    if len(groupable) < 2:
        return []

    parent = {candidate["listing_id"]: candidate["listing_id"] for candidate in groupable}
    matches: dict[tuple[int, int], dict] = {}

    for index, left in enumerate(groupable):
        for right in groupable[index + 1 :]:
            match = _near_duplicate_match(left, right)
            if match is None:
                continue
            left_id = left["listing_id"]
            right_id = right["listing_id"]
            _union(parent, left_id, right_id)
            matches[tuple(sorted((left_id, right_id)))] = match

    grouped: dict[int, list[dict]] = {}
    for candidate in groupable:
        root = _find(parent, candidate["listing_id"])
        grouped.setdefault(root, []).append(candidate)

    groups = []
    for members in grouped.values():
        if len(members) < 2:
            continue
        member_ids = [member["listing_id"] for member in members]
        group_matches = [
            match
            for pair, match in matches.items()
            if pair[0] in member_ids and pair[1] in member_ids
        ]
        groups.append(_near_duplicate_group_summary(members, group_matches))

    groups.sort(
        key=lambda group: (
            -len(group["listing_ids"]),
            -_confidence_rank(group["confidence"]),
            group["price_summary"]["min"] if group["price_summary"]["min"] is not None else 10**12,
            group["listing_ids"][0],
        )
    )
    groups = groups[:limit]
    for index, group in enumerate(groups, start=1):
        group_id = f"ndg-{index}"
        group["group_id"] = group_id
        for candidate in candidates:
            if candidate["listing_id"] in group["listing_ids"]:
                candidate.setdefault("near_duplicate_group_ids", []).append(group_id)
    return groups


def _is_groupable_for_near_duplicate(candidate: dict) -> bool:
    signals = candidate.get("signals") or {}
    noisy_keys = (
        "likely_accessory_or_parts",
        "likely_service_listing",
        "likely_non_target_size",
        "suspicious_low_price_for_target",
    )
    return not any(signals.get(key) for key in noisy_keys)


def _near_duplicate_match(left: dict, right: dict) -> dict | None:
    left_tokens = _candidate_spec_tokens(left)
    right_tokens = _candidate_spec_tokens(right)
    shared_tokens = sorted(left_tokens & right_tokens)
    meaningful_shared_tokens = [token for token in shared_tokens if not token.startswith("family:")]
    if len(meaningful_shared_tokens) < 3 or _has_spec_conflict(left_tokens, right_tokens):
        return None

    same_seller = bool(_normalized_seller(left) and _normalized_seller(left) == _normalized_seller(right))
    same_location = bool(_normalized_location(left) and _normalized_location(left) == _normalized_location(right))
    title_overlap = _token_overlap(_title_tokens(left), _title_tokens(right))
    price_gap_ratio = _price_gap_ratio(left.get("price_value"), right.get("price_value"))

    reasons = []
    if same_seller:
        reasons.append("same_seller")
    if same_location:
        reasons.append("same_location")
    if title_overlap >= 0.45:
        reasons.append("similar_title")
    if price_gap_ratio is not None and price_gap_ratio <= 0.18:
        reasons.append("similar_price")

    confidence = None
    if same_seller and len(meaningful_shared_tokens) >= 4:
        confidence = "high"
    elif same_seller and len(meaningful_shared_tokens) >= 3:
        confidence = "medium"
    elif same_location and len(meaningful_shared_tokens) >= 4 and title_overlap >= 0.35:
        confidence = "medium"
    elif len(meaningful_shared_tokens) >= 5 and title_overlap >= 0.5:
        confidence = "low"

    if confidence is None:
        return None

    return {
        "confidence": confidence,
        "reasons": reasons,
        "shared_tokens": shared_tokens,
        "title_overlap": round(title_overlap, 3),
        "price_gap_ratio": price_gap_ratio,
    }


def _near_duplicate_group_summary(members: list[dict], matches: list[dict]) -> dict:
    listing_ids = [member["listing_id"] for member in members]
    prices = sorted(
        member["price_value"]
        for member in members
        if member.get("price_value") is not None
    )
    shared_tokens = _shared_group_tokens(members)
    reasons = _dedupe_strings(
        reason
        for match in matches
        for reason in match.get("reasons", [])
    )
    confidence = _group_confidence(matches)
    return {
        "group_id": "",
        "confidence": confidence,
        "listing_ids": listing_ids,
        "reason_codes": reasons,
        "shared_spec_tokens": shared_tokens,
        "price_summary": {
            "count": len(prices),
            "min": prices[0] if prices else None,
            "max": prices[-1] if prices else None,
            "spread": prices[-1] - prices[0] if len(prices) >= 2 else 0,
            "values": prices,
        },
        "members": [
            {
                "listing_id": member["listing_id"],
                "title": member["title"],
                "price_text": member["price_text"],
                "price_value": member["price_value"],
                "location": member["location"],
                "seller_name": member["seller_name"],
                "source_type": member["source_type"],
                "source_label": member["source_label"],
                "url": member["url"],
            }
            for member in members
        ],
        "model_note": (
            "Possible near-duplicate or same-spec anchor. The model should inspect detail pages, OCR, seller profile, "
            "and photos before deciding whether these are the same machine, same seller inventory, or only comparable configurations."
        ),
    }


def candidate_spec_tokens(candidate: dict) -> set[str]:
    signals = candidate.get("signals") or {}
    text = " ".join(
        str(part or "")
        for part in (
            candidate.get("title"),
            candidate.get("description_excerpt"),
            candidate.get("location"),
            candidate.get("seller_name"),
        )
    )
    lowered = text.lower()
    tokens = {f"family:{signals.get('target_family') or 'generic'}"}

    for size in signals.get("detected_screen_sizes") or []:
        tokens.add(f"screen:{size}")
    for size in ("13", "14", "16", "27", "21.5"):
        if _mentions_screen_size(text, (size,)):
            tokens.add(f"screen:{size}")

    for year in re.findall(r"\b20(?:1[5-9]|2[0-6])\b", text):
        tokens.add(f"year:{year}")

    for match in re.finditer(r"\bm\s*([1-5])\s*(pro|max|ultra)?\b", lowered):
        tokens.add(f"chip:m{match.group(1)}")
        if match.group(2):
            tokens.add(f"chip-class:{match.group(2)}")
    for match in re.finditer(r"\bm([1-5])(pro|max|ultra)\b", lowered):
        tokens.add(f"chip:m{match.group(1)}")
        tokens.add(f"chip-class:{match.group(2)}")
    for chip in re.findall(r"\bi[3579]\b", lowered):
        tokens.add(f"cpu:{chip}")

    for memory in re.findall(r"(?<!\d)(8|16|24|32|64|128)\s*(?:g|gb|G|GB|内存)", text):
        tokens.add(f"memory:{memory}g")
    for storage in re.findall(r"(?<!\d)(128|256|512)\s*(?:g|gb|G|GB|固态|硬盘|存储)", text):
        tokens.add(f"storage:{storage}g")
    for storage in re.findall(r"(?<!\d)(1|2|4|8)\s*(?:t|tb|T|TB)", text):
        tokens.add(f"storage:{storage}t")

    for gpu in ("580x", "575x", "570x", "5300", "5500", "5700", "vega"):
        if gpu in lowered:
            tokens.add(f"gpu:{gpu}")
    if "ssd" in lowered or "固态" in text:
        tokens.add("storage-type:ssd")
    if "fusion" in lowered or "融合硬盘" in text:
        tokens.add("storage-type:fusion")
    return tokens


def _candidate_spec_tokens(candidate: dict) -> set[str]:
    return candidate_spec_tokens(candidate)


def _has_spec_conflict(left_tokens: set[str], right_tokens: set[str]) -> bool:
    prefixes = (
        "screen:",
        "chip:",
        "chip-class:",
        "cpu:",
        "gpu:",
        "memory:",
        "storage:",
        "storage-type:",
    )
    for prefix in prefixes:
        left_values = {token for token in left_tokens if token.startswith(prefix)}
        right_values = {token for token in right_tokens if token.startswith(prefix)}
        if left_values and right_values and not left_values & right_values:
            return True
    return False


def _shared_group_tokens(members: list[dict]) -> list[str]:
    token_sets = [_candidate_spec_tokens(member) for member in members]
    if not token_sets:
        return []
    shared = set.intersection(*token_sets)
    return sorted(shared)[:20]


def _normalized_seller(candidate: dict) -> str:
    return _normalize_compact(candidate.get("seller_name"))


def _normalized_location(candidate: dict) -> str:
    return _normalize_compact(candidate.get("location"))


def _normalize_compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _title_tokens(candidate: dict) -> set[str]:
    text = str(candidate.get("title") or "").lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    words.update(token for token in re.split(r"\s+", text) if len(token) >= 2)
    return words


def _token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _price_gap_ratio(left: int | None, right: int | None) -> float | None:
    if left is None or right is None or max(left, right) <= 0:
        return None
    return round(abs(left - right) / max(left, right), 3)


def _group_confidence(matches: list[dict]) -> str:
    if not matches:
        return "low"
    return max((match["confidence"] for match in matches), key=_confidence_rank)


def _dedupe_strings(items) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _confidence_rank(confidence: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(confidence, 0)


def _find(parent: dict[int, int], value: int) -> int:
    while parent[value] != value:
        parent[value] = parent[parent[value]]
        value = parent[value]
    return value


def _union(parent: dict[int, int], left: int, right: int) -> None:
    left_root = _find(parent, left)
    right_root = _find(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def _truncate(value: str, max_chars: int) -> str:
    value = " ".join(value.split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "..."
