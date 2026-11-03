from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from shopping_agent.config import AppConfig
from shopping_agent.evidence import build_listing_evidence, evidence_bundle_to_dict
from shopping_agent.prepare_evidence import _compact_evidence_bundle, _ready_listing_ids
from shopping_agent.run_summary import RunSummaryOptions, build_run_summary


@dataclass
class EvaluationTaskOptions:
    goal: str | None = None
    evidence_ocr_chars: int = 1200
    max_listings: int = 3
    candidate_listing_limit: int = 20
    current_date: str = field(default_factory=lambda: date.today().isoformat())


def build_listing_evaluation_task(
    config: AppConfig,
    listing_id: int,
    options: EvaluationTaskOptions | None = None,
) -> dict:
    options = options or EvaluationTaskOptions()
    bundle = build_listing_evidence(config, listing_id=listing_id)
    compact_bundle = _compact_evidence_bundle(evidence_bundle_to_dict(bundle), options.evidence_ocr_chars)
    return _task_payload(
        options=options,
        target={"type": "listing", "listing_id": listing_id},
        evidence_bundles=[compact_bundle],
        run_summary=None,
    )


def build_run_evaluation_task(
    config: AppConfig,
    run_id: int,
    options: EvaluationTaskOptions | None = None,
) -> dict:
    options = options or EvaluationTaskOptions()
    summary = build_run_summary(
        config,
        run_id=run_id,
        options=RunSummaryOptions(
            listing_limit=max(options.candidate_listing_limit, options.max_listings, 1),
        ),
    )
    listing_ids = _ready_listing_ids(summary, limit=options.max_listings)
    evidence_bundles = []
    for listing_id in listing_ids:
        try:
            bundle = build_listing_evidence(config, listing_id=listing_id)
        except ValueError:
            continue
        evidence_bundles.append(
            _compact_evidence_bundle(evidence_bundle_to_dict(bundle), options.evidence_ocr_chars)
        )
    return _task_payload(
        options=options,
        target={"type": "run", "run_id": run_id, "ready_listing_ids": listing_ids},
        evidence_bundles=evidence_bundles,
        run_summary=summary,
    )


def render_evaluation_prompt(task: dict) -> str:
    task_json = json.dumps(task, ensure_ascii=False, indent=2)
    return f"""你是二手购物研究助手的大模型大脑。请基于本地工具采集到的证据，完成中文购买决策分析。

任务日期：{task["current_date"]}
用户目标：{task.get("goal") or "(not provided)"}
评估对象：{task["target"]}

核心规则：
- 你负责最终判断；本地 Python 工具只负责搜索、截图、下载、OCR、结构化证据。
- 不要把 evidence flags 当成最终结论，它们只是提示你检查的证据线索。
- 不要把 seller_signals 当成卖家类型结论，它们只是工具抽取的卖家相关证据。
- 不要编造官方规格、市场价格、成交价、卖家事实。
- 做价格或风险判断前，必须查询官方/可信规格和当前市场样本。
- 如果评估任务 JSON 提供 `local_reference_tools.market_baseline_command`，先运行它查看本地已采集候选的同平台价格基准；这只是本地证据，不替代外部市场检索。
- 按评估任务 JSON 中的 `external_reference_plan` 使用淘宝、京东等平台作为价格基准来源；不要把这些来源误当成个人二手候选主来源。
- 当前平台真实挂牌、近期成交/挂牌样本优先于旧文章或软文。
- 引用来源 URL，并说明来源质量、样本数量、检查日期和离群样本处理。
- 证据不足时，明确写“待确认”，并列出用户需要手动问卖家的问题。
- 禁止发消息、下单、议价、付款、修改账号设置。

必须做的外部/参考调研：
1. 根据标题、描述、详情页、OCR 识别，判断候选商品可能是什么型号。
2. 查询该型号/配置的官方或可信规格。
3. 查询当前二手市场可比样本，包括平台、检查日期、样本数量、价格范围、明显离群样本。
4. 对比卖家文字、图片 OCR、官方规格之间是否一致。
5. 基于详情页、seller_signals、必要时的卖家主页证据，判断卖家类型倾向、置信度和购买影响。
6. 在完成上述调研后，再判断价格、风险和建议出价。

输出要求：
1. 使用中文。
2. 如果要生成用户可读报告，优先输出 HTML；如果只能输出 Markdown，也必须用横向对比表。
3. 第一屏必须是购买决策用的横向对比总表：第一列是“对比项”，后续列是候选商品；必须包含“商品链接”一行。
4. 表格优先展示用户真正关心的差异：年份、CPU、CPU 相对性能、显卡、内存、硬盘、所在地/自提、到手总成本、关键风险、建议出价、当前动作。
5. 对没有信息增益的行不要机械保留。例如所有候选显卡完全一致时，不要再单独写一行“显卡性能相对 165%/165%/165%”。
6. 最好值、最强性能、最低总成本、最高风险点要加粗或突出。
7. 多候选时，除了总表，还要给一个“推荐 shortlist 表”：高性价比、低风险/高质量、低预算、值得补证据。
8. 不要把工具命令、采集流水、内部状态堆到用户报告正文里；这些只作为证据来源或附录。
9. 如果候选太少或搜索词明显不足，先指出需要继续扩展搜索，而不是强行给最终结论。
10. 严格参考评估任务 JSON 中的 `output_requirements.comparison_table_contract`，缺信息写“待确认”，不要为了填表而编造参数或价格。

报告交付：
- 完成评估后，生成中文 HTML 购买决策报告，并调用 `save-html-report` 保存到 `data/reports/`。
- 可以先用 `report-template` 查看核心章节，但最终 HTML 报告第一屏必须是横向对比总表。
- 如果证据不足以写最终推荐，也要保存一份阶段性 HTML 报告，明确缺什么证据和下一步动作。

评估任务 JSON：
```json
{task_json}
```
"""


