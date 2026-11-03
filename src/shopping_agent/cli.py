from __future__ import annotations

from shopping_agent.region_preference import region_preference

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console

from shopping_agent.analysis import analyze_downloaded_images
from shopping_agent.browser.session import BrowserSession, SearchFilters, SearchSnapshot
from shopping_agent.candidate_context import build_candidate_evidence, build_candidate_index
from shopping_agent.candidate_pool import CandidatePoolOptions, build_candidate_pool
from shopping_agent.config import AppConfig, ensure_runtime_dirs, load_config
from shopping_agent.codex_launcher import (
    build_codex_launch_plan,
    format_command,
    format_interactive_launch_hint,
    launch_codex,
    write_prompt_file,
)
from shopping_agent.detail import (
    capture_detail_url,
    get_listing_urls_for_run,
    listing_url_belongs_to_run,
    wait_between_detail_pages,
)
from shopping_agent.detail_candidates import DetailCandidateOptions, build_detail_candidates
from shopping_agent.db import initialize
from shopping_agent.db import add_saved_report, connect, fetch_latest_detail_snapshot_for_listing
from shopping_agent.doctor import run_doctor
from shopping_agent.evidence import build_listing_evidence, evidence_bundle_to_dict
from shopping_agent.evaluation_task import (
    EvaluationTaskOptions,
    build_listing_evaluation_task,
    build_run_evaluation_task,
    render_evaluation_prompt,
)
from shopping_agent.goal_plan import GoalPlanOptions, build_goal_plan
from shopping_agent.history import (
    _safe_console_text,
    print_recent_history,
    print_run_detail,
    print_run_details,
    print_run_listings,
)
from shopping_agent.listing_analysis import analyze_listing
from shopping_agent.market_baseline import MarketBaselineOptions, build_market_baseline
from shopping_agent.media import cleanup_legacy_media, download_pending_media, list_media_assets
from shopping_agent.prepare_evidence import prepare_run_evidence_sync
from shopping_agent.platforms.xianyu_detail_parser import parse_xianyu_recommendation_links
from shopping_agent.reference_evidence import (
    ReferenceEvidenceInput,
    SOURCE_TYPE_CHOICES,
    build_reference_evidence_summary,
    save_reference_evidence,
)
from shopping_agent.reports.html import render_html_report_template, save_html_report
from shopping_agent.reports.markdown import ReportMetadata, render_report_template, save_markdown_report
from shopping_agent.decision_report import DecisionReportOptions, build_decision_report, render_decision_report_markdown
from shopping_agent.decision_report import backfill_seller_fields_from_detail_text
from shopping_agent.candidate_query import CandidateQueryOptions, query_candidates
from shopping_agent.run_comparison import RunComparisonOptions, build_run_comparison
from shopping_agent.run_diff import build_run_diff
from shopping_agent.research_loop import (
    ResearchLoopOptions,
    build_foldback_adoption,
    run_research_loop,
)
from shopping_agent.run_summary import RunSummaryOptions, build_run_summary
from shopping_agent.safety import SafetyError, enforce_browser_collection_safety
from shopping_agent.spike import SearchSpikeResult, SearchSpikeSafetyError, capture_search_spike
from shopping_agent.tasks import (
    attach_run,
    build_task_summary,
    create_task,
    export_task,
    print_recent_tasks,
    print_task_summary,
    update_task_preferences,
)

console = Console()


