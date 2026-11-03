from __future__ import annotations

from statistics import median


CARD_CANDIDATE_TARGET = 120
CARD_CANDIDATE_MIN_USABLE = 50
CLEAN_CANDIDATE_TARGET = 30
DETAIL_TEXT_TARGET_RICH_CARDS = 12
DETAIL_TEXT_TARGET_USABLE_CARDS = 20
DETAIL_TEXT_TARGET_THIN_CARDS = 24
STAGE_READY_TARGET = 4
FINAL_READY_TARGET = 6
DEEP_EVIDENCE_TARGET = 8
DETAIL_PREPASS_BATCH_TARGET = 12
DETAIL_PREPASS_MIN_CLEAN_CANDIDATES = 8


SPEC_SIGNAL_KEYS = (
    # Computer / Apple signals.
    "mentions_macbook_pro",
    "mentions_macbook_air",
    "mentions_m_series",
    "mentions_m_pro_or_max",
    "mentions_14",
    "mentions_16",
    "mentions_32g",
    "mentions_512",
    "mentions_1t",
    "mentions_imac",
    "mentions_27",
    "mentions_5k",
    "mentions_i9",
    "mentions_580x",
    "target_year_hint",
    "adjacent_year_hint",
    # Camera signals.
    "mentions_camera",
    "mentions_sony",
    "mentions_a7c",
    "mentions_a7m3",
    "mentions_a7m4",
    "mentions_full_frame",
    "mentions_body_only",
    "mentions_shutter_count",
    "mentions_no_repair",
    "mentions_cmos",
    # Display / monitor signals.
    "mentions_display",
    "mentions_4k",
    "mentions_high_refresh",
    "mentions_miniled",
    "mentions_hdr",
    "mentions_hdr1000",
    "mentions_ips",
    "mentions_oled",
    "mentions_hdmi21",
    "mentions_dp14",
    "mentions_typec",
    "mentions_warranty",
    "mentions_dead_pixel_check",
)


def build_collection_sufficiency(candidate_pool: dict | None) -> dict:
    candidates = (candidate_pool or {}).get("all_candidates") or []
    clean_candidates = [
        candidate
        for candidate in candidates
        if (candidate.get("candidate_status") or {}).get("state") != "reject_noise"
    ]
    description_lengths = [len(candidate.get("description_excerpt") or "") for candidate in candidates]
    rich_description_count = sum(1 for length in description_lengths if length >= 100)
    spec_signal_count = sum(1 for candidate in candidates if _has_spec_signal(candidate))
    detail_count = sum(1 for candidate in candidates if _collection_state(candidate).get("has_detail"))
    downloaded_image_count = sum(
        1 for candidate in candidates if _collection_state(candidate).get("has_downloaded_images")
    )
    ocr_count = sum(1 for candidate in candidates if _collection_state(candidate).get("has_ocr"))
    ready_count = sum(
        1
        for candidate in candidates
        if (candidate.get("candidate_status") or {}).get("ready_for_evaluation")
    )
    priced_count = sum(1 for candidate in candidates if candidate.get("price_value") is not None)
    located_count = sum(1 for candidate in candidates if candidate.get("location"))
    card_status = _card_layer_status(
        candidate_count=len(candidates),
        clean_candidate_count=len(clean_candidates),
        rich_description_ratio=_ratio(rich_description_count, len(candidates)),
        spec_signal_ratio=_ratio(spec_signal_count, len(candidates)),
    )
    detail_target = _detail_text_target(card_status)
    detail_gap = max(detail_target - detail_count, 0)
    detail_prepass = _detail_text_prepass(candidate_pool or {}, detail_gap=detail_gap)
    gaps = _gaps(
        candidate_count=len(candidates),
        clean_candidate_count=len(clean_candidates),
        detail_count=detail_count,
        detail_target=detail_target,
        ready_count=ready_count,
    )
    recommendation = _recommended_next_collection(
        card_status=card_status,
        candidate_count=len(candidates),
        clean_candidate_count=len(clean_candidates),
        detail_count=detail_count,
        detail_target=detail_target,
        ready_count=ready_count,
        detail_prepass=detail_prepass,
    )
    return {
        "decision_owner": "tool",
        "is_final_recommendation": False,
        "budgets": {
            "card_candidate_target": CARD_CANDIDATE_TARGET,
            "card_candidate_min_usable": CARD_CANDIDATE_MIN_USABLE,
            "clean_candidate_target": CLEAN_CANDIDATE_TARGET,
            "detail_prepass_min_clean_candidates": DETAIL_PREPASS_MIN_CLEAN_CANDIDATES,
            "detail_text_target": detail_target,
            "stage_ready_target": STAGE_READY_TARGET,
            "final_ready_target": FINAL_READY_TARGET,
            "deep_evidence_target": DEEP_EVIDENCE_TARGET,
        },
        "card_layer": {
            "status": card_status,
            "candidate_count": len(candidates),
            "clean_candidate_count": len(clean_candidates),
            "priced_candidate_count": priced_count,
            "located_candidate_count": located_count,
            "price_coverage_ratio": _ratio(priced_count, len(candidates)),
            "location_coverage_ratio": _ratio(located_count, len(candidates)),
            "median_description_chars": int(median(description_lengths)) if description_lengths else 0,
            "rich_description_count": rich_description_count,
            "rich_description_ratio": _ratio(rich_description_count, len(candidates)),
            "spec_signal_candidate_count": spec_signal_count,
            "spec_signal_ratio": _ratio(spec_signal_count, len(candidates)),
        },
        "detail_layer": {
            "status": "enough" if detail_count >= detail_target else "needs_more_detail_text",
            "detail_candidate_count": detail_count,
            "target": detail_target,
            "gap": max(detail_target - detail_count, 0),
            "prepass_candidate_listing_ids": detail_prepass["listing_ids"],
            "prepass_command_previews": detail_prepass["command_previews"],
            "prepass_scope_note": (
                "These commands capture detail page text only by setting media-limit and ocr-limit to 0. "
                "Use them when card coverage is usable but detail context is thin."
            ),
            "purpose": "Seller profile, structured platform attributes, full page context, recommendation links, and image URL entrypoints.",
        },
        "deep_evidence_layer": {
            "status": "stage_ready" if ready_count >= STAGE_READY_TARGET else "needs_more_deep_evidence",
            "ready_candidate_count": ready_count,
            "downloaded_image_candidate_count": downloaded_image_count,
            "ocr_candidate_count": ocr_count,
            "stage_target": STAGE_READY_TARGET,
            "final_target": FINAL_READY_TARGET,
            "gap_to_stage_report": max(STAGE_READY_TARGET - ready_count, 0),
            "gap_to_final_ready_set": max(FINAL_READY_TARGET - ready_count, 0),
        },
        "gaps": gaps,
        "recommended_next_collection": recommendation,
        "notes": [
            "Search cards are useful for discovery, rough spec detection, price distribution, and noise filtering.",
            "Detail text is mainly for seller profile, structured attributes, page context, recommendations, and image URL entrypoints.",
            "Image download and OCR should stay selective because they are slower and provide verification evidence rather than broad discovery.",
        ],
    }