def _task_payload(
    options: EvaluationTaskOptions,
    target: dict,
    evidence_bundles: list[dict],
    run_summary: dict | None,
) -> dict:
    return {
        "task_type": "llm_shopping_evaluation",
        "current_date": options.current_date,
        "goal": options.goal,
        "target": target,
        "instructions": _instructions(),
        "reference_research_requirements": _reference_research_requirements(),
        "local_reference_tools": _local_reference_tools(options=options, target=target),
        "external_reference_plan": _external_reference_plan(options=options, target=target),
        "output_requirements": _output_requirements(),
        "report_delivery": _report_delivery(options=options, target=target),
        "run_summary": run_summary,
        "evidence_bundles": evidence_bundles,
    }


def _instructions() -> list[str]:
    return [
        "大模型负责商品识别、风险判断、价格判断、搜索扩展和最终推荐；本地 flags 只是证据信号。",
        "seller_signals 只是卖家相关证据，不是个人/商家最终判断；卖家类型倾向、置信度和购买影响必须由大模型判断。",
        "最终判断前必须查询官方规格和当前市场样本。",
        "如果任务提供 market-baseline 命令，先用它查看本地候选价格基准，但不要把它当作唯一市场证据。",
        "按 external_reference_plan 收集外部价格证据；淘宝/京东默认是价格基准，不是二手候选主来源。",
        "不要用旧文章或单一弱来源推断价格。",
        "官方规格和市场样本必须给 URL。",
        "证据不足时明确写待确认，并说明下一步应该补抓什么证据。",
        "输出面向用户的中文购买决策报告，优先横向对比表和 shortlist。",
        "禁止发消息、下单、议价、付款、修改账号设置。",
    ]


def _reference_research_requirements() -> list[dict]:
    return [
        {
            "name": "official_or_trusted_specs",
            "required": True,
            "examples": ["manufacturer specs", "EveryMac/Mactracker-style product database"],
        },
        {
            "name": "current_market_samples",
            "required": True,
            "examples": ["same-platform current listings", "recent sold listings when available", "adjacent-platform comparable listings"],
        },
        {
            "name": "source_quality_notes",
            "required": True,
            "examples": ["sample count", "date checked", "platform", "outliers excluded", "why weak sources were downweighted"],
        },
    ]


