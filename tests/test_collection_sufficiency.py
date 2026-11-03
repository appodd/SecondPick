from __future__ import annotations

from shopping_agent.collection_sufficiency import build_collection_sufficiency


def test_collection_sufficiency_prefers_stage_report_once_ready_candidates_exist() -> None:
    candidates = [
        _candidate(index, ready=True, has_detail=True, has_images=True, has_ocr=True)
        for index in range(4)
    ]

    result = build_collection_sufficiency({"all_candidates": candidates})

    assert result["deep_evidence_layer"]["ready_candidate_count"] == 4
    assert result["recommended_next_collection"]["primary_action"] == "generate_stage_report"
    assert result["recommended_next_collection"]["follow_up_action"] is None
    assert result["recommended_next_collection"]["is_blocked"] is False


def test_collection_sufficiency_searches_more_when_card_layer_is_thin() -> None:
    candidates = [_candidate(index, description="M1 Pro") for index in range(6)]

    result = build_collection_sufficiency({"all_candidates": candidates})

    assert result["card_layer"]["status"] == "thin"
    assert result["recommended_next_collection"]["primary_action"] == "search_more_cards"
    assert any(gap["code"] == "candidate_count_below_target" for gap in result["gaps"])


def test_collection_sufficiency_prefers_detail_prepass_when_thin_but_plausible() -> None:
    candidates = [
        _candidate(
            index,
            title=f"Sony A7C body unit {index}",
            description="Sony A7C body shutter count full frame camera",
            signals=_camera_signals(),
        )
        for index in range(8)
    ]

    result = build_collection_sufficiency({"all_candidates": candidates})

    assert result["card_layer"]["status"] == "thin"
    assert result["recommended_next_collection"]["primary_action"] == "capture_detail_text_prepass"
    assert result["recommended_next_collection"]["follow_up_action"] == "search_more_cards"
    assert result["detail_layer"]["prepass_candidate_listing_ids"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert "--media-limit 0 --ocr-limit 0" in result["recommended_next_collection"]["command_previews"][0]


def test_collection_sufficiency_counts_camera_spec_signals() -> None:
    candidates = [
        _candidate(
            index,
            title=f"Sony A7M3 body unit {index}",
            description="Sony A7M3 full frame body only, shutter count visible, no repair",
            signals=_camera_signals(model="a7m3"),
        )
        for index in range(50)
    ]

    result = build_collection_sufficiency({"all_candidates": candidates})

    assert result["card_layer"]["status"] == "usable"
    assert result["card_layer"]["spec_signal_candidate_count"] == 50
    assert result["card_layer"]["spec_signal_ratio"] == 1.0


def test_collection_sufficiency_counts_display_spec_signals() -> None:
    candidates = [
        _candidate(
            index,
            title=f"27寸 4K 160Hz 显示器 unit {index}",
            description="27 inch 4K 160Hz Fast IPS monitor with warranty and no dead pixels",
            signals={
                "mentions_display": True,
                "mentions_4k": True,
                "mentions_high_refresh": True,
                "mentions_ips": True,
                "mentions_warranty": True,
                "mentions_dead_pixel_check": True,
            },
        )
        for index in range(50)
    ]

    result = build_collection_sufficiency({"all_candidates": candidates})

    assert result["card_layer"]["status"] == "usable"
    assert result["card_layer"]["spec_signal_candidate_count"] == 50
    assert result["card_layer"]["spec_signal_ratio"] == 1.0


def test_collection_sufficiency_captures_detail_after_usable_card_layer() -> None:
    candidates = [
        _candidate(index, description="MacBook Pro M1 Pro 16G 512G personal used machine with clean description")
        for index in range(50)
    ]

    result = build_collection_sufficiency({"all_candidates": candidates})

    assert result["card_layer"]["status"] == "usable"
    assert result["detail_layer"]["target"] == 20
    assert result["detail_layer"]["prepass_candidate_listing_ids"][:3] == [1, 2, 3]
    assert result["detail_layer"]["prepass_command_previews"][0] == (
        "python -m shopping_agent.cli prepare-evidence --run-id 100 --platform xianyu "
        "--detail-limit 12 --media-limit 0 --ocr-limit 0 --wait-ms 5000 "
        "--listing-id 1 --listing-id 2 --listing-id 3 --listing-id 4 --listing-id 5 --listing-id 6 "
        "--listing-id 7 --listing-id 8 --listing-id 9 --listing-id 10 --listing-id 11 --listing-id 12 "
        "--i-understand-account-risk --pretty"
    )
    assert result["recommended_next_collection"]["primary_action"] == "capture_detail_text_prepass"
    assert result["recommended_next_collection"]["command_previews"] == result["detail_layer"]["prepass_command_previews"]


def test_collection_sufficiency_prepares_deep_evidence_after_detail_target() -> None:
    candidates = [
        _candidate(
            index,
            description="MacBook Pro M1 Pro 16G 512G personal used machine with clean description",
            has_detail=index < 20,
        )
        for index in range(50)
    ]

    result = build_collection_sufficiency({"all_candidates": candidates})

    assert result["detail_layer"]["status"] == "enough"
    assert result["recommended_next_collection"]["primary_action"] == "prepare_deep_evidence"


def test_collection_sufficiency_does_not_recommend_empty_detail_prepass() -> None:
    candidates = [
        _candidate(
            index,
            description="MacBook Pro M1 Pro 16G 512G personal used machine with clean description",
            has_detail=index < 14,
        )
        for index in range(50)
    ]
    candidate_pool = {
        "all_candidates": candidates,
        "shortlist_for_next_evidence": candidates[:12],
    }

    result = build_collection_sufficiency(candidate_pool)

    assert result["card_layer"]["status"] == "usable"
    assert result["detail_layer"]["status"] == "needs_more_detail_text"
    assert result["detail_layer"]["prepass_candidate_listing_ids"] == []
    assert result["recommended_next_collection"]["primary_action"] == "prepare_deep_evidence"
    assert result["recommended_next_collection"]["detail_gap_remaining"] == 6


def _candidate(
    index: int,
    *,
    title: str | None = None,
    description: str = "MacBook Pro M1 Pro 16G 512G personal used machine with clean description",
    signals: dict | None = None,
    ready: bool = False,
    has_detail: bool = False,
    has_images: bool = False,
    has_ocr: bool = False,
) -> dict:
    return {
        "listing_id": index + 1,
        "first_seen_run_id": 100,
        "platform": "xianyu",
        "title": title or f"MacBook Pro M1 Pro unit {index}",
        "price_value": 6000 + index,
        "location": "Shanghai",
        "description_excerpt": description,
        "signals": signals or {
            "mentions_macbook_pro": True,
            "mentions_m_pro_or_max": True,
            "mentions_512": True,
        },
        "collection_state": {
            "has_detail": has_detail,
            "has_downloaded_images": has_images,
            "has_ocr": has_ocr,
        },
        "candidate_status": {
            "state": "ready_for_evaluation" if ready else "needs_evidence",
            "ready_for_evaluation": ready,
        },
    }


def _camera_signals(*, model: str = "a7c") -> dict:
    return {
        "mentions_camera": True,
        "mentions_sony": True,
        f"mentions_{model}": True,
        "mentions_full_frame": True,
        "mentions_body_only": True,
        "mentions_shutter_count": True,
        "mentions_no_repair": True,
    }
