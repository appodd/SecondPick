from __future__ import annotations

import asyncio
from pathlib import Path

from shopping_agent.browser.session import SearchSnapshot
from shopping_agent.cli import build_parser
from shopping_agent.config import AppConfig
from shopping_agent.research_loop import ResearchLoopOptions, _assessment_with_command_previews, run_research_loop
from shopping_agent.spike import SearchSpikeResult


def test_research_loop_default_candidate_capacity_supports_task_target() -> None:
    parser = build_parser()

    assert ResearchLoopOptions().candidate_limit == 600
    assert ResearchLoopOptions().max_searches == 2
    assert parser.parse_args(["research-loop", "R9000P"]).candidate_limit == 600
    assert parser.parse_args(["research-loop", "R9000P"]).max_searches == 2


def test_research_loop_decision_points_keep_detail_and_ocr_targeted() -> None:
    result = asyncio.run(
        run_research_loop(
            AppConfig(default_city="上海", platforms=["xianyu"]),
            "R9000P 4060",
            options=ResearchLoopOptions(max_searches=2),
        )
    )

    decision_text = "\n".join(result["next_decision_points"])

    assert "3-5 candidates" not in decision_text
    assert "specific unresolved visual question" in decision_text
    assert "image download, OCR" not in decision_text


def test_research_loop_cli_accepts_dry_run_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "research-loop",
            "MacBook Pro M1",
            "--city",
            "Shanghai",
            "--platform",
            "xianyu",
            "--max-searches",
            "3",
            "--pretty",
        ]
    )

    assert args.command == "research-loop"
    assert args.goal == "MacBook Pro M1"
    assert args.city == "Shanghai"
    assert args.platform == ["xianyu"]
    assert args.max_searches == 3
    assert args.execute_search is False


def test_research_loop_cli_accepts_task_id() -> None:
    parser = build_parser()

    args = parser.parse_args(["research-loop", "MacBook Pro M1", "--execute-search", "--task-id", "7"])

    assert args.command == "research-loop"
    assert args.task_id == 7


def test_research_cli_is_goal_entrypoint_with_codex_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "research",
            "帮我找 2019 年 27 寸 iMac，上海优先",
            "--city",
            "上海",
            "--platform",
            "xianyu",
            "--codex-arg=-a",
            "--codex-arg=never",
            "--run",
        ]
    )

    assert args.command == "research"
    assert args.goal == "帮我找 2019 年 27 寸 iMac，上海优先"
    assert args.city == "上海"
    assert args.platform == ["xianyu"]
    assert args.codex_arg == ["-a", "never"]
    assert args.run is True


def test_codex_guide_cli_accepts_goal_context_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "codex-guide",
            "--goal",
            "帮我找 2019 年 27 寸 iMac，上海优先",
            "--city",
            "上海",
            "--platform",
            "xianyu",
        ]
    )

    assert args.command == "codex-guide"
    assert args.goal == "帮我找 2019 年 27 寸 iMac，上海优先"
    assert args.city == "上海"
    assert args.platform == ["xianyu"]


def test_report_template_cli_accepts_html_format() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "report-template",
            "--title",
            "iMac 对比",
            "--goal",
            "找 2019 iMac 27 寸",
            "--run-id",
            "4",
            "--format",
            "html",
        ]
    )

    assert args.command == "report-template"
    assert args.title == "iMac 对比"
    assert args.goal == "找 2019 iMac 27 寸"
    assert args.run_id == 4
    assert args.format == "html"


def test_research_loop_dry_run_builds_goal_plan_and_command_previews() -> None:
    config = AppConfig(default_city="Shanghai", platforms=["xianyu"])

    result = asyncio.run(
        run_research_loop(
            config,
            "MacBook Pro M1",
            options=ResearchLoopOptions(city="Shanghai", platforms=["xianyu"], max_searches=2),
        )
    )

    assert result["mode"] == "dry-run"
    assert result["browser_access"] == "not_started"
    assert result["executed_run_ids"] == []
    assert result["candidate_pool"] is None
    assert result["loop_assessment"]["status"] == "not_executed"
    assert result["loop_assessment"]["decision_owner"] == "llm"
    assert result["loop_assessment"]["next_search_candidates"][0]["execute_by_default"] is False
    assert "spike-search xianyu" in result["loop_assessment"]["next_search_candidates"][0]["command_preview"]
    assert "--i-understand-account-risk" in result["loop_assessment"]["next_search_candidates"][0]["command_preview"]
    assert result["goal_plan"]["interpreted_intent"]["family"] == "macbook"
    assert len(result["selected_searches"]) == 2
    assert all("spike-search xianyu" in item["command_preview"] for item in result["selected_searches"])
    assert result["selected_searches"][0]["requires_account_risk_acknowledgement"] is True
    assert "--i-understand-account-risk" in result["selected_searches"][0]["command_preview"]