def _local_reference_tools(options: EvaluationTaskOptions, target: dict) -> dict:
    reference_tools = _reference_evidence_tools(options=options, target=target)
    if target.get("type") == "run" and target.get("run_id") is not None:
        command = [
            "python",
            "-m",
            "shopping_agent.cli",
            "market-baseline",
            "--run-id",
            str(target["run_id"]),
        ]
        if options.goal:
            command.extend(["--goal", _quote_arg(options.goal)])
        command.append("--pretty")
        return {
            "market_baseline_command": " ".join(command),
            **reference_tools,
            "scope": "local collected candidates for this run",
            "note": "Use this as same-platform local price evidence. The model must still search official specs and current external market samples before final price judgment.",
            "expected_output_fields": [
                "price_evidence_level",
                "sample_policy.exclusion_summary",
                "overall.price_summary",
                "overall.price_evidence_level",
                "spec_price_groups[].price_evidence_level",
                "spec_price_groups[].price_summary",
            ],
            "usage_policy": [
                "Use price_evidence_level to judge local sample thickness, not final market value.",
                "Read sample_policy.exclusion_summary before deciding whether the local baseline excluded important outliers or only obvious noise.",
                "Compare spec_price_groups only after checking model, screen size, chip/CPU, memory, storage, condition, and seller context.",
            ],
        }
    return {
        "market_baseline_command": None,
        **reference_tools,
        "scope": "not available for listing-only evaluation without a run id",
        "note": "Use official specs and current external market samples; if possible, evaluate a run to get local candidate price context.",
        "expected_output_fields": [],
        "usage_policy": [
            "Do not infer a local same-platform price baseline from one listing-only evidence bundle.",
        ],
    }


def _reference_evidence_tools(options: EvaluationTaskOptions, target: dict) -> dict:
    base_args = _target_cli_args(target)
    if options.goal:
        base_args.extend(["--goal", _quote_arg(options.goal)])
    list_command = [
        "python",
        "-m",
        "shopping_agent.cli",
        "reference-list",
        *base_args,
        "--pretty",
    ]
    add_template = [
        "python",
        "-m",
        "shopping_agent.cli",
        "reference-add",
        *base_args,
        "--source-type",
        "<official_specs|trusted_specs|current_listing|sold_history|merchant_refurbished|article_or_forum>",
        "--platform",
        "<platform-or-source>",
        "--title",
        _quote_arg("<reference title>"),
        "--url",
        _quote_arg("<reference URL>"),
        "--price-text",
        _quote_arg("<optional observed price text>"),
        "--spec-summary",
        _quote_arg("<optional spec or identity summary>"),
        "--comparable-scope",
        _quote_arg("<why comparable or not>"),
        "--notes",
        _quote_arg("<source quality, sample count, limitations, excluded outliers>"),
    ]
    return {
        "reference_add_command_template": " ".join(add_template),
        "reference_list_command": " ".join(list_command),
        "reference_ledger_policy": [
            "After checking official specs, current listings, sold/history evidence, merchant/refurbished listings, or background articles, save useful sources with reference-add.",
            "Use reference-list before writing the final report to inspect source type counts, evidence levels, and price summaries.",
            "The reference ledger is evidence memory only; it does not make the final price, risk, seller, or recommendation judgment.",
        ],
    }


