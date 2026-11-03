from __future__ import annotations

from shopping_agent.region_preference import region_preference

from dataclasses import dataclass
from typing import Any

from shopping_agent.browser.session import SearchFilters
from shopping_agent.adoption_gate import evaluate_foldback_adoption
from shopping_agent.candidate_pool import CandidatePoolOptions, build_candidate_pool
from shopping_agent.config import AppConfig
from shopping_agent.goal_plan import GoalPlanOptions, build_goal_plan
from shopping_agent.research_assessment import build_research_assessment
from shopping_agent.run_summary import RunSummaryOptions, build_run_summary
from shopping_agent.run_comparison import RunComparisonOptions, build_run_comparison
from shopping_agent.safety import enforce_browser_collection_safety, safety_delay
from shopping_agent.spike import capture_search_spike
from shopping_agent.tasks import attach_run


@dataclass
class ResearchLoopOptions:
    city: str | None = None
    platforms: list[str] | None = None
    max_searches: int = 2
    execute_search: bool = False
    acknowledged_risk: bool = False
    wait_ms: int = 5000
    headless: bool = False
    scroll_steps: int = 0
    scroll_wait_ms: int = 900
    listing_limit: int = 20
    candidate_limit: int = 600
    shortlist_limit: int = 12
    task_id: int | None = None
    clarify_via_codex: bool = False
    expand_similar_via_codex: bool = False
    next_search_via_codex: bool = False
    prior_foldback: dict | None = None
    max_pages: int = 1


async def run_research_loop(config: AppConfig, goal: str, options: ResearchLoopOptions | None = None) -> dict:
    options = options or ResearchLoopOptions()
    city = region_preference(goal, explicit_city=options.city)['city'] or ''
    platforms = options.platforms or config.platforms
    goal_plan = build_goal_plan(
        goal,
        options=GoalPlanOptions(
            city=city,
            platforms=platforms,
            clarify_via_codex=options.clarify_via_codex,
            expand_similar_via_codex=options.expand_similar_via_codex,
        ),
    )
    selected_searches = _select_searches(goal_plan, max_searches=options.max_searches)

    result: dict[str, Any] = {
        "mode": "execute" if options.execute_search else "dry-run",
        "goal": goal,
        "city": city,
        "platforms": platforms,
        "browser_access": "started" if options.execute_search else "not_started",
        "goal_plan": goal_plan,
        "selected_searches": [
            _search_preview(search, options=options) for search in selected_searches
        ],
        "executed_run_ids": [],
        "run_summaries": [],
        "candidate_pool": None,
        "loop_assessment": None,
        "next_decision_points": _next_decision_points(),
        "notes": [
            "This command is an agent entrypoint, not a final recommendation.",
            "Dry-run mode does not open a browser or touch any platform.",
            "The LLM should inspect run summaries and candidate pools before deciding whether to expand, narrow, capture details, or answer a specific unresolved visual question with OCR.",
        ],
    }

    result["loop_assessment"] = _assessment_with_command_previews(
        build_research_assessment(
            goal_plan=goal_plan,
            selected_searches=selected_searches,
            run_summaries=result["run_summaries"],
            candidate_pool=result["candidate_pool"],
            next_search_via_codex=options.next_search_via_codex,
            prior_foldback=options.prior_foldback,
        ),
        options=options,
        candidate_pool=result["candidate_pool"],
        goal=goal,
    )

    if not options.execute_search:
        return result

    run_ids: list[int] = []
    for index, search in enumerate(selected_searches):
        platform = search["platform"]
        filters = _filters_from_mapping(search.get("filters") or {})
        enforce_browser_collection_safety(
            config=config,
            platform=platform,
            headless=options.headless,
            acknowledged_risk=options.acknowledged_risk,
        )
        if index > 0:
            safety_delay(config, platform)
        spike_result = await capture_search_spike(
            config=config,
            platform=platform,
            query=search["query"],
            wait_ms=options.wait_ms,
            headless=options.headless,
            filters=filters,
            scroll_steps=options.scroll_steps,
            scroll_wait_ms=options.scroll_wait_ms,
            max_pages=options.max_pages,
        )
        run_ids.append(spike_result.run_id)
        result["executed_run_ids"].append(spike_result.run_id)
        if options.task_id is not None:
            attach_run(config, task_id=options.task_id, run_id=spike_result.run_id, role="search")
        result["run_summaries"].append(
            build_run_summary(
                config,
                run_id=spike_result.run_id,
                options=RunSummaryOptions(listing_limit=options.listing_limit),
            )
        )

    if run_ids:
        result["candidate_pool"] = build_candidate_pool(
            config,
            run_ids=run_ids,
            options=CandidatePoolOptions(
                goal=goal,
                target_city=city,
                limit=options.candidate_limit,
                shortlist_limit=options.shortlist_limit,
            ),
        )

    result["loop_assessment"] = _assessment_with_command_previews(
        build_research_assessment(
            goal_plan=goal_plan,
            selected_searches=selected_searches,
            run_summaries=result["run_summaries"],
            candidate_pool=result["candidate_pool"],
            next_search_via_codex=options.next_search_via_codex,
            prior_foldback=options.prior_foldback,
        ),
        options=options,
        candidate_pool=result["candidate_pool"],
        goal=goal,
    )

    return result