def test_research_loop_selection_includes_adjacent_model_when_budget_allows() -> None:
    config = AppConfig(default_city="Shanghai", platforms=["xianyu"])

    result = asyncio.run(
        run_research_loop(
            config,
            "MacBook Pro M1",
            options=ResearchLoopOptions(city="Shanghai", platforms=["xianyu"], max_searches=3),
        )
    )

    queries = [item["query"] for item in result["selected_searches"]]

    assert len(queries) == 3
    assert "MacBook Pro M2 Pro" in queries


def test_research_loop_imac_selection_keeps_exact_year_and_adjacent_year() -> None:
    config = AppConfig(default_city="上海", platforms=["xianyu"])

    result = asyncio.run(
        run_research_loop(
            config,
            "帮我找 2019 年 27 寸 iMac，上海优先",
            options=ResearchLoopOptions(city="上海", platforms=["xianyu"], max_searches=3),
        )
    )

    queries = [item["query"] for item in result["selected_searches"]]

    assert queries == ["iMac 27", "2019 iMac 27", "2020 iMac 27"]


def test_research_loop_real_chinese_imac_goal_is_nonblocking_dry_run() -> None:
    config = AppConfig(default_city="上海", platforms=["xianyu"])
    goal = "帮我找 2019 年 27 寸 iMac，上海优先"

    result = asyncio.run(
        run_research_loop(
            config,
            goal,
            options=ResearchLoopOptions(city="上海", platforms=["xianyu"], max_searches=3),
        )
    )

    queries = [item["query"] for item in result["selected_searches"]]
    assessment = result["loop_assessment"]
    calibration = assessment["user_calibration"]

    assert result["mode"] == "dry-run"
    assert result["browser_access"] == "not_started"
    assert result["city"] == "上海"
    assert result["platforms"] == ["xianyu"]
    assert result["executed_run_ids"] == []
    assert result["goal_plan"]["interpreted_intent"]["family"] == "imac"
    assert result["goal_plan"]["interpreted_intent"]["years"] == [2019]
    assert result["goal_plan"]["interpreted_intent"]["screen_sizes"] == [27]
    assert result["goal_plan"]["interpreted_intent"]["mentions_city"] == "上海"
    assert queries == ["iMac 27", "2019 iMac 27", "2020 iMac 27"]
    assert all("--i-understand-account-risk" in item["command_preview"] for item in result["selected_searches"])
    assert assessment["model_decision_brief"]["recommended_next_move"] == "execute_selected_searches"
    assert assessment["model_decision_brief"]["can_write_final_report_now"] is False
    assert calibration["should_block_collection"] is False
    assert calibration["blocking_questions"] == []
    assert any("2020" in item["question"] for item in calibration["nonblocking_questions"])


def test_research_loop_next_search_command_preview_ignores_seller_type_filter() -> None:
    assessment = {
        "next_search_candidates": [
            {
                "platform": "xianyu",
                "query": "MacBook Pro M1",
                "filters": {"min_price": 3000, "area": "Shanghai", "personal_only": True, "sort": "newest"},
                "execute_by_default": False,
            }
        ]
    }

    enriched = _assessment_with_command_previews(
        assessment,
        options=ResearchLoopOptions(scroll_steps=8, scroll_wait_ms=900),
    )
    command = enriched["next_search_candidates"][0]["command_preview"]

    assert "python -m shopping_agent.cli spike-search xianyu" in command
    assert "--min-price 3000" in command
    assert "--area Shanghai" in command
    assert "--personal-only" not in command
    assert "--sort newest" in command
    assert "--scroll-steps 8 --scroll-wait-ms 900" in command
    assert "--wait-ms 5000" in command
    assert "--i-understand-account-risk" in command


def test_research_loop_prepare_evidence_action_gets_command_preview() -> None:
    assessment = {
        "next_search_candidates": [],
        "suggested_next_actions": [
            {
                "type": "prepare_evidence",
                "priority": "high",
                "listing_ids": [10, 11],
            }
        ],
    }
    candidate_pool = {
        "run_ids": [30, 31],
        "all_candidates": [{"platform": "xianyu"}],
    }

    enriched = _assessment_with_command_previews(
        assessment,
        options=ResearchLoopOptions(wait_ms=6000),
        candidate_pool=candidate_pool,
    )
    action = enriched["suggested_next_actions"][0]

    assert action["requires_account_risk_acknowledgement"] is True
    assert action["command_previews"][0] == (
        "python -m shopping_agent.cli prepare-evidence --run-id 30 --platform xianyu "
        "--detail-limit 3 --media-limit 0 --ocr-limit 0 --wait-ms 6000 "
        "--i-understand-account-risk --pretty"
    )
    assert "--run-id 31" in action["command_previews"][1]
    assert "works per run" in action["command_scope_note"]