def _print_text(value: str) -> None:
    sys.stdout.buffer.write(value.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


def _resolve_detail_capture_metadata(
    *,
    url: str | None,
    run_id: int | None,
    source_type: str | None,
    source_label: str | None,
    url_belongs_to_run: bool,
) -> tuple[str, str, str]:
    is_new_manual_seed = bool(url) and run_id is None
    is_manual_source = bool(url) and not url_belongs_to_run
    if is_manual_source:
        resolved_source_type = "mobile_manual"
        resolved_source_label = "手机端手动加入"
    else:
        resolved_source_type = source_type or "web_search"
        resolved_source_label = source_label or (
            "手机端手动加入" if resolved_source_type == "mobile_manual" else "网页搜索"
        )
    attachment_role = "manual_seed" if is_new_manual_seed else "detail_capture"
    return resolved_source_type, resolved_source_label, attachment_role


def _load_prior_foldback(path):
    """Load a prior foldback adoption verdict from a JSON file path.

    Accepts the JSON produced by foldback-adopt (optionally with a UTF-8 BOM,
    as PowerShell Out-File adds one) and returns it as a dict so it can be
    threaded through ResearchLoopOptions.prior_foldback into the next
    subagent prompt. Returns None when no path is given.
    """
    if not path:
        return None
    raw = Path(path).read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("Prior foldback file " + path + " did not contain a JSON object.")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shopping-agent",
        description="Local semi-automated shopping and secondhand price research agent.",
    )
    parser.add_argument(
        "--config",
        default="config/default.toml",
        help="Path to TOML config file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the local SQLite database.")

    doctor = subparsers.add_parser("doctor", help="Check local runtime requirements.")
    doctor.add_argument(
        "--skip-browser",
        action="store_true",
        help="Skip Playwright browser launch check.",
    )

    research = subparsers.add_parser("research", help="Start a shopping research run.")
    research.add_argument("goal", help="Natural-language purchase goal.")
    research.add_argument("--city", default=None, help="Override default city.")
    research.add_argument("--platform", action="append", help="Limit to one or more platforms.")
    research.add_argument("--codex-bin", default="codex", help="Codex executable name or path.")
    research.add_argument(
        "--codex-arg",
        action="append",
        default=[],
        help=(
            "Extra argument forwarded to the launched Codex process. "
            "Repeat for arguments with values, for example --codex-arg=-a --codex-arg=never."
        ),
    )
    research.add_argument("--no-search", action="store_true", help="Do not pass --search to Codex.")
    research.add_argument("--run", action="store_true", help="Actually launch Codex. Default is dry-run.")

    goal_plan = subparsers.add_parser(
        "goal-plan",
        help="Build a model-facing search and requirement-calibration plan from a fuzzy shopping goal.",
    )
    goal_plan.add_argument("goal", help="Natural-language purchase goal.")
    goal_plan.add_argument("--city", default=None, help="Override default city.")
    goal_plan.add_argument("--platform", action="append", help="Limit to one or more platforms.")
    goal_plan.add_argument(
        "--clarify-via-codex",
        action="store_true",
        help="Attach a clarification_request for fuzzy goals: a Codex prompt and command preview that can refine product identity and questions using model knowledge. Advisory only; does not launch Codex.",
    )
    goal_plan.add_argument(
        "--expand-similar-via-codex",
        action="store_true",
        help="Attach a similar_product_request: a Codex prompt that expands adjacent/similar products (e.g. M1 -> M2, tier variants) using model knowledge. Leave off when the user only wants the exact model, e.g. a spare-part or accessory buy. Advisory only; does not launch Codex.",
    )
    goal_plan.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    research_loop = subparsers.add_parser(
        "research-loop",
        help="Build or execute the first search loop for a fuzzy shopping goal.",
    )
    research_loop.add_argument("goal", help="Natural-language purchase goal.")
    research_loop.add_argument("--city", default=None, help="Override default city.")
    research_loop.add_argument("--platform", action="append", help="Limit to one or more platforms.")
    research_loop.add_argument("--max-searches", type=int, default=2, help="Maximum planned searches to execute or preview.")
    research_loop.add_argument(
        "--execute-search",
        action="store_true",
        help="Actually open browser pages and run the selected searches. Default is dry-run.",
    )
    research_loop.add_argument("--wait-ms", type=int, default=5000, help="Milliseconds to wait after page load.")
    research_loop.add_argument("--headless", action="store_true", help="Run browser without visible window.")
    research_loop.add_argument("--scroll-steps", type=int, default=0, help="Deprecated: DOM scroll fallback only. Prefer --max-pages for API pagination (structured listings, no scroll).")
    research_loop.add_argument("--scroll-wait-ms", type=int, default=900, help="Deprecated: paired with --scroll-steps DOM fallback.")
    research_loop.add_argument("--listing-limit", type=int, default=20, help="Maximum listings per run summary.")
    research_loop.add_argument("--candidate-limit", type=int, default=600, help="Maximum merged candidates.")
    research_loop.add_argument("--shortlist-limit", type=int, default=12, help="Maximum next-evidence shortlist candidates.")
    research_loop.add_argument("--max-pages", type=int, default=1, help="Number of result pages to capture per xianyu search via API pagination (each page ~30 items).")
    research_loop.add_argument(
        "--i-understand-account-risk",
        action="store_true",
        help="Required when executing browser automation on platforms with account-risk concerns.",
    )
    research_loop.add_argument(
        "--clarify-via-codex",
        action="store_true",
        help="Attach a clarification_request to goal_plan for fuzzy goals: a Codex prompt and command preview that can refine product identity and questions using model knowledge. Advisory only; does not launch Codex.",
    )
    research_loop.add_argument(
        "--expand-similar-via-codex",
        action="store_true",
        help="Attach a similar_product_request to goal_plan: a Codex prompt that expands adjacent/similar products using model knowledge. Leave off when the user only wants the exact model. Advisory only; does not launch Codex.",
    )
    research_loop.add_argument(
        "--next-search-via-codex",
        action="store_true",
        help="Attach a next_search_request to loop_assessment: a Codex prompt that dynamically proposes next-round search terms from real run results. Advisory only; does not launch Codex.",
    )
    research_loop.add_argument(
        "--prior-foldback",
        default=None,
        help="Path to a JSON file with a previous foldback adoption verdict (from foldback-adopt). Its rejected verdict is rendered into the next_search_request prompt so the next subagent pass avoids the same failing term.",
    )
    research_loop.add_argument("--task-id", type=int, default=None, help="Attach executed runs to a research task.")
    research_loop.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    login = subparsers.add_parser("login", help="Open a persistent browser profile for login.")
    login.add_argument("platform", help="Platform to log into, for example xianyu.")

    spike = subparsers.add_parser("spike-search", help="Capture a raw search page snapshot.")
    spike.add_argument("platform", help="Platform to inspect, for example xianyu.")
    spike.add_argument("query", help="Search query to open.")
    spike.add_argument(
        "--wait-ms",
        type=int,
        default=5000,
        help="Milliseconds to wait after initial page load.",
    )
    spike.add_argument("--min-price", type=int, default=None, help="Minimum price filter to apply on supported platforms.")
    spike.add_argument("--max-price", type=int, default=None, help="Maximum price filter to apply on supported platforms.")
    spike.add_argument("--area", default=None, help="Area/city filter to try on supported platforms, for example Shanghai.")
    spike.add_argument(
        "--sort",
        choices=["newest", "price_asc", "price_desc"],
        default=None,
        help="Sort order to try on supported platforms.",
    )
    spike.add_argument(
        "--scroll-steps",
        type=int,
        default=0,
        help="Deprecated: DOM scroll fallback only. Prefer --max-pages for API pagination (structured listings, no scroll).",
    )
    spike.add_argument(
        "--scroll-wait-ms",
        type=int,
        default=900,
        help="Deprecated: paired with --scroll-steps DOM fallback.",
    )
    spike.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Number of result pages to capture per xianyu search via API pagination (each page ~30 items).",
    )
    spike.add_argument(
        "--headless",
        action="store_true",
        help="Run browser without opening a visible window.",
    )
    spike.add_argument(
        "--i-understand-account-risk",
        action="store_true",
        help="Required for browser automation on platforms with account-risk concerns.",
    )
    spike.add_argument("--task-id", type=int, default=None, help="Attach the created run to a research task.")

    detail = subparsers.add_parser("capture-detail", help="Capture listing detail pages.")
    detail.add_argument("--url", default=None, help="Single detail URL to capture (optionally with --run-id).")
    detail.add_argument("--run-id", type=int, default=None, help="Run to capture under, or capture URLs from.")
    detail.add_argument("--platform", default="xianyu", help="Platform name.")
    detail.add_argument("--limit", type=int, default=3, help="Maximum URLs to capture from --run-id.")
    detail.add_argument("--wait-ms", type=int, default=5000, help="Milliseconds to wait after page load.")
    detail.add_argument("--headless", action="store_true", help="Run browser without visible window.")
    detail.add_argument(
        "--source-type",
        default=None,
        help=(
            "Candidate source for --url captures. Defaults to web_search only when the URL "
            "already belongs to --run-id; nonmember URLs are always mobile_manual."
        ),
    )
    detail.add_argument(
        "--source-label",
        default=None,
        help="Human-readable candidate source label, for example 手机端手动加入.",
    )
    detail.add_argument(
        "--i-understand-account-risk",
        action="store_true",
        help="Required for browser automation on platforms with account-risk concerns.",
    )
    detail.add_argument("--task-id", type=int, default=None, help="Attach captured detail run(s) to a research task.")

    media = subparsers.add_parser("download-media", help="Download pending product image URLs.")
    media.add_argument("--limit", type=int, default=10, help="Maximum pending media assets to download.")
    media_target = media.add_mutually_exclusive_group()
    media_target.add_argument("--run-id", type=int, default=None, help="Limit downloads to listings from a run.")
    media_target.add_argument("--listing-id", type=int, default=None, help="Limit downloads to one listing.")
    media.add_argument(
        "--media-type",
        default="product_image_url",
        help="Media type to download. Defaults to product_image_url.",
    )

    media_list = subparsers.add_parser("media-list", help="List saved media assets.")
    media_list.add_argument("--media-type", default="product_image_url", help="Media type to list.")
    media_list.add_argument("--limit", type=int, default=50, help="Maximum rows to show.")

    analyze_images = subparsers.add_parser("analyze-images", help="Analyze downloaded product images.")
    analyze_images.add_argument("--media-type", default="product_image_url", help="Media type to analyze.")
    analyze_images.add_argument("--limit", type=int, default=20, help="Maximum images to analyze.")
    analyze_target = analyze_images.add_mutually_exclusive_group()
    analyze_target.add_argument("--run-id", type=int, default=None, help="Limit analysis to listings from a run.")
    analyze_target.add_argument("--listing-id", type=int, default=None, help="Limit analysis to one listing.")
    analyze_images.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "paddleocr", "pytesseract"],
        help="OCR backend to use.",
    )
    analyze_images.add_argument(
        "--force",
        action="store_true",
        help="Analyze already OCRed images again.",
    )

    analyze_listing_parser = subparsers.add_parser(
        "analyze-listing",
        help="Show evidence flags and temporary heuristic risks for a listing.",
    )
    analyze_listing_parser.add_argument("--listing-id", type=int, required=True, help="Listing ID to analyze.")

    build_evidence_parser = subparsers.add_parser(
        "build-evidence",
        help="Build a structured evidence bundle for a listing.",
    )
    build_evidence_parser.add_argument("--listing-id", type=int, required=True, help="Listing ID to bundle.")
    build_evidence_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    prepare_evidence = subparsers.add_parser(
        "prepare-evidence",
        help="Prepare detail pages, images, OCR, and evidence bundles for a search run.",
    )
    prepare_evidence.add_argument("--run-id", type=int, required=True, help="Run ID to prepare.")
    prepare_evidence.add_argument("--platform", default="xianyu", help="Platform name.")
    prepare_evidence.add_argument("--detail-limit", type=int, default=3, help="Maximum missing details to capture.")
    prepare_evidence.add_argument("--media-limit", type=int, default=0, help="Maximum pending images to download.")
    prepare_evidence.add_argument("--ocr-limit", type=int, default=0, help="Maximum downloaded images to OCR.")
    prepare_evidence.add_argument("--wait-ms", type=int, default=5000, help="Milliseconds to wait after page load.")
    prepare_evidence.add_argument("--headless", action="store_true", help="Run browser without visible window.")
    prepare_evidence.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "paddleocr", "pytesseract"],
        help="OCR backend to use.",
    )
    prepare_evidence.add_argument(
        "--build-evidence-limit",
        type=int,
        default=3,
        help="Maximum ready listings to include as evidence bundles.",
    )
    prepare_evidence.add_argument(
        "--evidence-ocr-chars",
        type=int,
        default=800,
        help="Maximum OCR text chars per image in embedded evidence bundles. Use -1 for full text.",
    )
    prepare_evidence.add_argument(
        "--i-understand-account-risk",
        action="store_true",
        help="Required for browser automation on platforms with account-risk concerns.",
    )
    prepare_evidence.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    evaluation_task = subparsers.add_parser(
        "evaluation-task",
        help="Build an LLM evaluation task from a listing or prepared run.",
    )
    target = evaluation_task.add_mutually_exclusive_group(required=True)
    target.add_argument("--listing-id", type=int, help="Listing ID to evaluate.")
    target.add_argument("--run-id", type=int, help="Run ID whose ready listings should be evaluated.")
    evaluation_task.add_argument("--goal", default=None, help="Original shopping goal.")
    evaluation_task.add_argument(
        "--max-listings",
        type=int,
        default=3,
        help="Maximum ready listings to include for --run-id.",
    )
    evaluation_task.add_argument(
        "--candidate-listing-limit",
        type=int,
        default=20,
        help="Maximum run-summary candidates to scan when selecting ready listings.",
    )
    evaluation_task.add_argument(
        "--evidence-ocr-chars",
        type=int,
        default=1200,
        help="Maximum OCR text chars per image in embedded evidence bundles. Use -1 for full text.",
    )
    evaluation_task.add_argument(
        "--format",
        choices=["json", "prompt"],
        default="json",
        help="Output raw task JSON or an LLM prompt.",
    )
    evaluation_task.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    codex_guide = subparsers.add_parser(
        "codex-guide",
        help="Start a Codex-guided shopping research session for this project.",
    )
    codex_guide.add_argument("--goal", default=None, help="Shopping goal to pass to Codex.")
    codex_guide.add_argument("--listing-id", type=int, default=None, help="Listing ID to evaluate.")
    codex_guide.add_argument("--city", default=None, help="Override default city for goal-mode research.")
    codex_guide.add_argument("--platform", action="append", help="Limit goal-mode research to one or more platforms.")
    codex_guide.add_argument("--codex-bin", default="codex", help="Codex executable name or path.")
    codex_guide.add_argument(
        "--codex-arg",
        action="append",
        default=[],
        help=(
            "Extra argument forwarded to the launched Codex process. "
            "Repeat for arguments with values, for example --codex-arg=-a --codex-arg=never."
        ),
    )
    codex_guide.add_argument("--no-search", action="store_true", help="Do not pass --search to Codex.")
    codex_guide.add_argument("--run", action="store_true", help="Actually launch Codex. Default is dry-run.")

    cleanup_media = subparsers.add_parser("cleanup-media", help="Delete legacy media records.")
    cleanup_media.add_argument(
        "--media-type",
        default="image_url",
        help="Media type to delete. Defaults to old generic image_url records.",
    )
    cleanup_media.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion.",
    )

    report_template = subparsers.add_parser(
        "report-template",
        help="Print a Markdown or HTML report template for LLM-written evaluation reports.",
    )
    report_template.add_argument("--title", default="Shopping Research Report", help="Report title.")
    report_template.add_argument("--goal", default=None, help="Original shopping goal.")
    report_template.add_argument("--run-id", type=int, default=None, help="Run ID for this report.")
    report_template.add_argument("--listing-id", type=int, default=None, help="Listing ID for this report.")
    report_template.add_argument(
        "--format",
        choices=["markdown", "html"],
        default="markdown",
        help="Template format to print. Defaults to markdown.",
    )
    report_template.add_argument(
        "--extra-section",
        action="append",
        default=[],
        help="Optional product-specific section to include. Can be repeated.",
    )

    save_report = subparsers.add_parser(
        "save-report",
        help="Save an LLM-written Markdown report under the reports directory.",
    )
    source = save_report.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Markdown file to save.")
    source.add_argument("--stdin", action="store_true", help="Read Markdown from stdin.")
    save_report.add_argument("--title", default="Shopping Research Report", help="Report title.")
    save_report.add_argument("--goal", default=None, help="Original shopping goal.")
    save_report.add_argument("--run-id", type=int, default=None, help="Run ID for this report.")
    save_report.add_argument("--listing-id", type=int, default=None, help="Listing ID for this report.")
    save_report.add_argument("--task-id", type=int, default=None, help="Research task ID for this report.")
    save_report.add_argument("--filename", default=None, help="Optional output filename.")

    save_html = subparsers.add_parser(
        "save-html-report",
        help="Save an LLM-written HTML report under the reports directory.",
    )
    source = save_html.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="HTML file to save.")
    source.add_argument("--stdin", action="store_true", help="Read HTML from stdin.")
    save_html.add_argument("--title", default="Shopping Research Report", help="Report title.")
    save_html.add_argument("--goal", default=None, help="Original shopping goal.")
    save_html.add_argument("--run-id", type=int, default=None, help="Run ID for this report.")
    save_html.add_argument("--listing-id", type=int, default=None, help="Listing ID for this report.")
    save_html.add_argument("--task-id", type=int, default=None, help="Research task ID for this report.")
    save_html.add_argument("--filename", default=None, help="Optional output filename.")

    decision_report_parser = subparsers.add_parser(
        "decision-report",
        help="Generate a four-section evidence report from a run without purchase judgments.",
    )
    decision_report_parser.add_argument("--run-id", type=int, required=True, help="Run ID to report on.")
    decision_report_parser.add_argument("--goal", default=None, help="Original shopping goal.")
    decision_report_parser.add_argument("--target-city", default=None, help="Target city for relevance.")
    decision_report_parser.add_argument("--max-listings", type=int, default=20, help="Max candidates in the report.")
    decision_report_parser.add_argument("--detailed-reviews", type=int, default=3, help="Number of detailed reviews.")
    decision_report_parser.add_argument("--save", action="store_true", help="Save the report to data/reports/.")
    decision_report_parser.add_argument("--pretty", action="store_true", help="Print the report dict as JSON.")

    backfill_parser = subparsers.add_parser(
        "backfill-seller-fields",
        help="Backfill structured seller columns from DOM detail text for old runs.",
    )
    backfill_parser.add_argument("--run-id", type=int, required=True, help="Run ID to backfill.")
    backfill_parser.add_argument("--pretty", action="store_true", help="Print result as JSON.")

    query_parser = subparsers.add_parser(
        "query-candidates",
        help="Narrow-query a run's candidates as session memory for interactive Q&A.",
    )
    query_parser.add_argument("--run-id", type=int, required=True, action="append", help="Run ID(s) to query. Repeatable.")
    query_parser.add_argument("--goal", default=None, help="Original shopping goal.")
    query_parser.add_argument("--min-price", type=int, default=None, help="Min price filter.")
    query_parser.add_argument("--max-price", type=int, default=None, help="Max price filter.")
    query_parser.add_argument("--price-ratio-max", type=float, default=None, help="Max listing-price / deduplicated-pool-median ratio (e.g. 0.75).")
    query_parser.add_argument("--price-ratio-min", type=float, default=None, help="Min listing-price / deduplicated-pool-median ratio.")
    query_parser.add_argument("--condition", default=None, help="Condition filter keyword (几乎全新/细微瑕疵/明显瑕疵).")
    query_parser.add_argument("--condition-exclude", default=None, help="Exclude candidates whose condition matches this.")
    query_parser.add_argument("--has-detail", action="store_true", default=None, help="Only candidates with captured detail text.")
    query_parser.add_argument("--seller-sold-min", type=int, default=None, help="Min seller sold count.")
    query_parser.add_argument("--seller-sold-max", type=int, default=None, help="Max seller sold count.")
    query_parser.add_argument("--credit-level", default=None, help="Seller credit level filter (信用极好/优秀/良好/较差).")
    query_parser.add_argument("--realname-only", action="store_true", help="Only realname-verified sellers.")
    query_parser.add_argument("--listing-id", type=int, action="append", default=[], help="Specific listing ID(s). Repeatable.")
    query_parser.add_argument("--has-damage", action="store_true", default=None, help="Only candidates with damage keywords.")
    query_parser.add_argument("--no-damage", action="store_true", default=None, help="Only candidates without damage keywords.")
    query_parser.add_argument("--location", action="append", default=[], help="Location substring filter. Repeatable.")
    query_parser.add_argument("--text-contains", action="append", default=[], help="Required text term. Repeatable.")
    query_parser.add_argument("--text-exclude", action="append", default=[], help="Excluded text term. Repeatable.")
    query_parser.add_argument("--text-match", choices=["all", "any"], default="all", help="Whether all or any include terms must match.")
    query_parser.add_argument(
        "--text-scope",
        action="append",
        default=[],
        choices=["title", "search_description", "detail_description", "attributes"],
        help="Saved evidence field used for text matching. Repeatable; defaults to all scopes.",
    )
    query_parser.add_argument("--sort", default="price_asc", choices=["price_asc", "price_desc", "condition_best", "seller_most_active", "credit_best", "recent"], help="Sort order.")
    query_parser.add_argument("--limit", type=int, default=50, help="Max results.")
    query_parser.add_argument("--no-market-context", action="store_true", help="Omit market context (median/price range).")
    query_parser.add_argument("--pretty", action="store_true", help="Print JSON.")

    task_create = subparsers.add_parser("task-create", help="Create a research task that can group multiple runs.")
    task_create.add_argument("--title", required=True, help="Short task title.")
    task_create.add_argument("--goal", required=True, help="Full shopping goal.")
    task_create.add_argument("--city", default=None, help="Explicit trading city preference. Unspecified means no region preference.")
    task_create.add_argument("--notes", default=None, help="Optional task notes.")

    task_attach = subparsers.add_parser("task-attach-run", help="Attach an existing run to a research task.")
    task_attach.add_argument("--task-id", type=int, required=True, help="Research task ID.")
    task_attach.add_argument("--run-id", type=int, required=True, help="Search run ID.")
    task_attach.add_argument("--role", default="search", help="Run role, for example search, manual_seed, baseline.")
    task_attach.add_argument("--notes", default=None, help="Optional attachment notes.")

    task_update = subparsers.add_parser(
        "task-update",
        help="Append a material user preference revision without changing the original goal.",
    )
    task_update.add_argument("--task-id", type=int, required=True, help="Research task ID.")
    task_update.add_argument("--user-message", required=True, help="Exact user message that changed the goal.")
    task_update.add_argument("--effective-goal", required=True, help="Current goal after applying the revision.")
    task_update.add_argument("--add-preference", action="append", default=[], help="Preference added by this revision. Repeatable.")
    task_update.add_argument("--remove-preference", action="append", default=[], help="Preference removed by this revision. Repeatable.")

    task_summary = subparsers.add_parser("task-summary", help="Inspect research tasks and their attached runs/reports.")
    task_summary.add_argument("--task-id", type=int, default=None, help="Task ID to inspect.")
    task_summary.add_argument("--limit", type=int, default=10, help="Number of recent tasks to show.")
    task_summary.add_argument("--pretty", action="store_true", help="Print task summary JSON.")

    detail_candidates = subparsers.add_parser(
        "detail-candidates",
        help="Return an objective, diverse pool of task listings still needing detail evidence.",
    )
    detail_candidates.add_argument("--task-id", type=int, required=True, help="Research task ID.")
    detail_candidates.add_argument("--limit", type=int, default=20, help="Maximum candidates to return.")
    detail_candidates.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    export_task_parser = subparsers.add_parser("export-task", help="Export a task summary and referenced evidence files.")
    export_task_parser.add_argument("--task-id", type=int, required=True, help="Task ID to export.")
    export_task_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Export root directory. Defaults to data/exports.",
    )

    subparsers.add_parser("report", help="Render the latest report.")
    history = subparsers.add_parser("history", help="Inspect saved run history.")
    history.add_argument("--limit", type=int, default=10, help="Number of recent runs to show.")
    history.add_argument("--run-id", type=int, default=None, help="Show page snapshots for a run.")
    history.add_argument(
        "--listings",
        action="store_true",
        help="Show listing snapshots for --run-id instead of page snapshots.",
    )
    history.add_argument(
        "--details",
        action="store_true",
        help="Show detail snapshots for --run-id instead of page snapshots.",
    )

    run_summary = subparsers.add_parser(
        "run-summary",
        help="Print machine-readable JSON summary for a search run.",
    )
    run_summary.add_argument("--run-id", type=int, required=True, help="Run ID to summarize.")
    run_summary.add_argument("--listing-limit", type=int, default=20, help="Maximum listings to include.")
    run_summary.add_argument(
        "--description-chars",
        type=int,
        default=220,
        help="Maximum description excerpt length per listing.",
    )
    run_summary.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    candidate_index = subparsers.add_parser(
        "candidate-index",
        help="Print every deduplicated saved search candidate once in compact form.",
    )
    candidate_index.add_argument("--task-id", type=int, default=None, help="Research task scope.")
    candidate_index.add_argument(
        "--run-id",
        type=int,
        action="append",
        default=None,
        help="Saved run scope. Can be repeated.",
    )
    candidate_index.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional page size (1-100). Omit to return the complete compact scope.",
    )
    candidate_index.add_argument("--cursor", default=None, help="Opaque cursor from the preceding page.")
    candidate_index.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    candidate_evidence = subparsers.add_parser(
        "candidate-evidence",
        help="Print saved evidence for selected in-scope listing IDs.",
    )
    candidate_evidence.add_argument("--task-id", type=int, default=None, help="Research task scope.")
    candidate_evidence.add_argument(
        "--run-id",
        type=int,
        action="append",
        default=None,
        help="Saved run scope. Can be repeated.",
    )
    candidate_evidence.add_argument(
        "--listing-id",
        type=int,
        action="append",
        required=True,
        help="In-scope listing ID. Can be repeated.",
    )
    candidate_evidence.add_argument(
        "--raw-text-chars",
        type=int,
        default=0,
        help="Optional maximum saved detail-text characters per listing.",
    )
    candidate_evidence.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    candidate_pool = subparsers.add_parser(
        "candidate-pool",
        help="Merge one or more search runs into a machine-readable candidate pool.",
    )
    candidate_pool.add_argument(
        "--run-id",
        type=int,
        action="append",
        required=True,
        help="Run ID to include. Can be repeated.",
    )
    candidate_pool.add_argument("--goal", default=None, help="Original shopping goal.")
    candidate_pool.add_argument("--target-city", default=None, help="City signal to prioritize.")
    candidate_pool.add_argument("--limit", type=int, default=80, help="Maximum merged candidates.")
    candidate_pool.add_argument(
        "--shortlist-limit",
        type=int,
        default=12,
        help="Maximum candidates to expose as next evidence shortlist.",
    )
    candidate_pool.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    market_baseline = subparsers.add_parser(
        "market-baseline",
        help="Build a local price baseline from collected candidate pools.",
    )
    market_baseline.add_argument(
        "--run-id",
        type=int,
        action="append",
        required=True,
        help="Run ID to include. Can be repeated.",
    )
    market_baseline.add_argument("--goal", default=None, help="Original shopping goal.")
    market_baseline.add_argument("--target-city", default=None, help="City signal to prioritize.")
    market_baseline.add_argument("--listing-limit", type=int, default=120, help="Maximum merged candidates.")
    market_baseline.add_argument(
        "--shortlist-limit",
        type=int,
        default=20,
        help="Maximum candidates to expose as next evidence shortlist.",
    )
    market_baseline.add_argument("--group-limit", type=int, default=12, help="Maximum spec price groups.")
    market_baseline.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    reference_add = subparsers.add_parser(
        "reference-add",
        help="Save model-collected official spec or market reference evidence.",
    )
    reference_add.add_argument("--run-id", type=int, default=None, help="Optional run ID this reference supports.")
    reference_add.add_argument("--listing-id", type=int, default=None, help="Optional listing ID this reference supports.")
    reference_add.add_argument("--goal", default=None, help="Optional shopping goal this reference supports.")
    reference_add.add_argument("--source-type", choices=SOURCE_TYPE_CHOICES, required=True, help="Reference source type.")
    reference_add.add_argument("--platform", default=None, help="Platform or source family, for example apple, taobao, jd.")
    reference_add.add_argument("--title", required=True, help="Reference title.")
    reference_add.add_argument("--url", required=True, help="Reference URL.")
    reference_add.add_argument("--price-text", default=None, help="Observed price text, if any.")
    reference_add.add_argument("--price-value", type=int, default=None, help="Observed numeric price value, if any.")
    reference_add.add_argument("--currency", default="CNY", help="Currency code. Defaults to CNY.")
    reference_add.add_argument("--evidence-level", default=None, help="Override default evidence level.")
    reference_add.add_argument("--model-key", default=None, help="Comparable model/spec key assigned by the model.")
    reference_add.add_argument("--spec-summary", default=None, help="Short spec or identity summary.")
    reference_add.add_argument("--comparable-scope", default=None, help="Why this reference is or is not comparable.")
    reference_add.add_argument("--notes", default=None, help="Source quality, limitations, or outlier notes.")
    reference_add.add_argument("--checked-at", default=None, help="Date/time checked. Defaults to today's local date.")
    reference_add.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    reference_list = subparsers.add_parser(
        "reference-list",
        help="List and summarize model-recorded reference evidence.",
    )
    reference_list.add_argument("--run-id", type=int, default=None, help="Filter by run ID.")
    reference_list.add_argument("--listing-id", type=int, default=None, help="Filter by listing ID.")
    reference_list.add_argument("--goal", default=None, help="Filter by exact shopping goal.")
    reference_list.add_argument("--limit", type=int, default=50, help="Maximum references to include.")
    reference_list.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    compare_runs = subparsers.add_parser(
        "compare-runs",
        help="Compare multiple search runs to evaluate web filter or keyword effectiveness.",
    )
    compare_runs.add_argument(
        "--run-id",
        type=int,
        action="append",
        required=True,
        help="Run ID to compare. Can be repeated.",
    )
    compare_runs.add_argument("--goal", default=None, help="Original shopping goal.")
    compare_runs.add_argument("--target-city", default=None, help="City signal to prioritize.")
    compare_runs.add_argument("--listing-limit", type=int, default=80, help="Maximum listings per run to inspect.")
    compare_runs.add_argument(
        "--shortlist-limit",
        type=int,
        default=12,
        help="Maximum candidates per run to expose as shortlist context.",
    )
    compare_runs.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    foldback_adopt = subparsers.add_parser(
        "foldback-adopt",
        help="Evaluate whether a Codex-proposed foldback search term improved on its audit baseline run.",
    )
    foldback_adopt.add_argument("--baseline-run-id", type=int, required=True, help="Audit baseline run the foldback term was meant to improve.")
    foldback_adopt.add_argument("--foldback-run-id", type=int, required=True, help="Run produced by executing the subagent proposed foldback term.")
    foldback_adopt.add_argument("query", help="The foldback search term that produced the foldback run.")
    foldback_adopt.add_argument("--goal", default=None, help="Original shopping goal used for noise classification.")
    foldback_adopt.add_argument("--target-city", default=None, help="City signal to prioritize.")
    foldback_adopt.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    run_diff = subparsers.add_parser(
        "run-diff",
        help="Compare two search runs and report new, missing, and changed listings.",
    )
    run_diff.add_argument("--before-run-id", type=int, required=True, help="Earlier run ID.")
    run_diff.add_argument("--after-run-id", type=int, required=True, help="Later run ID.")
    run_diff.add_argument("--goal", default=None, help="Original shopping goal.")
    run_diff.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    recommendation_links = subparsers.add_parser(
        "recommendation-links",
        help="Extract candidate item links from a captured Xianyu detail page.",
    )
    recommendation_links.add_argument("--listing-id", type=int, required=True, help="Listing ID to inspect.")
    recommendation_links.add_argument("--limit", type=int, default=30, help="Maximum recommendation links.")
    recommendation_links.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser


