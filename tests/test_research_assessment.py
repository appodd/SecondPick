from __future__ import annotations

import json

from shopping_agent.research_assessment import build_research_assessment


def test_research_assessment_marks_dry_run_as_not_executed() -> None:
    assessment = build_research_assessment(
        goal_plan={"search_rounds": []},
        selected_searches=[{"platform": "xianyu", "query": "MacBook Pro M1", "filters": {}}],
        run_summaries=[],
        candidate_pool=None,
    )

    assert assessment["status"] == "not_executed"
    assert assessment["decision_owner"] == "llm"
    assert assessment["is_final_recommendation"] is False
    assert assessment["model_decision_brief"]["search_quality"] == "not_executed"
    assert assessment["model_decision_brief"]["recommended_next_move"] == "execute_selected_searches"
    assert assessment["model_decision_brief"]["can_write_final_report_now"] is False
    assert assessment["suggested_next_actions"][0]["type"] == "execute_selected_searches"
    assert assessment["next_search_candidates"][0]["query"] == "MacBook Pro M1"
    assert assessment["next_search_candidates"][0]["source"] == "selected_first_round"


def test_research_assessment_surfaces_nonblocking_user_calibration_questions() -> None:
    assessment = build_research_assessment(
        goal_plan={
            "interpreted_intent": {"family": "macbook", "subtype": "pro"},
            "search_rounds": [{"round": 1, "platform": "xianyu", "query": "MacBook Pro M1", "filters": {}}],
            "clarification_questions": [
                "你说的 M1 是基础款 M1，还是 M1 Pro/M1 Max？",
                "14 寸和 16 寸是否都接受？",
                "是否接受 M2 Pro 这类相邻方案？",
            ],
        },
        selected_searches=[{"platform": "xianyu", "query": "MacBook Pro M1", "filters": {}}],
        run_summaries=[],
        candidate_pool=None,
    )

    calibration = assessment["user_calibration"]

    assert calibration["stage"] == "before_first_search"
    assert calibration["should_block_collection"] is False
    assert calibration["blocking_questions"] == []
    assert calibration["nonblocking_questions"][0]["question"].startswith("你说的 M1")
    assert calibration["nonblocking_questions"][0]["blocking"] is False
    assert "不应默认阻塞首轮宽搜索" in calibration["policy"]


def test_research_assessment_blocks_collection_when_product_identity_is_unclear() -> None:
    assessment = build_research_assessment(
        goal_plan={
            "interpreted_intent": {"family": "generic"},
            "search_rounds": [{"round": 1, "platform": "xianyu", "query": "想买个二手电脑", "filters": {}}],
            "clarification_questions": ["目标商品的品牌、型号、预算、成色和地区偏好是什么？"],
        },
        selected_searches=[{"platform": "xianyu", "query": "想买个二手电脑", "filters": {}}],
        run_summaries=[],
        candidate_pool=None,
    )

    calibration = assessment["user_calibration"]

    assert calibration["should_block_collection"] is True
    assert calibration["blocking_questions"][0]["blocking"] is True
    assert "商品身份或品类太宽" in calibration["blocking_questions"][0]["reason"]


def test_research_assessment_surfaces_noise_and_conditional_filter() -> None:
    goal_plan = {
        "search_rounds": [],
        "conditional_filters": [
            {
                "filters": {"min_price": 3000, "area": "Shanghai", "personal_only": True, "sort": "newest"},
                "reason": "Too many accessories or services in the first search.",
            }
        ],
    }
    candidate_pool = {
        "candidate_count": 4,
        "all_candidates": [
            {"signals": {"likely_accessory_or_parts": True}},
            {"signals": {"likely_service_listing": True}},
            {"signals": {"suspicious_low_price_for_target": True}},
            {"signals": {}},
        ],
        "shortlist_for_next_evidence": [],
    }

    assessment = build_research_assessment(
        goal_plan=goal_plan,
        selected_searches=[{"platform": "xianyu", "query": "MacBook Pro M1", "filters": {}}],
        run_summaries=[
            {
                "result_quality": {
                    "access_blocked": False,
                    "listing_count": 20,
                    "priced_listing_count": 20,
                    "located_listing_count": 18,
                }
            }
        ],
        candidate_pool=candidate_pool,
    )

    action_types = [action["type"] for action in assessment["suggested_next_actions"]]

    assert "high_noise_ratio" in assessment["quality_flags"]
    assert assessment["model_decision_brief"]["search_quality"] == "noisy"
    assert assessment["model_decision_brief"]["recommended_next_move"] == "revise_search_terms_or_apply_conditional_filter"
    assert "Official specs" in assessment["model_decision_brief"]["why_not_final_report"][-1]
    assert "consider_conditional_filter" in action_types
    assert assessment["suggested_next_actions"][0]["filters"] == {
        "min_price": 3000,
        "area": "Shanghai",
        "sort": "newest",
    }
    assert assessment["next_search_candidates"][0]["filters"] == {
        "min_price": 3000,
        "area": "Shanghai",
        "sort": "newest",
    }
    assert assessment["next_search_candidates"][0]["cli_filter_args"] == [
        "--min-price",
        "3000",
        "--area",
        "Shanghai",
        "--sort",
        "newest",
    ]
    assert assessment["next_search_candidates"][0]["source"] == "conditional_filter"


