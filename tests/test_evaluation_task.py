from __future__ import annotations

from shopping_agent.evaluation_task import (
    EvaluationTaskOptions,
    _external_reference_plan,
    _local_reference_tools,
    _output_requirements,
    _report_delivery,
    render_evaluation_prompt,
)


def test_render_evaluation_prompt_requires_reference_research() -> None:
    task = {
        "task_type": "llm_shopping_evaluation",
        "current_date": "2026-06-17",
        "goal": "找 2019 iMac 27 寸",
        "target": {"type": "listing", "listing_id": 1},
        "instructions": ["Search official specs and current market evidence before final judgment."],
        "reference_research_requirements": [{"name": "official_or_trusted_specs"}],
        "local_reference_tools": {
            "market_baseline_command": "python -m shopping_agent.cli market-baseline --run-id 1 --pretty",
            "reference_add_command_template": "python -m shopping_agent.cli reference-add ...",
            "reference_list_command": "python -m shopping_agent.cli reference-list --run-id 1 --pretty",
        },
        "external_reference_plan": {"market_price_baselines": []},
        "output_requirements": {"format": "markdown"},
        "run_summary": None,
        "evidence_bundles": [{"listing_id": 1, "price_text": "¥3550"}],
    }

    prompt = render_evaluation_prompt(task)

    assert "必须查询官方/可信规格和当前市场样本" in prompt
    assert "官方" in prompt
    assert "当前市场样本" in prompt
    assert "用户需要手动问卖家的问题" in prompt
    assert "横向对比总表" in prompt
    assert "save-html-report" in prompt
    assert "market_baseline_command" in prompt
    assert "reference_add_command_template" in prompt
    assert "reference_list_command" in prompt
    assert "external_reference_plan" in prompt
    assert '"listing_id": 1' in prompt


def test_evaluation_task_options_defaults_are_conservative() -> None:
    options = EvaluationTaskOptions(goal="找 iMac")

    assert options.goal == "找 iMac"
    assert options.max_listings == 3
    assert options.candidate_listing_limit == 20
    assert options.evidence_ocr_chars == 1200


def test_output_requirements_include_decision_table_contract() -> None:
    requirements = _output_requirements()
    contract = requirements["comparison_table_contract"]

    assert "候选来源" in contract["required_rows"]
    assert "商品链接" in contract["required_rows"]
    assert "CPU 相对性能" in contract["required_rows"]
    assert "建议出价" in contract["required_rows"]
    assert any(item["row"] == "电池健康/循环" for item in contract["conditional_rows"])
    assert any("删除所有候选完全相同" in item for item in contract["row_selection_policy"])
    assert any("手机端手动加入" in item for item in contract["row_selection_policy"])
    assert any("shortlist 必须来自总表候选池" in item for item in contract["shortlist_policy"])


def test_report_delivery_commands_target_ready_listing() -> None:
    delivery = _report_delivery(
        options=EvaluationTaskOptions(goal="我想找一台 MacBook Pro，M1"),
        target={"type": "listing", "listing_id": 11},
    )

    assert "report-template" in delivery["report_template_command"]
    assert "--format html" in delivery["report_template_command"]
    assert "--listing-id 11" in delivery["report_template_command"]
    assert ' --goal "我想找一台 MacBook Pro，M1"' in delivery["save_html_report_command_template"]
    assert "--listing-id 11" in delivery["save_html_report_command_template"]
    assert "save-html-report" in delivery["save_html_report_command_template"]
    assert delivery["final_artifact"] == "Chinese HTML report saved under data/reports/"
    assert any("body fragment" in item for item in delivery["requirements"])


def test_local_reference_tools_expose_market_baseline_for_run() -> None:
    tools = _local_reference_tools(
        options=EvaluationTaskOptions(goal="MacBook Pro 14寸 32G"),
        target={"type": "run", "run_id": 33},
    )

    assert "market-baseline" in tools["market_baseline_command"]
    assert "--run-id 33" in tools["market_baseline_command"]
    assert ' --goal "MacBook Pro 14寸 32G"' in tools["market_baseline_command"]
    assert "same-platform local price evidence" in tools["note"]
    assert "price_evidence_level" in tools["expected_output_fields"]
    assert "sample_policy.exclusion_summary" in tools["expected_output_fields"]
    assert any("sample thickness" in item for item in tools["usage_policy"])
    assert "reference-add" in tools["reference_add_command_template"]
    assert "reference-list" in tools["reference_list_command"]
    assert "--run-id 33" in tools["reference_list_command"]
    assert any("evidence memory only" in item for item in tools["reference_ledger_policy"])


def test_local_reference_tools_listing_only_has_no_market_baseline_command() -> None:
    tools = _local_reference_tools(
        options=EvaluationTaskOptions(goal="MacBook Pro"),
        target={"type": "listing", "listing_id": 11},
    )

    assert tools["market_baseline_command"] is None
    assert "reference-add" in tools["reference_add_command_template"]
    assert "reference-list" in tools["reference_list_command"]
    assert "--listing-id 11" in tools["reference_list_command"]
    assert tools["expected_output_fields"] == []


def test_external_reference_plan_scopes_taobao_and_jd_as_price_baselines() -> None:
    plan = _external_reference_plan(
        options=EvaluationTaskOptions(goal="找 2019 年 27 寸 iMac"),
        target={"type": "run", "run_id": 12},
    )

    assert plan["platform_strategy_source"] == "docs/platform-spike.md"
    platforms = {item["platform"]: item for item in plan["market_price_baselines"]}
    assert platforms["taobao"]["role"] == "merchant/new/refurbished price baseline"
    assert "Do not assume Taobao or Taobao Union API access" in platforms["taobao"]["method"]
    assert platforms["jd"]["role"] == "new/merchant price baseline"
    assert "jd.union.open.goods.query" in platforms["jd"]["method"]
    assert platforms["xianyu"]["role"] == "same-platform local secondhand baseline"
    assert "market-baseline.price_evidence_level" in platforms["xianyu"]["evidence_level"]
    assert any("Taobao/JD mostly as price anchors" in item for item in plan["source_quality_policy"])