def _search_capture_status_lines(snapshot: SearchSnapshot) -> list[str]:
    lines = [
        "Search pages: "
        f"requested {snapshot.requested_page_count}, "
        f"captured API responses {snapshot.api_page_count}"
    ]
    if snapshot.stop_reason:
        lines.append(f"Collection stop reason: {snapshot.stop_reason}")
    return lines


def _print_search_spike_result(
    result: SearchSpikeResult,
    *,
    task_id: int | None,
    config: AppConfig,
) -> None:
    snapshot = result.snapshot
    if snapshot.stop_reason:
        console.print(f"[yellow]Captured partial search snapshot:[/yellow] {snapshot.url}")
    else:
        console.print(f"[green]Captured search snapshot:[/green] {snapshot.url}")
    console.print(f"Title: {snapshot.page_title}")
    console.print(f"Screenshot: {snapshot.screenshot_path}")
    console.print(f"HTML: {snapshot.html_path}")
    console.print(f"Text: {result.text_path}")
    console.print(f"Links: {result.links_path} ({len(snapshot.links)} links)")
    if result.status_path is not None:
        console.print(f"Status: {result.status_path}")
    for line in _search_capture_status_lines(snapshot):
        console.print(line)
    if snapshot.scroll_window_count > 1:
        console.print(
            f"Scroll union: {snapshot.scroll_window_count} windows captured, "
            f"{snapshot.scroll_union_link_count} unique links"
        )
    console.print(f"Run ID: {result.run_id}")
    console.print(f"Saved candidate listing links: {result.saved_links}")
    console.print(f"Parsed visible listings: {result.parsed_listings}")
    if snapshot.filter_status:
        console.print(f"Filters: {', '.join(snapshot.filter_status)}")
    if task_id is not None:
        try:
            attach_run(config, task_id=task_id, run_id=result.run_id, role="search")
        except ValueError as exc:
            raise SystemExit(str(exc))
        console.print(f"Attached to task: {task_id}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(Path(args.config))
    ensure_runtime_dirs(config)

    if args.command == "init-db":
        initialize(config.database_path)
        console.print(f"[green]Initialized database:[/green] {config.database_path}")
        return

    if args.command == "doctor":
        results = run_doctor(config, check_browser=not args.skip_browser)
        for result in results:
            status = "[green]OK[/green]" if result.ok else "[red]FAIL[/red]"
            console.print(f"{status} {result.name}: {result.detail}")
        if not all(result.ok for result in results):
            raise SystemExit(1)
        return

    if args.command == "task-create":
        task_id = create_task(config, title=args.title, goal=args.goal, city=args.city, notes=args.notes)
        console.print(f"[green]Created research task:[/green] {task_id}")
        console.print(f"Title: {args.title}")
        console.print(f"Goal: {args.goal}")
        console.print(f"City: {args.city or '(unspecified)'}")
        return

    if args.command == "task-attach-run":
        try:
            attachment_id = attach_run(
                config,
                task_id=args.task_id,
                run_id=args.run_id,
                role=args.role,
                notes=args.notes,
            )
        except ValueError as exc:
            raise SystemExit(str(exc))
        console.print(
            f"[green]Attached run:[/green] run {args.run_id} -> task {args.task_id} "
            f"(attachment {attachment_id})"
        )
        return

    if args.command == "task-summary":
        if args.task_id is None:
            print_recent_tasks(config, console, limit=args.limit)
            return
        if args.pretty:
            try:
                summary = build_task_summary(config, args.task_id)
            except ValueError as exc:
                raise SystemExit(str(exc))
            _print_text(json.dumps(summary, ensure_ascii=False, indent=2))
            return
        try:
            print_task_summary(config, console, args.task_id)
        except ValueError as exc:
            raise SystemExit(str(exc))
        return

    if args.command == "task-update":
        try:
            revision_id = update_task_preferences(
                config,
                task_id=args.task_id,
                user_message=args.user_message,
                effective_goal=args.effective_goal,
                added_preferences=args.add_preference,
                removed_preferences=args.remove_preference,
            )
        except ValueError as exc:
            raise SystemExit(str(exc))
        console.print(f"[green]Recorded task preference revision:[/green] {revision_id}")
        console.print(f"Task: {args.task_id}")
        console.print(f"Current goal: {args.effective_goal}")
        return

    if args.command == "detail-candidates":
        try:
            result = build_detail_candidates(
                config,
                task_id=args.task_id,
                options=DetailCandidateOptions(limit=args.limit),
            )
        except ValueError as exc:
            raise SystemExit(str(exc))
        indent = 2 if args.pretty else None
        _print_text(json.dumps(result, ensure_ascii=False, indent=indent))
        return

    if args.command == "export-task":
        try:
            result = export_task(config, task_id=args.task_id, output_dir=args.output_dir)
        except ValueError as exc:
            raise SystemExit(str(exc))
        console.print(f"[green]Exported task:[/green] {result.task_id}")
        console.print(f"Export dir: {result.export_dir}")
        console.print(f"Manifest: {result.manifest_path}")
        console.print(f"Copied files: {result.copied_files}")
        console.print(f"Missing files: {result.missing_files}")
        return

    if args.command == "login":
        if not config.allow_login:
            raise SystemExit("Login is disabled by config.")
        session = BrowserSession(config.browser_profile_dir)
        result = asyncio.run(session.open_for_login(args.platform))
        if result.authenticated is False:
            console.print(
                "[red]Login was not completed.[/red] "
                "The Xianyu login dialog is still visible in the saved browser profile."
            )
            console.print(f"Profile: {config.browser_profile_dir}")
            raise SystemExit(2)
        if result.authenticated is True:
            console.print(f"[green]Login verified.[/green] Profile: {config.browser_profile_dir}")
        else:
            console.print(
                "[yellow]Login browser session closed; authentication was not verified "
                f"for {args.platform}.[/yellow] Profile: {config.browser_profile_dir}"
            )
        return

    if args.command == "research":
        initialize(config.database_path)
        city = region_preference(args.goal, explicit_city=args.city)['city'] or ''
        platforms = args.platform or config.platforms
        project_root = Path.cwd().resolve()
        plan = build_codex_launch_plan(
            project_root=project_root,
            goal=args.goal,
            codex_bin=args.codex_bin,
            enable_search=not args.no_search,
            city=city,
            platforms=platforms,
            codex_args=args.codex_arg,
        )
        prompt_path = write_prompt_file(project_root, plan.prompt)
        console.print("[bold]Research entry delegates to Codex.[/bold]")
        console.print(f"Goal: {args.goal}")
        console.print(f"City: {city}")
        console.print(f"Platforms: {', '.join(platforms)}")
        console.print(f"Database: {config.database_path}")
        console.print(f"Prompt file: {prompt_path}")
        console.print(
            format_interactive_launch_hint(
                project_root,
                goal=args.goal,
                city=city,
                platforms=platforms,
                codex_args=args.codex_arg,
                entrypoint="research",
            )
        )
        console.print("[bold]Codex launch command[/bold]")
        console.print(format_command([part if part != plan.prompt else "<prompt-from-file>" for part in plan.command]))
        if not args.run:
            console.print("Dry run only. Re-run with --run to launch Codex.")
            return
        raise SystemExit(launch_codex(plan))

    if args.command == "goal-plan":
        plan = build_goal_plan(
            args.goal,
            options=GoalPlanOptions(
                city=args.city,
                platforms=args.platform or config.platforms,
                clarify_via_codex=args.clarify_via_codex,
                expand_similar_via_codex=args.expand_similar_via_codex,
            ),
        )
        indent = 2 if args.pretty else None
        _print_text(json.dumps(plan, ensure_ascii=False, indent=indent))
        return

    if args.command == "research-loop":
        try:
            result = asyncio.run(
                run_research_loop(
                    config,
                    args.goal,
                    options=ResearchLoopOptions(
                        city=args.city,
                        platforms=args.platform or config.platforms,
                        max_searches=args.max_searches,
                        execute_search=args.execute_search,
                        acknowledged_risk=args.i_understand_account_risk,
                        wait_ms=args.wait_ms,
                        headless=args.headless,
                        scroll_steps=args.scroll_steps,
                        scroll_wait_ms=args.scroll_wait_ms,
                        listing_limit=args.listing_limit,
                        candidate_limit=args.candidate_limit,
                        shortlist_limit=args.shortlist_limit,
                        task_id=args.task_id,
                        clarify_via_codex=args.clarify_via_codex,
                        expand_similar_via_codex=args.expand_similar_via_codex,
                        next_search_via_codex=args.next_search_via_codex,
                        prior_foldback=_load_prior_foldback(args.prior_foldback),
                        max_pages=args.max_pages,
                    ),
                )
            )
        except SafetyError as exc:
            console.print(f"[red]Safety stop:[/red] {exc}")
            raise SystemExit(2)
        indent = 2 if args.pretty else None
        _print_text(json.dumps(result, ensure_ascii=False, indent=indent))
        return

    if args.command == "spike-search":
        safety_stop: SearchSpikeSafetyError | None = None
        try:
            enforce_browser_collection_safety(
                config=config,
                platform=args.platform,
                headless=args.headless,
                acknowledged_risk=args.i_understand_account_risk,
            )
            result = asyncio.run(
                capture_search_spike(
                    config=config,
                    platform=args.platform,
                    query=args.query,
                    wait_ms=args.wait_ms,
                    headless=args.headless,
                    filters=SearchFilters(
                        min_price=args.min_price,
                        max_price=args.max_price,
                        area=args.area,
                        sort=args.sort,
                    ),
                    scroll_steps=args.scroll_steps,
                    scroll_wait_ms=args.scroll_wait_ms,
                    max_pages=args.max_pages,
                )
            )
        except SearchSpikeSafetyError as exc:
            result = exc.result
            safety_stop = exc
        except SafetyError as exc:
            console.print(f"[red]Safety stop:[/red] {exc}")
            raise SystemExit(2)
        _print_search_spike_result(result, task_id=args.task_id, config=config)
        if safety_stop is not None:
            console.print(f"[red]Safety stop:[/red] {safety_stop}")
            raise SystemExit(2)
        return

    if args.command == "history":
        if args.run_id is not None:
            if args.details:
                print_run_details(config, console, args.run_id)
            elif args.listings:
                print_run_listings(config, console, args.run_id, limit=args.limit)
            else:
                print_run_detail(config, console, args.run_id)
        else:
            print_recent_history(config, console, limit=args.limit)
        return

    if args.command == "run-summary":
        summary = build_run_summary(
            config,
            run_id=args.run_id,
            options=RunSummaryOptions(
                listing_limit=args.listing_limit,
                description_chars=args.description_chars,
            ),
        )
        indent = 2 if args.pretty else None
        print(json.dumps(summary, ensure_ascii=True, indent=indent))
        return

    if args.command == "candidate-index":
        try:
            result = build_candidate_index(
                config,
                task_id=args.task_id,
                run_ids=args.run_id,
                limit=args.limit,
                cursor=args.cursor,
            )
        except ValueError as exc:
            raise SystemExit(str(exc))
        indent = 2 if args.pretty else None
        _print_text(json.dumps(result, ensure_ascii=False, indent=indent))
        return

    if args.command == "candidate-evidence":
        try:
            result = build_candidate_evidence(
                config,
                task_id=args.task_id,
                run_ids=args.run_id,
                listing_ids=args.listing_id,
                raw_text_chars=args.raw_text_chars,
            )
        except ValueError as exc:
            raise SystemExit(str(exc))
        indent = 2 if args.pretty else None
        _print_text(json.dumps(result, ensure_ascii=False, indent=indent))
        return

    if args.command == "candidate-pool":
        pool = build_candidate_pool(
            config,
            run_ids=args.run_id,
            options=CandidatePoolOptions(
                goal=args.goal,
                target_city=args.target_city,
                limit=args.limit,
                shortlist_limit=args.shortlist_limit,
            ),
        )
        indent = 2 if args.pretty else None
        print(json.dumps(pool, ensure_ascii=True, indent=indent))
        return

    if args.command == "market-baseline":
        baseline = build_market_baseline(
            config,
            run_ids=args.run_id,
            options=MarketBaselineOptions(
                goal=args.goal,
                target_city=args.target_city,
                listing_limit=args.listing_limit,
                shortlist_limit=args.shortlist_limit,
                group_limit=args.group_limit,
            ),
        )
        indent = 2 if args.pretty else None
        print(json.dumps(baseline, ensure_ascii=True, indent=indent))
        return

    if args.command == "reference-add":
        record = save_reference_evidence(
            config,
            ReferenceEvidenceInput(
                run_id=args.run_id,
                listing_id=args.listing_id,
                goal=args.goal,
                source_type=args.source_type,
                platform=args.platform,
                title=args.title,
                url=args.url,
                price_text=args.price_text,
                price_value=args.price_value,
                currency=args.currency,
                evidence_level=args.evidence_level,
                model_key=args.model_key,
                spec_summary=args.spec_summary,
                comparable_scope=args.comparable_scope,
                notes=args.notes,
                checked_at=args.checked_at,
            ),
        )
        indent = 2 if args.pretty else None
        print(json.dumps(record, ensure_ascii=True, indent=indent))
        return

    if args.command == "reference-list":
        summary = build_reference_evidence_summary(
            config,
            run_id=args.run_id,
            listing_id=args.listing_id,
            goal=args.goal,
            limit=args.limit,
        )
        indent = 2 if args.pretty else None
        print(json.dumps(summary, ensure_ascii=True, indent=indent))
        return

    if args.command == "compare-runs":
        comparison = build_run_comparison(
            config,
            run_ids=args.run_id,
            options=RunComparisonOptions(
                goal=args.goal,
                target_city=args.target_city,
                listing_limit=args.listing_limit,
                shortlist_limit=args.shortlist_limit,
            ),
        )
        indent = 2 if args.pretty else None
        print(json.dumps(comparison, ensure_ascii=True, indent=indent))
        return

    if args.command == "foldback-adopt":
        verdict = build_foldback_adoption(
            config,
            baseline_run_id=args.baseline_run_id,
            foldback_run_id=args.foldback_run_id,
            query=args.query,
            goal=args.goal,
            target_city=args.target_city,
        )
        indent = 2 if args.pretty else None
        _print_text(json.dumps(verdict, ensure_ascii=False, indent=indent))
        return

    if args.command == "run-diff":
        diff = build_run_diff(
            config,
            before_run_id=args.before_run_id,
            after_run_id=args.after_run_id,
            goal=args.goal,
        )
        indent = 2 if args.pretty else None
        print(json.dumps(diff, ensure_ascii=True, indent=indent))
        return

    if args.command == "recommendation-links":
        initialize(config.database_path)
        with connect(config.database_path) as conn:
            detail_snapshot = fetch_latest_detail_snapshot_for_listing(conn, args.listing_id)
        if detail_snapshot is None:
            raise SystemExit(f"No detail snapshot found for listing {args.listing_id}.")
        links_path = Path(detail_snapshot["links_path"])
        links = links_path.read_text(encoding="utf-8").splitlines() if links_path.exists() else []
        recommendations = parse_xianyu_recommendation_links(
            links,
            current_url=str(detail_snapshot["url"]),
            limit=args.limit,
        )
        payload = {
            "listing_id": args.listing_id,
            "detail_snapshot_id": detail_snapshot["id"],
            "source_url": detail_snapshot["url"],
            "recommendation_count": len(recommendations),
            "recommendation_links": recommendations,
            "note": "These links come from the captured detail page. The LLM should decide whether they are relevant before opening them.",
        }
        indent = 2 if args.pretty else None
        print(json.dumps(payload, ensure_ascii=True, indent=indent))
        return

    if args.command == "capture-detail":
        try:
            enforce_browser_collection_safety(
                config=config,
                platform=args.platform,
                headless=args.headless,
                acknowledged_risk=args.i_understand_account_risk,
                detail_limit=args.limit if args.run_id is not None else 1,
            )
        except SafetyError as exc:
            console.print(f"[red]Safety stop:[/red] {exc}")
            raise SystemExit(2)

        if not args.url and args.run_id is None:
            raise SystemExit("Provide --url and/or --run-id to capture detail pages.")
        urls = [args.url] if args.url else get_listing_urls_for_run(config, args.run_id, args.limit)
        if not urls:
            raise SystemExit("No listing URLs found to capture.")
        url_belongs_to_run = bool(
            args.url
            and args.run_id is not None
            and listing_url_belongs_to_run(config, run_id=args.run_id, url=args.url)
        )
        source_type, source_label, attachment_role = _resolve_detail_capture_metadata(
            url=args.url,
            run_id=args.run_id,
            source_type=args.source_type,
            source_label=args.source_label,
            url_belongs_to_run=url_belongs_to_run,
        )
        for index, url in enumerate(urls, start=1):
            if index > 1:
                wait_between_detail_pages(config, args.platform)
            try:
                result = asyncio.run(
                    capture_detail_url(
                        config=config,
                        url=url,
                        platform=args.platform,
                        run_id=args.run_id,
                        wait_ms=args.wait_ms,
                        headless=args.headless,
                        source_type=source_type,
                        source_label=source_label,
                    )
                )
            except SafetyError as exc:
                console.print(f"[red]Safety stop:[/red] {exc}")
                raise SystemExit(2)
            snapshot = result.snapshot
            console.print(f"[green]Captured detail {index}/{len(urls)}:[/green] {url}")
            console.print(f"Listing ID: {result.listing_id}")
            console.print(f"Run ID: {result.run_id}")
            console.print(f"Source: {source_type} ({source_label})")
            console.print(f"Detail snapshot ID: {result.detail_snapshot_id}")
            console.print(f"Title: {snapshot.page_title}")
            console.print(f"Screenshot: {snapshot.screenshot_path}")
            console.print(f"Text: {snapshot.text_path}")
            console.print(f"Images: {snapshot.images_path} ({len(snapshot.image_urls)} images)")
            if args.task_id is not None and result.run_id is not None:
                try:
                    attach_run(
                        config,
                        task_id=args.task_id,
                        run_id=result.run_id,
                        role=attachment_role,
                    )
                except ValueError as exc:
                    raise SystemExit(str(exc))
                console.print(f"Attached to task: {args.task_id}")
            if snapshot.access_blocked:
                console.print("[yellow]Access appears blocked for this detail page.[/yellow]")
        return

    if args.command == "download-media":
        results = download_pending_media(
            config,
            limit=args.limit,
            media_type=args.media_type,
            run_id=args.run_id,
            listing_id=args.listing_id,
        )
        for result in results:
            if result.ok:
                console.print(f"[green]Downloaded[/green] media {result.media_id}: {result.local_path}")
            else:
                console.print(f"[red]Failed[/red] media {result.media_id}: {result.error}")
        console.print(f"Processed {len(results)} media assets.")
        return

    if args.command == "media-list":
        rows = list_media_assets(config, media_type=args.media_type, limit=args.limit)
        for row in rows:
            local_path = row["local_path"] or "(not downloaded)"
            console.print(
                f"{row['id']} listing={row['listing_id']} type={row['media_type']} "
                f"local={local_path}"
            )
            console.print(f"  {row['source_url']}")
        console.print(f"Shown {len(rows)} media assets.")
        return

    if args.command == "analyze-images":
        records = analyze_downloaded_images(
            config,
            media_type=args.media_type,
            limit=args.limit,
            backend=args.backend,
            include_existing=args.force,
            run_id=args.run_id,
            listing_id=args.listing_id,
        )
        for record in records:
            console.print(
                f"media={record.media_id} {record.width}x{record.height} "
                f"backend={record.backend} status={record.status} "
                f"ocr_chars={record.ocr_chars} path={record.local_path}"
            )
            if record.error:
                console.print(f"  [yellow]{record.error}[/yellow]")
        console.print(f"Analyzed {len(records)} images.")
        return

    if args.command == "analyze-listing":
        try:
            result = analyze_listing(config, listing_id=args.listing_id)
        except ValueError as exc:
            raise SystemExit(str(exc))
        console.print(f"[bold]Listing {result.listing_id}[/bold]")
        console.print(f"URL: {result.url}")
        console.print(f"Price: {_safe_console_text(result.price_text or '')}")
        console.print(f"Location: {_safe_console_text(result.location or '')}")
        console.print(f"Seller: {_safe_console_text(result.seller_name or '')}")
        console.print(f"OCR text images: {result.ocr_count}")
        console.print("[bold]Description specs[/bold]")
        console.print(result.report.description_specs or "(none)")
        console.print("[bold]Image OCR specs[/bold]")
        console.print(result.report.image_specs or "(none)")
        if result.report.flags:
            console.print("[bold]Evidence flags[/bold]")
            for flag in result.report.flags:
                evidence = f" {flag.evidence}" if flag.evidence else ""
                console.print(f"- {flag.severity} {flag.code}: {_safe_console_text(flag.message)}{evidence}")
        if result.report.risks:
            console.print("[bold yellow]Heuristic risks[/bold yellow]")
            for risk in result.report.risks:
                console.print(f"- {_safe_console_text(risk)}")
        if result.report.questions:
            console.print("[bold]Questions for seller[/bold]")
            for question in result.report.questions:
                console.print(f"- {_safe_console_text(question)}")
        return

    if args.command == "build-evidence":
        try:
            bundle = build_listing_evidence(config, listing_id=args.listing_id)
        except ValueError as exc:
            raise SystemExit(str(exc))
        indent = 2 if args.pretty else None
        print(json.dumps(evidence_bundle_to_dict(bundle), ensure_ascii=True, indent=indent))
        return

    if args.command == "prepare-evidence":
        try:
            result = prepare_run_evidence_sync(
                config,
                run_id=args.run_id,
                platform=args.platform,
                detail_limit=args.detail_limit,
                media_limit=args.media_limit,
                ocr_limit=args.ocr_limit,
                wait_ms=args.wait_ms,
                headless=args.headless,
                acknowledged_risk=args.i_understand_account_risk,
                ocr_backend=args.backend,
                build_evidence_limit=args.build_evidence_limit,
                evidence_ocr_chars=args.evidence_ocr_chars,
            )
        except SafetyError as exc:
            console.print(f"[red]Safety stop:[/red] {exc}")
            raise SystemExit(2)
        payload = {
            "run_id": result.run_id,
            "captured_details": [
                {"url": item.url, "detail_snapshot_id": item.detail_snapshot_id}
                for item in result.captured_details
            ],
            "downloaded_media": [
                {
                    "media_id": item.media_id,
                    "source_url": item.source_url,
                    "local_path": str(item.local_path),
                    "ok": item.ok,
                    "error": item.error,
                }
                for item in result.downloaded_media
            ],
            "analyzed_images": [
                {
                    "media_id": item.media_id,
                    "local_path": str(item.local_path),
                    "status": item.status,
                    "backend": item.backend,
                    "width": item.width,
                    "height": item.height,
                    "ocr_chars": item.ocr_chars,
                    "error": item.error,
                }
                for item in result.analyzed_images
            ],
            "ready_listing_ids": result.ready_listing_ids,
            "summary": result.summary,
            "evidence_bundles": result.evidence_bundles,
        }
        indent = 2 if args.pretty else None
        print(json.dumps(payload, ensure_ascii=True, indent=indent))
        return

    if args.command == "evaluation-task":
        options = EvaluationTaskOptions(
            goal=args.goal,
            evidence_ocr_chars=args.evidence_ocr_chars,
            max_listings=args.max_listings,
            candidate_listing_limit=args.candidate_listing_limit,
        )
        if args.listing_id is not None:
            try:
                task = build_listing_evaluation_task(config, listing_id=args.listing_id, options=options)
            except ValueError as exc:
                raise SystemExit(str(exc))
        else:
            task = build_run_evaluation_task(config, run_id=args.run_id, options=options)
        if args.format == "prompt":
            _print_text(render_evaluation_prompt(task))
        else:
            indent = 2 if args.pretty else None
            print(json.dumps(task, ensure_ascii=True, indent=indent))
        return

    if args.command == "report-template":
        metadata = ReportMetadata(
            title=args.title,
            goal=args.goal,
            run_id=args.run_id,
            listing_id=args.listing_id,
            extra_sections=args.extra_section,
        )
        if args.format == "html":
            _print_text(render_html_report_template(metadata))
        else:
            _print_text(render_report_template(metadata))
        return

    if args.command == "query-candidates":
        has_damage = None
        if args.has_damage:
            has_damage = True
        elif args.no_damage:
            has_damage = False
        result = query_candidates(
            config,
            options=CandidateQueryOptions(
                run_ids=args.run_id,
                goal=args.goal,
                min_price=args.min_price,
                max_price=args.max_price,
                price_ratio_max=args.price_ratio_max,
                price_ratio_min=args.price_ratio_min,
                condition=args.condition,
                condition_exclude=args.condition_exclude,
                has_detail=args.has_detail or None,
                seller_sold_min=args.seller_sold_min,
                seller_sold_max=args.seller_sold_max,
                credit_level=args.credit_level,
                realname_verified_only=args.realname_only,
                listing_ids=args.listing_id,
                has_damage_keywords=has_damage,
                locations=args.location,
                text_includes=args.text_contains,
                text_excludes=args.text_exclude,
                text_match_mode=args.text_match,
                text_scopes=args.text_scope,
                sort_by=args.sort,
                limit=args.limit,
                include_market_context=not args.no_market_context,
            ),
        )
        indent = 2 if args.pretty else None
        _print_text(json.dumps(result, ensure_ascii=False, indent=indent))
        return

    if args.command == "backfill-seller-fields":
        result = backfill_seller_fields_from_detail_text(config, run_id=args.run_id)
        console.print(f"[green]Backfilled seller fields:[/green] {result['backfilled_count']} listings in run {args.run_id}")
        indent = 2 if args.pretty else None
        _print_text(json.dumps(result, ensure_ascii=False, indent=indent))
        return

    if args.command == "decision-report":
        report = build_decision_report(
            config,
            run_id=args.run_id,
            options=DecisionReportOptions(
                goal=args.goal,
                target_city=args.target_city,
                max_listings=args.max_listings,
                detailed_review_count=args.detailed_reviews,
            ),
        )
        markdown_text = render_decision_report_markdown(report)
        if args.save:
            metadata = ReportMetadata(
                title=report["title"],
                goal=report.get("goal"),
                run_id=args.run_id,
            )
            report_path = save_markdown_report(
                config=config,
                markdown_text=markdown_text,
                metadata=metadata,
            )
            console.print(f"[green]Saved decision report:[/green] {report_path}")
        if args.pretty:
            _print_text(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_text(markdown_text)
        return

    if args.command == "save-report":
        metadata = ReportMetadata(
            title=args.title,
            goal=args.goal,
            run_id=args.run_id,
            listing_id=args.listing_id,
        )
        if args.stdin:
            markdown_text = sys.stdin.read()
        else:
            markdown_text = args.input.read_text(encoding="utf-8")
        report_path = save_markdown_report(
            config=config,
            markdown_text=markdown_text,
            metadata=metadata,
            filename=args.filename,
        )
        initialize(config.database_path)
        with connect(config.database_path) as conn:
            try:
                add_saved_report(
                    conn,
                    path=report_path,
                    title=args.title,
                    report_format="markdown",
                    goal=args.goal,
                    task_id=args.task_id,
                    run_id=args.run_id,
                    listing_id=args.listing_id,
                )
            except ValueError as exc:
                raise SystemExit(str(exc))
        console.print(f"[green]Saved report:[/green] {report_path}")
        return

    if args.command == "save-html-report":
        metadata = ReportMetadata(
            title=args.title,
            goal=args.goal,
            run_id=args.run_id,
            listing_id=args.listing_id,
        )
        if args.stdin:
            html_text = sys.stdin.read()
        else:
            html_text = args.input.read_text(encoding="utf-8")
        report_path = save_html_report(
            config=config,
            html_text=html_text,
            metadata=metadata,
            filename=args.filename,
        )
        initialize(config.database_path)
        with connect(config.database_path) as conn:
            try:
                add_saved_report(
                    conn,
                    path=report_path,
                    title=args.title,
                    report_format="html",
                    goal=args.goal,
                    task_id=args.task_id,
                    run_id=args.run_id,
                    listing_id=args.listing_id,
                )
            except ValueError as exc:
                raise SystemExit(str(exc))
        console.print(f"[green]Saved HTML report:[/green] {report_path}")
        return

    if args.command == "codex-guide":
        project_root = Path.cwd().resolve()
        guide_city = args.city if args.goal else None
        guide_platforms = (args.platform or config.platforms) if args.goal else None
        plan = build_codex_launch_plan(
            project_root=project_root,
            goal=args.goal,
            listing_id=args.listing_id,
            codex_bin=args.codex_bin,
            enable_search=not args.no_search,
            city=guide_city,
            platforms=guide_platforms,
            codex_args=args.codex_arg,
        )
        prompt_path = write_prompt_file(project_root, plan.prompt)
        console.print(f"Prompt file: {prompt_path}")
        console.print(
            format_interactive_launch_hint(
                project_root,
                goal=args.goal,
                listing_id=args.listing_id,
                city=guide_city,
                platforms=guide_platforms,
                codex_args=args.codex_arg,
            )
        )
        console.print("[bold]Codex launch command[/bold]")
        console.print(format_command([part if part != plan.prompt else "<prompt-from-file>" for part in plan.command]))
        if not args.run:
            console.print("Dry run only. Re-run with --run to launch Codex.")
            return
        raise SystemExit(launch_codex(plan))

    if args.command == "cleanup-media":
        if not args.yes:
            raise SystemExit("Refusing to delete media records without --yes.")
        deleted = cleanup_legacy_media(config, media_type=args.media_type)
        console.print(f"Deleted {deleted} media records of type {args.media_type}.")
        return

    console.print(f"[bold]{args.command} workflow is scaffolded but not implemented yet.[/bold]")


if __name__ == "__main__":
    main()