def test_research_assessment_suggests_evidence_for_shortlist() -> None:
    candidate_pool = {
        "candidate_count": 2,
        "all_candidates": [
            {"signals": {}},
            {"signals": {}},
        ],
        "shortlist_for_next_evidence": [
            {
                "listing_id": 10,
                "collection_state": {"has_detail": False, "has_downloaded_images": False, "has_ocr": False},
            },
            {
                "listing_id": 11,
                "collection_state": {"has_detail": True, "has_downloaded_images": False, "has_ocr": False},
            },
        ],
    }

    assessment = build_research_assessment(
        goal_plan={"search_rounds": [], "conditional_filters": []},
        selected_searches=[],
        run_summaries=[
            {
                "result_quality": {
                    "access_blocked": False,
                    "listing_count": 20,
                    "priced_listing_count": 20,
                    "located_listing_count": 20,
                }
            }
        ],
        candidate_pool=candidate_pool,
    )

    prepare_actions = [action for action in assessment["suggested_next_actions"] if action["type"] == "prepare_evidence"]
    evaluation_actions = [
        action for action in assessment["suggested_next_actions"] if action["type"] == "build_evaluation_task"
    ]
    recommendation_actions = [
        action for action in assessment["suggested_next_actions"] if action["type"] == "inspect_recommendation_links"
    ]

    assert assessment["coverage"]["ready_shortlist_count"] == 1
    assert assessment["coverage"]["shortlist_missing_evidence_count"] == 1
    assert assessment["model_decision_brief"]["evidence_readiness"] == "partially_ready_for_evaluation_task"
    assert assessment["model_decision_brief"]["recommended_next_move"] == "prepare_evidence_for_shortlist"
    assert assessment["model_decision_brief"]["can_start_final_evaluation"] is True
    assert assessment["model_decision_brief"]["can_write_final_report_now"] is False
    assert prepare_actions[0]["listing_ids"] == [10]
    assert evaluation_actions[0]["listing_ids"] == [11]
    assert recommendation_actions[0]["listing_ids"] == [11]

    assessment_text = json.dumps(assessment, ensure_ascii=False)
    assert "product images, and OCR" not in assessment_text
    assert "downloaded images, and OCR" not in assessment_text
    assert "detail evidence is sufficient unless a specific unresolved visual question remains" in assessment_text


def test_research_assessment_brief_moves_ready_shortlist_to_evaluation_task() -> None:
    candidate_pool = {
        "candidate_count": 1,
        "all_candidates": [{"signals": {}}],
        "shortlist_for_next_evidence": [
            {
                "listing_id": 11,
                "collection_state": {"has_detail": True, "has_downloaded_images": False, "has_ocr": False},
            }
        ],
    }

    assessment = build_research_assessment(
        goal_plan={"search_rounds": [], "conditional_filters": []},
        selected_searches=[],
        run_summaries=[
            {
                "result_quality": {
                    "access_blocked": False,
                    "listing_count": 1,
                    "priced_listing_count": 1,
                    "located_listing_count": 1,
                }
            }
        ],
        candidate_pool=candidate_pool,
    )

    brief = assessment["model_decision_brief"]

    assert brief["evidence_readiness"] == "ready_for_evaluation_task"
    assert brief["recommended_next_move"] == "build_evaluation_task"
    assert brief["can_start_final_evaluation"] is True
    assert brief["can_write_final_report_now"] is False
    assert "Official or trusted reference specifications" in brief["required_before_final_report"][0]


def test_research_assessment_suggests_compare_runs_for_multiple_runs() -> None:
    assessment = build_research_assessment(
        goal_plan={"search_rounds": [], "conditional_filters": []},
        selected_searches=[],
        run_summaries=[
            {
                "run_id": 30,
                "result_quality": {
                    "access_blocked": False,
                    "listing_count": 10,
                    "priced_listing_count": 10,
                    "located_listing_count": 9,
                },
            },
            {
                "run_id": 31,
                "result_quality": {
                    "access_blocked": False,
                    "listing_count": 8,
                    "priced_listing_count": 8,
                    "located_listing_count": 8,
                },
            },
        ],
        candidate_pool={
            "run_ids": [30, 31],
            "candidate_count": 8,
            "all_candidates": [{"signals": {}}],
            "shortlist_for_next_evidence": [],
        },
    )

    compare_actions = [action for action in assessment["suggested_next_actions"] if action["type"] == "compare_runs"]

    assert compare_actions[0]["priority"] == "high"
    assert compare_actions[0]["run_ids"] == [30, 31]
    assert "Multiple search runs" in compare_actions[0]["reason"]