def _card_layer_status(
    *,
    candidate_count: int,
    clean_candidate_count: int,
    rich_description_ratio: float,
    spec_signal_ratio: float,
) -> str:
    if candidate_count >= CARD_CANDIDATE_TARGET and clean_candidate_count >= CLEAN_CANDIDATE_TARGET:
        return "strong"
    if (
        candidate_count >= CARD_CANDIDATE_MIN_USABLE
        and clean_candidate_count >= 20
        and (rich_description_ratio >= 0.5 or spec_signal_ratio >= 0.6)
    ):
        return "usable"
    return "thin"


def _detail_text_target(card_status: str) -> int:
    if card_status == "strong":
        return DETAIL_TEXT_TARGET_RICH_CARDS
    if card_status == "usable":
        return DETAIL_TEXT_TARGET_USABLE_CARDS
    return DETAIL_TEXT_TARGET_THIN_CARDS


def _recommended_next_collection(
    *,
    card_status: str,
    candidate_count: int,
    clean_candidate_count: int,
    detail_count: int,
    detail_target: int,
    ready_count: int,
    detail_prepass: dict,
) -> dict:
    if ready_count >= STAGE_READY_TARGET:
        follow_up_detail_prepass = detail_count < detail_target and bool(detail_prepass["listing_ids"])
        return {
            "primary_action": "generate_stage_report",
            "reason": "Enough ready candidates exist for a staged report. Remaining search/detail gaps should be shown as caveats, not blockers.",
            "follow_up_action": "capture_detail_text_prepass" if follow_up_detail_prepass else None,
            "follow_up_command_previews": detail_prepass["command_previews"] if follow_up_detail_prepass else [],
            "is_blocked": False,
        }
    if (
        detail_count < detail_target
        and clean_candidate_count >= DETAIL_PREPASS_MIN_CLEAN_CANDIDATES
        and detail_prepass["listing_ids"]
    ):
        return {
            "primary_action": "capture_detail_text_prepass",
            "reason": (
                "The card layer is still below the broad target, but enough plausible candidates exist "
                "to capture lightweight detail text before more blind searching."
            ),
            "command_previews": detail_prepass["command_previews"],
            "follow_up_action": "search_more_cards" if card_status == "thin" else None,
            "is_blocked": False,
        }
    if candidate_count == 0 or clean_candidate_count < 10 or card_status == "thin":
        return {
            "primary_action": "search_more_cards",
            "reason": "The card layer is still thin or noisy. More search-card coverage should come before detail/OCR work.",
            "is_blocked": False,
        }
    if detail_count < detail_target:
        return {
            "primary_action": "prepare_deep_evidence",
            "reason": (
                "Detail text is still below the adaptive target, but no remaining shortlisted candidates "
                "are available for a lightweight detail prepass. Move the detailed shortlist into selective "
                "image/OCR evidence, and leave the detail gap as a report caveat or later search expansion."
            ),
            "detail_gap_remaining": max(detail_target - detail_count, 0),
            "is_blocked": False,
        }
    return {
        "primary_action": "prepare_deep_evidence",
        "reason": "Enough cards and detail text exist; download images and OCR a smaller set of high-value candidates.",
        "is_blocked": False,
    }