def build_foldback_adoption(
    config: AppConfig,
    *,
    baseline_run_id: int,
    foldback_run_id: int,
    query: str,
    goal: str | None = None,
    target_city: str | None = None,
) -> dict:
    """Evaluate a Codex-proposed foldback term against its audit baseline.

    Used by the driving Codex session after spawning a subagent, folding its
    WINNING_TERM into a real spike-search, and needing to decide whether to
    adopt that term into search_rounds or reject it and feed the failure back.
    Computes the same metrics compare-runs produces and applies the adoption
    gate so the loop converges instead of accumulating worse terms.
    """
    comparison = build_run_comparison(
        config,
        run_ids=[baseline_run_id, foldback_run_id],
        options=RunComparisonOptions(
            goal=goal,
            target_city=target_city,
        ),
    )
    run_metrics = comparison.get("run_metrics") or []
    if len(run_metrics) < 2:
        return {
            "baseline_run_id": baseline_run_id,
            "foldback_run_id": foldback_run_id,
            "query": query,
            "verdict": "indeterminate",
            "adopted": False,
            "reason": (
                f"Could not build metrics for both runs (got {len(run_metrics)}); "
                "treat as not-adopted until a clean comparison is possible."
            ),
        }
    return evaluate_foldback_adoption(
        baseline_run_id=baseline_run_id,
        foldback_run_id=foldback_run_id,
        baseline_metrics=run_metrics[0],
        foldback_metrics=run_metrics[1],
        query=query,
    )


def _select_searches(goal_plan: dict, max_searches: int) -> list[dict]:
    if max_searches <= 0:
        return []
    searches = list(goal_plan.get("search_rounds", []))
    if max_searches < 3:
        return searches[:max_searches]

    primary = [search for search in searches if not search.get("alternative")]
    alternatives = [search for search in searches if search.get("alternative")]
    selected = primary[: max_searches - 1]
    if alternatives:
        selected.append(alternatives[0])
    for search in searches:
        if len(selected) >= max_searches:
            break
        if _search_key(search) not in {_search_key(item) for item in selected}:
            selected.append(search)
    return selected[:max_searches]


def _search_preview(search: dict, *, options: ResearchLoopOptions) -> dict:
    filters = search.get("filters") or {}
    requires_risk_ack = search["platform"] == "xianyu"
    command = _spike_search_command(
        platform=search["platform"],
        query=search["query"],
        wait_ms=options.wait_ms,
        filters=filters,
        scroll_steps=options.scroll_steps,
        scroll_wait_ms=options.scroll_wait_ms,
        headless=options.headless,
        include_risk_ack=requires_risk_ack,
    )
    return {
        "round": search.get("round"),
        "platform": search["platform"],
        "query": search["query"],
        "filters": filters,
        "purpose": search.get("purpose"),
        "alternative": bool(search.get("alternative")),
        "requires_account_risk_acknowledgement": requires_risk_ack,
        "command_preview": command,
    }