def test_research_assessment_offers_remaining_planned_searches_for_small_pool() -> None:
    goal_plan = {
        "search_rounds": [
            {"round": 1, "platform": "xianyu", "query": "MacBook Pro M1", "filters": {}},
            {"round": 2, "platform": "xianyu", "query": "MacBook Pro M1 Pro", "filters": {}},
            {"round": 3, "platform": "xianyu", "query": "MacBook Pro M2 Pro", "filters": {}, "alternative": True},
        ],
        "conditional_filters": [],
    }
    selected = [goal_plan["search_rounds"][0]]
    candidate_pool = {
        "candidate_count": 2,
        "all_candidates": [{"signals": {}}, {"signals": {}}],
        "shortlist_for_next_evidence": [],
    }

    assessment = build_research_assessment(
        goal_plan=goal_plan,
        selected_searches=selected,
        run_summaries=[
            {
                "result_quality": {
                    "access_blocked": False,
                    "listing_count": 2,
                    "priced_listing_count": 2,
                    "located_listing_count": 2,
                }
            }
        ],
        candidate_pool=candidate_pool,
    )

    queries = [candidate["query"] for candidate in assessment["next_search_candidates"]]

    assert "low_candidate_count" in assessment["quality_flags"]
    assert assessment["model_decision_brief"]["search_quality"] == "thin"
    assert assessment["model_decision_brief"]["recommended_next_move"] == "broaden_or_try_remaining_planned_searches"
    assert "MacBook Pro M1 Pro" in queries
    assert "MacBook Pro M2 Pro" in queries
    assert all(candidate["execute_by_default"] is False for candidate in assessment["next_search_candidates"])


def test_research_assessment_prioritizes_size_specific_search_when_noise_is_wrong_size() -> None:
    goal_plan = {
        "interpreted_intent": {"family": "macbook", "subtype": "pro", "screen_sizes": [14]},
        "search_rounds": [
            {"round": 1, "platform": "xianyu", "query": "MacBook Pro M1", "filters": {}},
            {"round": 2, "platform": "xianyu", "query": "MacBook Pro M1 Pro 14 32G", "filters": {}},
            {
                "round": 3,
                "platform": "xianyu",
                "query": "MacBook Pro M2 Pro 14 32G",
                "filters": {},
                "alternative": True,
            },
            {"round": 4, "platform": "xianyu", "query": "MacBook Pro 32G", "filters": {}},
        ],
        "conditional_filters": [
            {
                "filters": {"min_price": 3000},
                "reason": "Too many irrelevant listings in the first search.",
            }
        ],
    }
    selected = [goal_plan["search_rounds"][0]]
    wrong_size_candidates = [{"signals": {"likely_non_target_size": True}} for _ in range(7)]
    neutral_candidates = [{"signals": {}} for _ in range(12)]
    city_candidate = [{"signals": {"target_city_hint": True}}]
    candidate_pool = {
        "candidate_count": 20,
        "all_candidates": wrong_size_candidates + neutral_candidates + city_candidate,
        "shortlist_for_next_evidence": [],
    }

    assessment = build_research_assessment(
        goal_plan=goal_plan,
        selected_searches=selected,
        run_summaries=[
            {
                "result_quality": {
                    "access_blocked": False,
                    "listing_count": 20,
                    "priced_listing_count": 20,
                    "located_listing_count": 20,
                }
            }
        ],
        candidate_pool=candidate_pool,
    )

    action_types = [action["type"] for action in assessment["suggested_next_actions"]]
    sources = [candidate["source"] for candidate in assessment["next_search_candidates"]]
    queries = [candidate["query"] for candidate in assessment["next_search_candidates"]]

    assert "target_size_mismatch_noise" in assessment["quality_flags"]
    assert "high_noise_ratio" in assessment["quality_flags"]
    assert "revise_size_specific_terms" in action_types
    assert assessment["candidate_signal_counts"]["likely_non_target_size"] == 7
    assert assessment["next_search_candidates"][0]["source"] == "target_size_refinement"
    assert queries[0] == "MacBook Pro M1 Pro 14 32G"
    assert sources.index("target_size_refinement") < sources.index("conditional_filter")


def test_research_assessment_surfaces_missing_target_city_signal() -> None:
    candidate_pool = {
        "region_preference": {"mode": "preferred", "city": "上海"},
        "candidate_count": 16,
        "all_candidates": [{"signals": {}} for _ in range(16)],
        "shortlist_for_next_evidence": [],
    }

    assessment = build_research_assessment(
        goal_plan={"search_rounds": [], "conditional_filters": []},
        selected_searches=[],
        run_summaries=[
            {
                "result_quality": {
                    "access_blocked": False,
                    "listing_count": 16,
                    "priced_listing_count": 16,
                    "located_listing_count": 16,
                }
            }
        ],
        candidate_pool=candidate_pool,
    )

    action_types = [action["type"] for action in assessment["suggested_next_actions"]]

    assert "no_target_city_signal" in assessment["quality_flags"]
    assert "consider_area_or_shipping_tradeoff" in action_types
