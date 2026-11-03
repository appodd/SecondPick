from __future__ import annotations

from shopping_agent.cli import build_parser
from shopping_agent.goal_plan import GoalPlanOptions, build_goal_plan


def test_goal_plan_for_ambiguous_macbook_pro_m1_guides_clarification_and_alternatives() -> None:
    plan = build_goal_plan(
        "我想找一台 MacBook Pro，M1",
        options=GoalPlanOptions(city="上海", platforms=["xianyu"]),
    )

    queries = [round_["query"] for round_ in plan["search_rounds"]]
    questions = "\n".join(plan["clarification_questions"])
    alternatives = "\n".join(item["query"] for item in plan["search_rounds"] if item.get("alternative"))

    assert plan["interpreted_intent"]["family"] == "macbook"
    assert plan["interpreted_intent"]["subtype"] == "pro"
    assert "MacBook Pro M1" in queries
    assert "MacBook Pro M1 Pro" in queries
    assert "MacBook Pro M2 Pro" in alternatives
    assert "基础款 M1" in questions
    assert plan["conditional_filters"][0]["filters"] == {"min_price": 3000}
    assert any("价格筛选" in item for item in plan["web_coverage_strategy"])
    assert any("新增 URL" in item for item in plan["web_coverage_strategy"])
    assert "run-summary" in plan["next_tool_sequence"]
    assert "candidate-pool" in plan["next_tool_sequence"]


def test_goal_plan_for_imac_adds_chinese_terms_and_adjacent_year() -> None:
    plan = build_goal_plan(
        "2019 年 27寸 iMac，上海优先",
        options=GoalPlanOptions(city="上海", platforms=["xianyu"]),
    )

    queries = [round_["query"] for round_ in plan["search_rounds"]]
    questions = "\n".join(plan["clarification_questions"])

    assert plan["interpreted_intent"]["family"] == "imac"
    assert "iMac 27" in queries
    assert "苹果一体机 27寸 5K" in queries
    assert "2019 iMac 27" in queries
    assert "2020 iMac 27" in queries
    assert "Fusion Drive" in questions


def test_goal_plan_for_imac_deduplicates_adjacent_year() -> None:
    plan = build_goal_plan(
        "2019 年 27寸 iMac，上海优先",
        options=GoalPlanOptions(city="上海", platforms=["xianyu"]),
    )

    queries = [round_["query"] for round_ in plan["search_rounds"]]
    alternatives = [round_["query"] for round_ in plan["search_rounds"] if round_.get("alternative")]

    assert queries.count("2020 iMac 27") == 1
    assert alternatives == ["2020 iMac 27"]
    assert queries[:3] == ["iMac 27", "2019 iMac 27", "苹果一体机 27寸 5K"]


def test_goal_plan_combines_macbook_chip_size_memory_and_adjacent_model() -> None:
    plan = build_goal_plan(
        "MacBook Pro M1 Pro 14 32G 上海优先",
        options=GoalPlanOptions(city="上海", platforms=["xianyu"]),
    )

    queries = [round_["query"] for round_ in plan["search_rounds"]]
    alternatives = [round_["query"] for round_ in plan["search_rounds"] if round_.get("alternative")]

    assert plan["interpreted_intent"]["chips"] == ["M1", "M1 PRO"]
    assert plan["interpreted_intent"]["screen_sizes"] == [14]
    assert plan["interpreted_intent"]["memory_gb"] == 32
    assert "MacBook Pro M1 Pro 14寸 32G" in queries
    assert "MacBook Pro M1 PRO" not in queries
    assert "MacBook Pro M1" not in queries
    assert "MacBook Pro M2 Pro 14寸 32G" in alternatives


def test_goal_plan_cli_accepts_fuzzy_goal_options() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "goal-plan",
            "想买 MacBook Pro M1 Pro",
            "--city",
            "上海",
            "--platform",
            "xianyu",
            "--pretty",
        ]
    )

    assert args.command == "goal-plan"
    assert args.city == "上海"
    assert args.platform == ["xianyu"]
    assert args.pretty is True