def _assessment_with_command_previews(
    assessment: dict,
    *,
    options: ResearchLoopOptions,
    candidate_pool: dict | None = None,
    goal: str | None = None,
) -> dict:
    enriched = dict(assessment)
    enriched_candidates = []
    for candidate in assessment.get("next_search_candidates", []):
        enriched_candidate = dict(candidate)
        platform = str(enriched_candidate.get("platform") or "")
        query = str(enriched_candidate.get("query") or "")
        filters = enriched_candidate.get("filters") or {}
        if platform and query:
            enriched_candidate["requires_account_risk_acknowledgement"] = platform == "xianyu"
            enriched_candidate["command_preview"] = _spike_search_command(
                platform=platform,
                query=query,
                wait_ms=options.wait_ms,
                filters=filters,
                scroll_steps=options.scroll_steps,
                scroll_wait_ms=options.scroll_wait_ms,
                headless=options.headless,
                include_risk_ack=platform == "xianyu",
            )
        enriched_candidates.append(enriched_candidate)
    enriched["next_search_candidates"] = enriched_candidates
    enriched["suggested_next_actions"] = [
        _action_with_command_previews(action, options=options, candidate_pool=candidate_pool, goal=goal)
        for action in assessment.get("suggested_next_actions", [])
    ]
    return enriched


def _action_with_command_previews(
    action: dict,
    *,
    options: ResearchLoopOptions,
    candidate_pool: dict | None,
    goal: str | None,
) -> dict:
    enriched = dict(action)
    if action.get("type") == "compare_runs":
        run_ids = [run_id for run_id in action.get("run_ids", []) if isinstance(run_id, int)]
        if len(run_ids) >= 2:
            enriched["command_preview"] = _compare_runs_command(
                run_ids=run_ids,
                goal=goal,
                target_city=options.city,
            )
            enriched["command_scope_note"] = (
                "compare-runs only reads local run summaries and candidate signals. "
                "The LLM still decides whether filter precision, recall, or adjacent-model coverage is better for this shopping goal."
            )
        return enriched

    if action.get("type") == "build_evaluation_task":
        listing_ids = [listing_id for listing_id in action.get("listing_ids", []) if isinstance(listing_id, int)]
        if listing_ids:
            enriched["command_previews"] = [
                _evaluation_task_command(listing_id=listing_id, goal=goal)
                for listing_id in listing_ids[:5]
            ]
            enriched["command_scope_note"] = (
                "evaluation-task builds the model prompt from ready evidence. "
                "The LLM still performs the final risk, price, and recommendation judgment."
            )
        return enriched

    if action.get("type") == "inspect_recommendation_links":
        listing_ids = [listing_id for listing_id in action.get("listing_ids", []) if isinstance(listing_id, int)]
        if listing_ids:
            enriched["command_previews"] = [
                _recommendation_links_command(listing_id=listing_id)
                for listing_id in listing_ids[:5]
            ]
            enriched["command_scope_note"] = (
                "recommendation-links only reads already captured detail-page snapshots. "
                "The LLM decides whether any related item deserves a new low-frequency capture."
            )
        return enriched

    if action.get("type") != "prepare_evidence":
        return enriched

    run_ids = [run_id for run_id in (candidate_pool or {}).get("run_ids", []) if isinstance(run_id, int)]
    if not run_ids:
        return enriched

    platform = _candidate_pool_platform(candidate_pool) or "xianyu"
    enriched["command_previews"] = [
        _prepare_evidence_command(
            run_id=run_id,
            platform=platform,
            wait_ms=options.wait_ms,
            headless=options.headless,
            include_risk_ack=platform == "xianyu",
        )
        for run_id in run_ids[:3]
    ]
    enriched["requires_account_risk_acknowledgement"] = platform == "xianyu"
    enriched["command_scope_note"] = (
        "prepare-evidence works per run. listing_ids explain which shortlisted candidates need evidence; "
        "the command will prepare an account-safe batch from that run."
    )
    return enriched


def _candidate_pool_platform(candidate_pool: dict | None) -> str | None:
    for candidate in (candidate_pool or {}).get("all_candidates", []):
        platform = candidate.get("platform")
        if platform:
            return str(platform)
    return None