def test_research_loop_compare_runs_action_gets_command_preview() -> None:
    assessment = {
        "next_search_candidates": [],
        "suggested_next_actions": [
            {
                "type": "compare_runs",
                "priority": "high",
                "run_ids": [30, 31],
            }
        ],
    }

    enriched = _assessment_with_command_previews(
        assessment,
        options=ResearchLoopOptions(city="Shanghai"),
        goal="MacBook Pro M1",
    )
    action = enriched["suggested_next_actions"][0]

    assert action["command_preview"] == (
        'python -m shopping_agent.cli compare-runs --run-id 30 --run-id 31 '
        '--goal "MacBook Pro M1" --target-city Shanghai --pretty'
    )
    assert "local run summaries" in action["command_scope_note"]
    assert "LLM still decides" in action["command_scope_note"]


def test_research_loop_evaluation_task_action_gets_command_preview() -> None:
    assessment = {
        "next_search_candidates": [],
        "suggested_next_actions": [
            {
                "type": "build_evaluation_task",
                "priority": "high",
                "listing_ids": [11],
            }
        ],
    }

    enriched = _assessment_with_command_previews(
        assessment,
        options=ResearchLoopOptions(),
        goal="我想找一台 MacBook Pro，M1",
    )
    action = enriched["suggested_next_actions"][0]

    assert action["command_previews"] == [
        'python -m shopping_agent.cli evaluation-task --listing-id 11 --goal "我想找一台 MacBook Pro，M1" --format prompt'
    ]
    assert "final risk" in action["command_scope_note"]


def test_research_loop_recommendation_links_action_gets_command_preview() -> None:
    assessment = {
        "next_search_candidates": [],
        "suggested_next_actions": [
            {
                "type": "inspect_recommendation_links",
                "priority": "medium",
                "listing_ids": [11, 12],
            }
        ],
    }

    enriched = _assessment_with_command_previews(
        assessment,
        options=ResearchLoopOptions(),
    )
    action = enriched["suggested_next_actions"][0]

    assert action["command_previews"] == [
        "python -m shopping_agent.cli recommendation-links --listing-id 11 --pretty",
        "python -m shopping_agent.cli recommendation-links --listing-id 12 --pretty",
    ]
    assert "already captured detail-page snapshots" in action["command_scope_note"]


def test_research_loop_execute_wires_spike_summary_and_candidate_pool(monkeypatch) -> None:
    import shopping_agent.research_loop as module

    config = AppConfig(default_city="Shanghai", platforms=["xianyu"])
    captured_queries: list[str] = []
    safety_calls: list[tuple[str, bool, bool]] = []
    attached_runs: list[tuple[int, int, str]] = []

    async def fake_capture_search_spike(**kwargs) -> SearchSpikeResult:
        captured_queries.append(kwargs["query"])
        snapshot = SearchSnapshot(
            platform=kwargs["platform"],
            query=kwargs["query"],
            url="https://www.goofish.com/search?q=test",
            screenshot_path=Path("data/screenshots/test.png"),
            html_path=Path("data/screenshots/test.html"),
            page_title="test",
            visible_text="",
            links=[],
            access_blocked=False,
        )
        return SearchSpikeResult(
            snapshot=snapshot,
            text_path=Path("data/screenshots/test.txt"),
            links_path=Path("data/screenshots/test.links.txt"),
            run_id=100 + len(captured_queries),
            saved_links=3,
            parsed_listings=3,
        )

    def fake_enforce_browser_collection_safety(**kwargs) -> None:
        safety_calls.append((kwargs["platform"], kwargs["headless"], kwargs["acknowledged_risk"]))

    monkeypatch.setattr(module, "capture_search_spike", fake_capture_search_spike)
    monkeypatch.setattr(module, "enforce_browser_collection_safety", fake_enforce_browser_collection_safety)
    monkeypatch.setattr(module, "safety_delay", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "build_run_summary", lambda _config, run_id, options=None: {"run_id": run_id})
    monkeypatch.setattr(
        module,
        "build_candidate_pool",
        lambda _config, run_ids, options=None: {"run_ids": run_ids, "candidate_count": 0},
    )
    monkeypatch.setattr(
        module,
        "attach_run",
        lambda _config, task_id, run_id, role="search", notes=None: attached_runs.append((task_id, run_id, role)) or 1,
    )

    result = asyncio.run(
        run_research_loop(
            config,
            "MacBook Pro M1",
            options=ResearchLoopOptions(
                city="Shanghai",
                platforms=["xianyu"],
                max_searches=1,
                execute_search=True,
                acknowledged_risk=True,
                task_id=7,
            ),
        )
    )

    assert result["mode"] == "execute"
    assert result["browser_access"] == "started"
    assert result["executed_run_ids"] == [101]
    assert result["run_summaries"] == [{"run_id": 101}]
    assert result["candidate_pool"] == {"run_ids": [101], "candidate_count": 0}
    assert result["loop_assessment"]["status"] == "needs_model_decision"
    assert "no_listings" in result["loop_assessment"]["quality_flags"]
    assert captured_queries == ["MacBook Pro M1"]
    assert safety_calls == [("xianyu", False, True)]
    assert attached_runs == [(7, 101, "search")]
    assert "--i-understand-account-risk" in result["selected_searches"][0]["command_preview"]