def _gaps(
    *,
    candidate_count: int,
    clean_candidate_count: int,
    detail_count: int,
    detail_target: int,
    ready_count: int,
) -> list[dict]:
    gaps = []
    if candidate_count < CARD_CANDIDATE_TARGET:
        gaps.append(
            {
                "layer": "card",
                "code": "candidate_count_below_target",
                "current": candidate_count,
                "target": CARD_CANDIDATE_TARGET,
            }
        )
    if clean_candidate_count < CLEAN_CANDIDATE_TARGET:
        gaps.append(
            {
                "layer": "card",
                "code": "clean_candidate_count_below_target",
                "current": clean_candidate_count,
                "target": CLEAN_CANDIDATE_TARGET,
            }
        )
    if detail_count < detail_target:
        gaps.append(
            {
                "layer": "detail",
                "code": "detail_text_below_adaptive_target",
                "current": detail_count,
                "target": detail_target,
            }
        )
    if ready_count < STAGE_READY_TARGET:
        gaps.append(
            {
                "layer": "deep_evidence",
                "code": "ready_candidate_count_below_stage_target",
                "current": ready_count,
                "target": STAGE_READY_TARGET,
            }
        )
    return gaps


def _has_spec_signal(candidate: dict) -> bool:
    signals = candidate.get("signals") or {}
    return any(bool(signals.get(key)) for key in SPEC_SIGNAL_KEYS)


def _collection_state(candidate: dict) -> dict:
    return candidate.get("collection_state") or {}


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def _detail_text_prepass(candidate_pool: dict, *, detail_gap: int) -> dict:
    candidates = candidate_pool.get("shortlist_for_next_evidence") or candidate_pool.get("all_candidates") or []
    limit = min(max(detail_gap, 0), DETAIL_PREPASS_BATCH_TARGET)
    selected = []
    for candidate in candidates:
        if limit <= 0:
            break
        if (candidate.get("candidate_status") or {}).get("state") == "reject_noise":
            continue
        if _collection_state(candidate).get("has_detail"):
            continue
        listing_id = candidate.get("listing_id")
        run_id = candidate.get("first_seen_run_id")
        if not isinstance(listing_id, int) or not isinstance(run_id, int):
            continue
        selected.append(candidate)
        limit -= 1

    batches: dict[tuple[int, str], list[int]] = {}
    for candidate in selected:
        platform = str(candidate.get("platform") or _candidate_pool_platform(candidate_pool) or "xianyu")
        key = (int(candidate["first_seen_run_id"]), platform)
        batches.setdefault(key, []).append(int(candidate["listing_id"]))

    command_previews = [
        _detail_prepass_command(run_id=run_id, platform=platform, listing_ids=listing_ids)
        for (run_id, platform), listing_ids in batches.items()
    ]
    return {
        "listing_ids": [int(candidate["listing_id"]) for candidate in selected],
        "command_previews": command_previews,
    }


def _detail_prepass_command(*, run_id: int, platform: str, listing_ids: list[int]) -> str:
    parts = [
        "python",
        "-m",
        "shopping_agent.cli",
        "prepare-evidence",
        "--run-id",
        str(run_id),
        "--platform",
        platform,
        "--detail-limit",
        str(len(listing_ids)),
        "--media-limit",
        "0",
        "--ocr-limit",
        "0",
        "--wait-ms",
        "5000",
    ]
    for listing_id in listing_ids:
        parts.extend(["--listing-id", str(listing_id)])
    if platform == "xianyu":
        parts.append("--i-understand-account-risk")
    parts.append("--pretty")
    return " ".join(parts)


def _candidate_pool_platform(candidate_pool: dict) -> str | None:
    for candidate in candidate_pool.get("all_candidates") or []:
        platform = candidate.get("platform")
        if platform:
            return str(platform)
    return None