def _search_key(search: dict) -> tuple:
    filters = search.get("filters") or {}
    return (search.get("platform"), search.get("query"), tuple(sorted(filters.items())))


def _spike_search_command(
    *,
    platform: str,
    query: str,
    wait_ms: int,
    filters: dict,
    scroll_steps: int,
    scroll_wait_ms: int,
    headless: bool,
    include_risk_ack: bool,
) -> str:
    parts = ["python", "-m", "shopping_agent.cli", "spike-search", platform, _quote_arg(query)]
    min_price = _int_filter(filters.get("min_price"))
    max_price = _int_filter(filters.get("max_price"))
    area = _str_filter(filters.get("area"))
    sort = _sort_filter(filters.get("sort"))
    if min_price is not None:
        parts.extend(["--min-price", str(min_price)])
    if max_price is not None:
        parts.extend(["--max-price", str(max_price)])
    if area:
        parts.extend(["--area", _quote_arg(area)])
    if sort:
        parts.extend(["--sort", sort])
    if scroll_steps > 0:
        parts.extend(["--scroll-steps", str(scroll_steps), "--scroll-wait-ms", str(scroll_wait_ms)])
    parts.extend(["--wait-ms", str(wait_ms)])
    if headless:
        parts.append("--headless")
    if include_risk_ack:
        parts.append("--i-understand-account-risk")
    return " ".join(parts)


def _prepare_evidence_command(
    *,
    run_id: int,
    platform: str,
    wait_ms: int,
    headless: bool,
    include_risk_ack: bool,
) -> str:
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
        "3",
        "--media-limit",
        "0",
        "--ocr-limit",
        "0",
        "--wait-ms",
        str(wait_ms),
    ]
    if headless:
        parts.append("--headless")
    if include_risk_ack:
        parts.append("--i-understand-account-risk")
    parts.append("--pretty")
    return " ".join(parts)


def _evaluation_task_command(*, listing_id: int, goal: str | None) -> str:
    parts = [
        "python",
        "-m",
        "shopping_agent.cli",
        "evaluation-task",
        "--listing-id",
        str(listing_id),
    ]
    if goal:
        parts.extend(["--goal", _quote_arg(goal)])
    parts.extend(["--format", "prompt"])
    return " ".join(parts)


def _recommendation_links_command(*, listing_id: int) -> str:
    return (
        "python -m shopping_agent.cli recommendation-links "
        f"--listing-id {listing_id} --pretty"
    )


def _compare_runs_command(*, run_ids: list[int], goal: str | None, target_city: str | None) -> str:
    parts = ["python", "-m", "shopping_agent.cli", "compare-runs"]
    for run_id in run_ids[:5]:
        parts.extend(["--run-id", str(run_id)])
    if goal:
        parts.extend(["--goal", _quote_arg(goal)])
    if target_city:
        parts.extend(["--target-city", _quote_arg(target_city)])
    parts.append("--pretty")
    return " ".join(parts)


def _filters_from_mapping(filters: dict) -> SearchFilters:
    return SearchFilters(
        min_price=_int_filter(filters.get("min_price")),
        max_price=_int_filter(filters.get("max_price")),
        area=_str_filter(filters.get("area")),
        sort=_sort_filter(filters.get("sort")),
    )


def _int_filter(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _str_filter(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _bool_filter(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _sort_filter(value: object) -> str | None:
    sort = _str_filter(value)
    if not sort or sort == "default":
        return None
    if sort in {"newest", "price_asc", "price_desc"}:
        return sort
    return None


def _quote_arg(value: str) -> str:
    if not value or any(char.isspace() for char in value) or '"' in value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _next_decision_points() -> list[str]:
    return [
        "Are the search results real target products instead of accessories, repair services, recycled listings, or boxes?",
        "Do price and location fields cover most candidates?",
        "Does the shortlist contain enough plausible listings to justify detail capture?",
        "Should the LLM broaden to adjacent models, add a conservative price floor, or use another keyword?",
        "Which candidates have a material evidence gap that justifies one detail capture?",
        "Does any selected listing have a specific unresolved visual question that justifies targeted image download or OCR?",
    ]