def _external_reference_plan(options: EvaluationTaskOptions, target: dict) -> dict:
    goal = options.goal or ""
    generic_goal = goal or "the target product/model from the evidence bundle"
    return {
        "decision_owner": "llm",
        "is_final_recommendation": False,
        "platform_strategy_source": "docs/platform-spike.md",
        "current_date": options.current_date,
        "goal": goal,
        "purpose": "Guide the model to collect current specs and market price evidence without assuming unavailable platform APIs.",
        "official_specs": {
            "required": True,
            "instructions": [
                "Identify the product family, model year, size, chip/CPU, memory, storage, GPU, and region assumptions from local evidence first.",
                "Search manufacturer specs and trusted product databases before judging configuration authenticity or performance.",
                "Cite URLs and record the date checked.",
            ],
            "query_templates": [
                f"{generic_goal} 官方规格",
                f"{generic_goal} technical specifications",
                f"{generic_goal} EveryMac specs",
            ],
        },
        "market_price_baselines": [
            {
                "platform": "xianyu",
                "role": "same-platform local secondhand baseline",
                "method": "Use local candidate pools and market-baseline when a run id is available.",
                "evidence_level": "Read market-baseline.price_evidence_level. A_local_active_* means current local active/listing snapshots with different sample thickness; it is weaker before detail/OCR verification.",
                "limitations": [
                    "挂牌价不等于成交价。",
                    "卖家风险、成色、维修、配置差异会强烈影响可比性。",
                ],
            },
            {
                "platform": "taobao",
                "role": "merchant/new/refurbished price baseline",
                "method": "Use web/search entry points or user-authorized browser evidence. Do not assume Taobao or Taobao Union API access.",
                "evidence_level": "C unless samples are current, comparable, and clearly merchant/refurbished listings.",
                "query_templates": [
                    f"淘宝 {generic_goal}",
                    f"淘宝 二手 {generic_goal}",
                    f"淘宝 翻新 {generic_goal}",
                ],
                "limitations": [
                    "当前项目未确认淘宝 API 可作为普通买家全站搜索主路径。",
                    "淘宝样本通常不是个人二手卖家，不能直接替代闲鱼同类样本。",
                    "低价文章、软文和陈旧报价只能作为背景，不能单独定价。",
                ],
            },
            {
                "platform": "jd",
                "role": "new/merchant price baseline",
                "method": "Use web/search entry points first. JD Union APIs such as jd.union.open.goods.query may be evaluated later only with proper credentials.",
                "evidence_level": "C for merchant listings; stronger only when model/configuration and current date are clearly comparable.",
                "query_templates": [
                    f"京东 {generic_goal}",
                    f"京东 二手 {generic_goal}",
                    f"京东 95新 {generic_goal}",
                ],
                "limitations": [
                    "京东联盟商品查询偏推广/商品池，不是二手交易市场。",
                    "新品或商家样本可以作为价格上沿或替代方案参考，不能直接代表个人二手成交价。",
                ],
            },
            {
                "platform": "zhuanzhuan",
                "role": "optional supplemental secondhand channel",
                "method": "Use only search/web spike routes until a stable official product-search API is documented.",
                "evidence_level": "B/C depending on whether listing details and platform verification are visible.",
                "query_templates": [
                    f"转转 {generic_goal}",
                    f"转转 二手 {generic_goal}",
                ],
                "limitations": [
                    "当前没有确认可用的官方开放 API。",
                    "优先级低于闲鱼，适合作为补充样本。",
                ],
            },
        ],
        "source_quality_policy": [
            "Prefer current comparable listings and recent sold/history evidence when available.",
            "Record sample count, platform, date checked, comparable specs, excluded outliers, and why each source is comparable or not.",
            "Do not mix different screen sizes, storage sizes, chip classes, battery/condition levels, or seller types into one price band without labeling the differences.",
            "Use Taobao/JD mostly as price anchors or replacement/new/refurbished context; use Xianyu/local candidate evidence for secondhand purchase ranking.",
        ],
        "stop_conditions": [
            "If external evidence is thin or contradictory, write a staged report with missing evidence instead of a final price conclusion.",
            "If a platform requires login, captcha, or unavailable API permission, stop and document the limitation rather than bypassing it.",
        ],
    }


def _output_requirements() -> dict:
    return {
        "format": "html_preferred_or_markdown",
        "sections": [
            "横向对比总表",
            "推荐 shortlist 表",
            "一句话结论",
            "价格判断和来源质量",
            "关键风险和证据",
            "卖家类型倾向、置信度和购买影响",
            "建议出价和下一步动作",
            "需要用户手动问卖家的问题",
            "证据来源",
        ],
        "comparison_table_contract": _comparison_table_contract(),
        "extension_policy": "核心是帮助用户买不买、买哪台、多少钱出价。可增加商品专属检查项，但不要写成学术报告或工具运行日志。",
    }


def _comparison_table_contract() -> dict:
    return {
        "layout": "第一列固定为“对比项”，后续每列是一台候选商品；候选列标题使用短标签，例如“闲鱼 72 / 上海 2019 iMac”或“闲鱼 217 / M1 Pro 32G”。",
        "required_rows": [
            "候选来源",
            "商品链接",
            "一句话定位",
            "年份/型号",
            "CPU",
            "CPU 相对性能",
            "显卡/图形",
            "内存",
            "硬盘",
            "屏幕/尺寸",
            "所在地/交易方式",
            "到手总成本",
            "卖家类型倾向",
            "关键优点",
            "关键风险",
            "建议出价",
            "当前动作",
        ],
        "conditional_rows": [
            {
                "row": "GPU 相对性能",
                "include_when": "不同候选 GPU 有明显差异，或 GPU 会影响用户主要用途。",
            },
            {
                "row": "电池健康/循环",
                "include_when": "评估 MacBook、iPad、手机等带电池设备。",
            },
            {
                "row": "原装/拆修疑点",
                "include_when": "证据显示配置、序列、硬盘、屏幕、外壳或卖家描述可能不一致。",
            },
            {
                "row": "配件/保修/验货",
                "include_when": "配件、保修、验货宝、发票或自提条件会影响总成本或风险。",
            },
        ],
        "row_selection_policy": [
            "保留能影响购买决策的差异行；删除所有候选完全相同且没有风险含义的重复性能行。",
            "性能行必须给基准和相对差异，例如“约 5200（基准）/ 约 8200（强 58%）”，没有可靠来源时写“待确认”。",
            "价格行要写到手总成本，不只写挂牌价；包含运费、验货、必要升级或维修预估时要注明。",
            "风险行要写证据和影响，不要只写抽象标签。",
            "来源行必须区分网页搜索、手机端手动加入或其他来源；不要把手机端推荐流发现的候选伪装成网页搜索结果。",
            "最优值、最低总成本、最高风险和最值得继续追的候选必须用加粗或 CSS 类突出。",
        ],
        "shortlist_policy": [
            "总表之后给 2-4 个 shortlist 结论：高性价比、低风险/高质量、低预算、值得补证据。",
            "shortlist 必须来自总表候选池；不要引入没有证据的新商品。",
            "如果证据不足以推荐，shortlist 应写“暂不推荐下单”，并说明下一步要补什么证据。",
        ],
    }


def _report_delivery(options: EvaluationTaskOptions, target: dict) -> dict:
    title = "二手购买决策报告"
    target_args = _target_cli_args(target)
    goal_args = ["--goal", _quote_arg(options.goal)] if options.goal else []
    return {
        "final_artifact": "Chinese HTML report saved under data/reports/",
        "report_template_command": " ".join(
            [
                "python",
                "-m",
                "shopping_agent.cli",
                "report-template",
                "--title",
                _quote_arg(title),
                "--format",
                "html",
                *goal_args,
                *target_args,
            ]
        ),
        "save_html_report_command_template": " ".join(
            [
                "python",
                "-m",
                "shopping_agent.cli",
                "save-html-report",
                "--input",
                "data\\reports\\draft.html",
                "--title",
                _quote_arg(title),
                *goal_args,
                *target_args,
            ]
        ),
        "requirements": [
            "Write the report in Chinese HTML unless the user explicitly asks otherwise.",
            "Start with a horizontal comparison table for purchase decisions.",
            "Do not put internal command logs in the user-facing report body.",
            "If evidence is insufficient, save a staged report that says what to collect next.",
            "save-html-report accepts a full HTML document or an HTML body fragment; body fragments will be wrapped in the project default Chinese report shell.",
        ],
    }


def _target_cli_args(target: dict) -> list[str]:
    if target.get("type") == "listing" and target.get("listing_id") is not None:
        return ["--listing-id", str(target["listing_id"])]
    if target.get("type") == "run" and target.get("run_id") is not None:
        return ["--run-id", str(target["run_id"])]
    return []


def _quote_arg(value: str | None) -> str:
    text = str(value or "")
    if not text or any(char.isspace() for char in text) or '"' in text:
        return '"' + text.replace('"', '\\"') + '"'
    return text
