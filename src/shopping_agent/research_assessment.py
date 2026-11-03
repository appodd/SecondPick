from __future__ import annotations

from typing import Any

from shopping_agent.collection_sufficiency import build_collection_sufficiency


def build_research_assessment(
    *,
    goal_plan: dict,
    selected_searches: list[dict],
    run_summaries: list[dict],
    candidate_pool: dict | None,
    next_search_via_codex: bool = False,
    prior_foldback: dict | None = None,
) -> dict:
    executed = bool(run_summaries)
    coverage = _coverage(run_summaries, candidate_pool)
    flags = _quality_flags(coverage, candidate_pool)
    status = _status(executed=executed, access_blocked=coverage["access_blocked"])
    next_search_request = (
        build_next_search_request(
            goal_plan=goal_plan,
            selected_searches=selected_searches,
            run_summaries=run_summaries,
            candidate_pool=candidate_pool,
            coverage=coverage,
            flags=flags,
            prior_foldback=prior_foldback,
        )
        if next_search_via_codex and status != "not_executed"
        else None
    )
    sufficiency = build_collection_sufficiency(candidate_pool) if status != "not_executed" else None
    return {
        "status": status,
        "collection_sufficiency": sufficiency,
        "decision_owner": "llm",
        "is_final_recommendation": False,
        "coverage": coverage,
        "quality_flags": flags,
        "model_decision_brief": _model_decision_brief(
            status=status,
            flags=flags,
            coverage=coverage,
        ),
        "candidate_signal_counts": _candidate_signal_counts(candidate_pool),
        "remaining_planned_searches": _remaining_planned_searches(goal_plan, selected_searches),
        "next_search_candidates": _next_search_candidates(
            status=status,
            flags=flags,
            goal_plan=goal_plan,
            selected_searches=selected_searches,
        ),
        "candidate_pool_suggested_actions": (candidate_pool or {}).get("suggested_next_actions", []),
        "suggested_next_actions": _suggest_next_actions(
            status=status,
            flags=flags,
            run_summaries=run_summaries,
            goal_plan=goal_plan,
            candidate_pool=candidate_pool,
        ),
        "user_calibration": _user_calibration(
            goal_plan=goal_plan,
            status=status,
            flags=flags,
            coverage=coverage,
        ),
        "llm_decision_questions": _llm_decision_questions(
            status=status, flags=flags, coverage=coverage
        ),
        "notes": [
            "These are tool-layer observations. They should guide the model, not replace model judgment.",
            "Do not produce a final purchase recommendation until saved detail evidence and current reference price/spec evidence are sufficient. Image/OCR evidence is optional and targeted only when a specific unresolved visual question remains.",
            "Fixed price thresholds such as suspicious_low_price_for_target are conservative floors, not model-specific verdicts; prefer candidate_pool.price_distribution and each candidate price_percentile_in_pool when judging whether a price is anomalous.",
        ],
        "next_search_request": next_search_request,
        "foldback_adoption": prior_foldback,
    }


def _llm_decision_questions(*, status: str, flags: list[str], coverage: dict) -> list[str]:
    """Context-aware decision questions handed to the LLM.

    Replaces a static question list so the model is prompted with the
    decisions that matter for the current loop state instead of the same four
    generic questions every time. Advisory only; no execution side effects.
    """
    if coverage.get("access_blocked") or status == "blocked":
        return [
            "Is the access block a login wall, captcha, or rate limit rather than a missing listing?",
            "Should the next move retry after a manual login or a safety delay instead of changing search terms?",
            "Is the account-risk acknowledgement and headless/headed mode correct for this platform right now?",
        ]
    if "high_noise_ratio" in flags or "target_size_mismatch_noise" in flags:
        return [
            "Are most listings real target products, or accessories, parts, services, or wrong-size variants?",
            "Should the next move revise keywords to a size/model-specific term, or apply a conservative price floor?",
            "Which candidates are worth keeping despite noise, and which should be excluded from the shortlist?",
        ]
    if coverage.get("shortlist_missing_evidence_count", 0) > 0 and coverage.get("ready_shortlist_count", 0) == 0:
        return [
            "Which shortlisted candidates have a material evidence gap that justifies detail capture before evaluation?",
            "Is the price and location coverage sufficient to compare these candidates fairly?",
            "Does any selected listing have a specific unresolved visual question that justifies targeted image download or OCR?",
        ]
    if coverage.get("ready_shortlist_count", 0) > 0:
        return [
            "Which ready-evidence candidates should move to an evaluation task and the final report?",
            "Do adjacent models deserve inclusion in the comparison based on price and quality?",
            "Is current reference price/spec evidence sufficient, or is another search or external lookup needed before the final recommendation?",
        ]
    if "low_candidate_count" in flags or coverage.get("candidate_count", 0) == 0:
        return [
            "Is the candidate pool too thin to judge value, or just early in the search?",
            "Should the next move broaden terms, try remaining planned searches, or add another platform?",
            "Are there enough plausible real-product candidates to justify detail capture yet?",
        ]
    return [
        "Are there enough plausible real-product candidates to justify detail capture?",
        "Should the next move broaden terms, narrow terms, add a platform filter, or capture details?",
        "Do adjacent models deserve inclusion in the comparison based on price and quality?",
        "Which candidates need detail evidence before recommendation, and which specific visual questions, if any, justify targeted OCR?",
    ]


def build_next_search_request(
    *,
    goal_plan: dict,
    selected_searches: list[dict],
    run_summaries: list[dict],
    candidate_pool: dict | None,
    coverage: dict,
    flags: list[str],
    prior_foldback: dict | None = None,
) -> dict:
    """Build an advisory Codex request that proposes next-round search terms from real results.

    Unlike the rule-based next_search_candidates (which only picks from the
    pre-generated goal_plan pool), this asks Codex to generate fresh search terms
    driven by what the first round actually returned: noise type, price
    distribution, observed models/sizes, and coverage gaps. Advisory only; does
    not launch Codex or open a platform.
    """
    prompt = _build_next_search_prompt(
        goal_plan=goal_plan,
        selected_searches=selected_searches,
        run_summaries=run_summaries,
        candidate_pool=candidate_pool,
        coverage=coverage,
        flags=flags,
        prior_foldback=prior_foldback,
    )
    return {
        "codex_prompt": prompt,
        "command_preview": _next_search_codex_command(goal_plan.get("goal") or ""),
        "policy": (
            "Advisory only. Does not auto-launch Codex or open a platform. "
            "Proposed terms should be folded into search_rounds and executed "
            "low-frequency after the model confirms them. Always keep at least "
            "one broad/unfiltered run for audit before narrowing."
        ),
    }


def _build_next_search_prompt(
    *,
    goal_plan: dict,
    selected_searches: list[dict],
    run_summaries: list[dict],
    candidate_pool: dict | None,
    coverage: dict,
    flags: list[str],
    prior_foldback: dict | None = None,
) -> str:
    goal = goal_plan.get("goal") or "(unspecified goal)"
    executed_queries = [search.get("query") for search in selected_searches if search.get("query")]
    queries_line = "; ".join(executed_queries) if executed_queries else "(none)"
    signal_counts = _candidate_signal_counts(candidate_pool)
    price_dist = (candidate_pool or {}).get("price_distribution") or {}
    foldback_line = _format_prior_foldback(prior_foldback)
    return f"""You are the planner for a secondhand shopping research workflow.

User goal: {goal}
Executed search terms: {queries_line}

Observed results (tool-layer facts, not final judgments):
- runs executed: {coverage.get("run_count")}
- listings captured: {coverage.get("listing_count")}
- priced listing ratio: {coverage.get("priced_listing_ratio")}
- located listing ratio: {coverage.get("located_listing_ratio")}
- candidate_count: {coverage.get("candidate_count")}
- shortlist_count: {coverage.get("shortlist_count")}
- quality_flags: {flags}
- candidate noise signals: {signal_counts}
- price_distribution: {price_dist}
{foldback_line}
Based on these REAL results, propose the next round of search terms. Do NOT open any platform
or run browser collection. Specifically:
1. Diagnose what the current results are missing or polluted by (wrong-size noise, accessory/parts
   noise, service listings, suspicious low-price outliers, too few candidates, missing target city).
2. Generate 2-5 NEW search terms not already in the executed queries. Prefer: synonyms, model
   code numbers (e.g. A2442), alternate Chinese/English phrasings, adjacent models that fit the
   goal, or size/chip-specific terms to cut noise. For each term give a one-line reason tied to
   the observed results.
3. If a conservative price floor is warranted, estimate it FROM the price_distribution above
   (e.g. below p25 or min), not a global constant; state the estimated floor and why.
4. Mark which new terms are safe to run by default versus need user confirmation (e.g. broadening
   to a different category that could derail the comparison).

Return only the next-search proposal. The downstream workflow will fold approved terms into
search_rounds before any real platform search.
"""


def _next_search_codex_command(goal: str) -> str:
    escaped = goal.replace("\\", "\\\\").replace('"', '\\"')
    return (
        'codex --search "Propose next-round search terms for the secondhand shopping goal below, '
        f'based on real first-round results. Do not open any platform.\n\nGoal: \"{escaped}\""'
    )
def _format_prior_foldback(prior_foldback: dict | None) -> str:
    """Render the most recent foldback adoption verdict into the prompt.

    Without this, the next subagent pass has no memory of a rejected term and
    can re-propose the same failing term shape (e.g. a size qualifier that
    raised accessory/service noise on Xianyu).
    """
    if not prior_foldback:
        return ""
    verdict = prior_foldback.get("verdict", "unknown")
    query = prior_foldback.get("query", "")
    reason = prior_foldback.get("reason", "")
    noise_delta = prior_foldback.get("noise_ratio_delta")
    useful_delta = prior_foldback.get("useful_candidate_delta")
    delta_line = ""
    if noise_delta is not None and useful_delta is not None:
        delta_line = f" (noise_delta={noise_delta:+.3f}, useful_delta={useful_delta:+})"
    return (
        f"\nPrior foldback verdict: '{query}' was {verdict}{delta_line}.\n"
        f"Reason: {reason}\n"
        "If the prior foldback was rejected, do NOT re-propose the same term or a trivial "
        "rephrasing of it; explain how your new terms avoid the failure mode.\n"
    )


def _coverage(run_summaries: list[dict], candidate_pool: dict | None) -> dict:
    qualities = [summary.get("result_quality", {}) for summary in run_summaries]
    listing_count = sum(_int(quality.get("listing_count")) for quality in qualities)
    priced_count = sum(_int(quality.get("priced_listing_count")) for quality in qualities)
    located_count = sum(_int(quality.get("located_listing_count")) for quality in qualities)
    access_blocked = any(bool(quality.get("access_blocked")) for quality in qualities)
    shortlist = (candidate_pool or {}).get("shortlist_for_next_evidence") or []
    ready_shortlist_count = sum(1 for item in shortlist if _has_ready_evidence(item))
    return {
        "run_count": len(run_summaries),
        "access_blocked": access_blocked,
        "listing_count": listing_count,
        "priced_listing_count": priced_count,
        "located_listing_count": located_count,
        "priced_listing_ratio": _ratio(priced_count, listing_count),
        "located_listing_ratio": _ratio(located_count, listing_count),
        "candidate_count": _int((candidate_pool or {}).get("candidate_count")),
        "shortlist_count": len(shortlist),
        "ready_shortlist_count": ready_shortlist_count,
        "shortlist_missing_evidence_count": max(len(shortlist) - ready_shortlist_count, 0),
    }


def _quality_flags(coverage: dict, candidate_pool: dict | None) -> list[str]:
    flags: list[str] = []
    if coverage["access_blocked"]:
        flags.append("access_blocked")
    if coverage["run_count"] == 0:
        flags.append("not_executed")
    if coverage["run_count"] > 0 and coverage["listing_count"] == 0:
        flags.append("no_listings")
    if coverage["candidate_count"] and coverage["candidate_count"] < 15:
        flags.append("low_candidate_count")
    if coverage["priced_listing_ratio"] < 0.7 and coverage["listing_count"] > 0:
        flags.append("low_price_coverage")
    if coverage["located_listing_ratio"] < 0.5 and coverage["listing_count"] > 0:
        flags.append("low_location_coverage")
    if coverage["shortlist_count"] == 0 and coverage["candidate_count"] > 0:
        flags.append("no_shortlist")
    if coverage["shortlist_missing_evidence_count"] > 0:
        flags.append("shortlist_needs_evidence")

    signal_counts = _candidate_signal_counts(candidate_pool)
    noisy = (
        signal_counts["likely_accessory_or_parts"]
        + signal_counts["likely_service_listing"]
        + signal_counts["suspicious_low_price_for_target"]
        + signal_counts["likely_non_target_size"]
    )
    if signal_counts["all_candidates"] > 0 and noisy / signal_counts["all_candidates"] >= 0.35:
        flags.append("high_noise_ratio")
    if signal_counts["all_candidates"] > 0 and signal_counts["likely_non_target_size"] / signal_counts["all_candidates"] >= 0.25:
        flags.append("target_size_mismatch_noise")
    if (candidate_pool or {}).get("region_preference", {}).get("mode", "none") != "none" and signal_counts["all_candidates"] >= 10 and signal_counts["target_city_hint"] == 0:
        flags.append("no_target_city_signal")
    return flags


def _model_decision_brief(*, status: str, flags: list[str], coverage: dict) -> dict:
    return {
        "decision_owner": "llm",
        "search_quality": _search_quality_label(status=status, flags=flags, coverage=coverage),
        "evidence_readiness": _evidence_readiness_label(coverage),
        "recommended_next_move": _recommended_next_move(status=status, flags=flags, coverage=coverage),
        "reason_codes": flags,
        "can_start_final_evaluation": coverage["ready_shortlist_count"] > 0,
        "can_write_final_report_now": False,
        "why_not_final_report": _why_not_final_report(status=status, flags=flags, coverage=coverage),
        "required_before_final_report": _required_before_final_report(coverage),
        "note": (
            "This brief summarizes local tool observations for the model. "
            "The model still decides search strategy, risk, price, and recommendation after checking official specs and current market evidence."
        ),
    }


def _search_quality_label(*, status: str, flags: list[str], coverage: dict) -> str:
    if status == "not_executed":
        return "not_executed"
    if status == "blocked":
        return "blocked"
    if "no_listings" in flags:
        return "empty"
    if "high_noise_ratio" in flags or "target_size_mismatch_noise" in flags:
        return "noisy"
    if "low_candidate_count" in flags:
        return "thin"
    if coverage["shortlist_count"] > 0:
        return "usable_shortlist"
    return "usable_search_observation"


def _evidence_readiness_label(coverage: dict) -> str:
    if coverage["ready_shortlist_count"] > 0 and coverage["shortlist_missing_evidence_count"] == 0:
        return "ready_for_evaluation_task"
    if coverage["ready_shortlist_count"] > 0:
        return "partially_ready_for_evaluation_task"
    if coverage["shortlist_missing_evidence_count"] > 0:
        return "needs_detail_evidence"
    if coverage["shortlist_count"] > 0:
        return "shortlist_without_ready_evidence"
    return "no_shortlist_evidence"


def _recommended_next_move(*, status: str, flags: list[str], coverage: dict) -> str:
    if status == "not_executed":
        return "execute_selected_searches"
    if status == "blocked":
        return "stop_for_safety"
    if "target_size_mismatch_noise" in flags:
        return "revise_size_specific_search_terms"
    if "high_noise_ratio" in flags or "no_listings" in flags:
        return "revise_search_terms_or_apply_conditional_filter"
    if coverage["shortlist_missing_evidence_count"] > 0:
        return "prepare_evidence_for_shortlist"
    if coverage["ready_shortlist_count"] > 0:
        return "build_evaluation_task"
    if "low_candidate_count" in flags:
        return "broaden_or_try_remaining_planned_searches"
    return "model_decide_next_step"


def _why_not_final_report(*, status: str, flags: list[str], coverage: dict) -> list[str]:
    reasons: list[str] = []
    if status == "not_executed":
        reasons.append("No platform search has been executed yet.")
    if status == "blocked":
        reasons.append("Platform access appears blocked; stop for safety.")
    if "no_listings" in flags:
        reasons.append("No listings were collected.")
    if "high_noise_ratio" in flags:
        reasons.append("The candidate pool is noisy and needs model-led search revision or filtering.")
    if "target_size_mismatch_noise" in flags:
        reasons.append("Many candidates appear to mention non-target screen sizes.")
    if coverage["shortlist_count"] == 0:
        reasons.append("No shortlist exists yet.")
    if coverage["shortlist_missing_evidence_count"] > 0:
        reasons.append("Shortlisted candidates still need detail evidence; detail evidence is sufficient unless a specific unresolved visual question remains.")
    if coverage["ready_shortlist_count"] == 0:
        reasons.append("No listing is ready for an evaluation task.")
    reasons.append("Official specs and current market price evidence still need to be checked by the model.")
    return _dedupe_strings(reasons)


def _required_before_final_report(coverage: dict) -> list[str]:
    required = []
    if coverage["ready_shortlist_count"] == 0:
        required.append("At least one ready evidence bundle with a saved detail page; add targeted image or OCR evidence only for a named unresolved visual question.")
    required.extend(
        [
            "Official or trusted reference specifications for the identified product.",
            "Current market price evidence from comparable active listings or recent sold/history samples.",
            "Model-written Chinese HTML comparison report saved with save-html-report.",
        ]
    )
    return required


def _status(*, executed: bool, access_blocked: bool) -> str:
    if not executed:
        return "not_executed"
    if access_blocked:
        return "blocked"
    return "needs_model_decision"


def _candidate_signal_counts(candidate_pool: dict | None) -> dict:
    candidates = (candidate_pool or {}).get("all_candidates") or []
    keys = [
        "likely_accessory_or_parts",
        "likely_service_listing",
        "suspicious_low_price_for_target",
        "likely_non_target_size",
        "target_city_hint",
        "mentions_target_screen_size",
        "mentions_non_target_screen_size",
    ]
    counts = {"all_candidates": len(candidates)}
    for key in keys:
        counts[key] = sum(1 for item in candidates if (item.get("signals") or {}).get(key))
    return counts


def _remaining_planned_searches(goal_plan: dict, selected_searches: list[dict], limit: int = 5) -> list[dict]:
    selected_keys = {_search_key(search) for search in selected_searches}
    remaining = []
    for search in goal_plan.get("search_rounds", []):
        if _search_key(search) in selected_keys:
            continue
        remaining.append(
            {
                "round": search.get("round"),
                "platform": search.get("platform"),
                "query": search.get("query"),
                "filters": search.get("filters") or {},
                "purpose": search.get("purpose"),
                "alternative": bool(search.get("alternative")),
            }
        )
        if len(remaining) >= limit:
            break
    return remaining


def _next_search_candidates(
    *,
    status: str,
    flags: list[str],
    goal_plan: dict,
    selected_searches: list[dict],
    limit: int = 6,
) -> list[dict]:
    if status == "blocked":
        return []

    candidates: list[dict] = []
    if status == "not_executed":
        for search in selected_searches:
            candidates.append(
                _search_candidate(
                    search,
                    source="selected_first_round",
                    reason="Execute this selected search first.",
                )
        )
        return _dedupe_search_candidates(candidates)[:limit]

    if "target_size_mismatch_noise" in flags:
        for search in _target_size_refinement_searches(goal_plan, selected_searches, limit=limit):
            candidates.append(
                _search_candidate(
                    search,
                    source="target_size_refinement",
                    reason=(
                        "Current candidates contain many explicit non-target screen sizes. "
                        "Try a planned query that keeps the target size in the search text."
                    ),
                )
            )

    if "high_noise_ratio" in flags or "no_listings" in flags:
        for conditional_filter in goal_plan.get("conditional_filters", []):
            for search in selected_searches[:3]:
                filtered_search = dict(search)
                filtered_search["filters"] = _merge_filters(search.get("filters") or {}, conditional_filter.get("filters") or {})
                candidates.append(
                    _search_candidate(
                        filtered_search,
                        source="conditional_filter",
                        reason=conditional_filter.get("reason") or "Try a platform filter after preserving the unfiltered run.",
                    )
                )

    if "low_candidate_count" in flags or "no_listings" in flags or not candidates:
        for search in _remaining_planned_searches(goal_plan, selected_searches, limit=limit):
            candidates.append(
                _search_candidate(
                    search,
                    source="remaining_goal_plan",
                    reason="Use another planned query if the model decides current coverage is insufficient.",
                )
            )

    return _dedupe_search_candidates(candidates)[:limit]


def _search_candidate(search: dict, *, source: str, reason: str) -> dict:
    filters = _objective_search_filters(search.get("filters") or {})
    return {
        "platform": search.get("platform"),
        "query": search.get("query"),
        "filters": filters,
        "cli_filter_args": _filter_cli_args(filters),
        "source": source,
        "reason": reason,
        "alternative": bool(search.get("alternative")),
        "requires_model_confirmation": True,
        "execute_by_default": False,
    }


def _merge_filters(base: dict, override: dict) -> dict:
    merged = _objective_search_filters(base)
    merged.update({key: value for key, value in override.items() if value is not None})
    return _objective_search_filters(merged)


def _objective_search_filters(filters: dict) -> dict:
    allowed = {"min_price", "max_price", "area", "sort"}
    return {key: value for key, value in filters.items() if key in allowed}


def _filter_cli_args(filters: dict) -> list[str]:
    args: list[str] = []
    if "min_price" in filters:
        args.extend(["--min-price", str(filters["min_price"])])
    if "max_price" in filters:
        args.extend(["--max-price", str(filters["max_price"])])
    if filters.get("area"):
        args.extend(["--area", str(filters["area"])])
    if filters.get("sort"):
        args.extend(["--sort", str(filters["sort"])])
    return args


def _dedupe_search_candidates(candidates: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for candidate in candidates:
        key = (
            candidate.get("platform"),
            candidate.get("query"),
            tuple(sorted((candidate.get("filters") or {}).items())),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _dedupe_strings(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _suggest_next_actions(
    *,
    status: str,
    flags: list[str],
    run_summaries: list[dict],
    goal_plan: dict,
    candidate_pool: dict | None,
) -> list[dict]:
    if status == "not_executed":
        return [
            {
                "type": "execute_selected_searches",
                "priority": "high",
                "reason": "No platform search has been executed in this loop yet.",
            }
        ]
    if status == "blocked":
        return [
            {
                "type": "stop_for_safety",
                "priority": "high",
                "reason": "At least one search page appears access-blocked. Do not bypass verification or platform controls.",
            }
        ]

    actions: list[dict] = []
    run_ids = _run_ids_for_comparison(run_summaries, candidate_pool)
    if len(run_ids) >= 2:
        actions.append(
            {
                "type": "compare_runs",
                "priority": "high",
                "run_ids": run_ids[:5],
                "reason": "Multiple search runs exist for this goal. Compare local run quality before deciding whether filters, scrolling, or keyword changes improved the candidate pool.",
            }
        )

    if "target_size_mismatch_noise" in flags:
        actions.append(
            {
                "type": "revise_size_specific_terms",
                "priority": "medium",
                "reason": "A large share of candidates mention a non-target screen size. Prefer planned queries that include the target size before relying on price filters.",
            }
        )
    if "no_target_city_signal" in flags:
        actions.append(
            {
                "type": "consider_area_or_shipping_tradeoff",
                "priority": "medium",
                "reason": "No candidate currently carries the target-city signal. The model should decide whether to try an area filter, add city words to the query, or accept nearby/shipped listings for comparison.",
            }
        )

    if "high_noise_ratio" in flags or "no_listings" in flags:
        conditional_filters = goal_plan.get("conditional_filters", [])
        if conditional_filters:
            actions.append(
                {
                    "type": "consider_conditional_filter",
                    "priority": "medium",
                    "filters": _objective_search_filters(
                        conditional_filters[0].get("filters", {})
                    ),
                    "reason": conditional_filters[0].get("reason"),
                }
            )
    if "low_candidate_count" in flags or "no_listings" in flags:
        actions.append(
            {
                "type": "expand_or_revise_search_terms",
                "priority": "medium",
                "reason": "The candidate pool is small; the model should inspect remaining planned searches or generate seller-natural synonyms.",
            }
        )

    shortlist = (candidate_pool or {}).get("shortlist_for_next_evidence") or []
    missing_detail_ids = [
        item.get("listing_id")
        for item in shortlist
        if item.get("listing_id") is not None and not (item.get("collection_state") or {}).get("has_detail")
    ]
    ready_listing_ids = [
        item.get("listing_id")
        for item in shortlist
        if item.get("listing_id") is not None and _has_ready_evidence(item)
    ]
    detail_listing_ids = [
        item.get("listing_id")
        for item in shortlist
        if item.get("listing_id") is not None and (item.get("collection_state") or {}).get("has_detail")
    ]
    if missing_detail_ids:
        actions.append(
            {
                "type": "prepare_evidence",
                "priority": "high",
                "listing_ids": missing_detail_ids[:5],
                "reason": "Shortlisted candidates need saved detail evidence before final judgment; image/OCR is optional and requires a specific unresolved visual question.",
            }
        )
    if ready_listing_ids:
        actions.append(
            {
                "type": "build_evaluation_task",
                "priority": "high",
                "listing_ids": ready_listing_ids[:5],
                "reason": "These shortlisted candidates already have saved detail evidence, so the model can build an evaluation task; use image/OCR only for a named unresolved visual question.",
            }
        )
    if detail_listing_ids:
        actions.append(
            {
                "type": "inspect_recommendation_links",
                "priority": "medium",
                "listing_ids": detail_listing_ids[:5],
                "reason": "Captured Xianyu detail pages may contain related item links. The model can inspect them as optional expansion candidates when current coverage is thin or adjacent recommendations look useful.",
            }
        )

    if not actions:
        actions.append(
            {
                "type": "model_decide_next_step",
                "priority": "medium",
                "reason": "Search observations are usable; the model should decide whether to capture details, expand adjacent models, or stop searching.",
            }
        )
    return actions


def _user_calibration(*, goal_plan: dict, status: str, flags: list[str], coverage: dict) -> dict:
    questions = [
        question.strip()
        for question in goal_plan.get("clarification_questions", [])
        if isinstance(question, str) and question.strip()
    ]
    facts = goal_plan.get("interpreted_intent") or {}
    search_rounds = goal_plan.get("search_rounds") or []
    product_identity_unclear = facts.get("family") in {None, "generic"} and len(search_rounds) <= 1

    blocking_questions = []
    if product_identity_unclear and questions:
        blocking_questions.append(
            _calibration_question(
                question=questions.pop(0),
                reason="商品身份或品类太宽，继续自动采集可能会把不相关商品混进候选池。",
                ask_when="继续真实平台采集前",
                blocking=True,
            )
        )

    return {
        "policy": (
            "澄清问题用于校准偏好，不应默认阻塞首轮宽搜索；"
            "除非商品身份不清楚，Codex 应先收集平台证据，再用少量问题校准最终排序和推荐。"
        ),
        "stage": _calibration_stage(status=status, flags=flags, coverage=coverage),
        "should_block_collection": bool(blocking_questions),
        "blocking_questions": blocking_questions,
        "nonblocking_questions": [
            _calibration_question(
                question=question,
                reason=_calibration_reason(question),
                ask_when=_calibration_ask_when(question),
                blocking=False,
            )
            for question in questions[:4]
        ],
    }


def _calibration_question(*, question: str, reason: str, ask_when: str, blocking: bool) -> dict:
    return {
        "question": question,
        "reason": reason,
        "ask_when": ask_when,
        "blocking": blocking,
    }


def _calibration_stage(*, status: str, flags: list[str], coverage: dict) -> str:
    if status == "blocked":
        return "safety_blocked"
    if status == "not_executed":
        return "before_first_search"
    if "shortlist_needs_evidence" in flags:
        return "before_detail_evidence"
    if coverage.get("ready_shortlist_count", 0) > 0:
        return "before_final_evaluation"
    if "high_noise_ratio" in flags or "low_candidate_count" in flags:
        return "after_low_quality_search"
    return "after_first_search"


def _calibration_reason(question: str) -> str:
    if "相邻" in question or "M2" in question or "2020" in question:
        return "影响是否把相邻型号纳入横向比较，但不应阻塞首轮搜索。"
    if "自提" in question or "上海" in question or "外地" in question:
        return "影响同城优先、物流风险、验货方式和最终排序。"
    if "内存" in question or "32G" in question or "16G" in question:
        return "影响配置筛选、价格基准和性价比判断。"
    if "尺寸" in question or "14" in question or "16" in question or "27" in question:
        return "影响候选池边界和横向对比维度。"
    return "影响最终排序或出价建议，但通常可以先用平台证据缩小问题范围。"


def _calibration_ask_when(question: str) -> str:
    if "相邻" in question or "M2" in question or "2020" in question:
        return "相邻型号出现明显价格或成色优势时"
    if "自提" in question or "上海" in question or "外地" in question:
        return "候选里同时存在同城和外地高性价比商品时"
    if "内存" in question or "32G" in question or "16G" in question:
        return "不同内存配置价格差明显、会改变推荐排序时"
    return "首轮搜索后、最终推荐前"


def _run_ids_for_comparison(run_summaries: list[dict], candidate_pool: dict | None) -> list[int]:
    run_ids = [
        run_id
        for run_id in (candidate_pool or {}).get("run_ids", [])
        if isinstance(run_id, int)
    ]
    if not run_ids:
        run_ids = [
            summary.get("run_id")
            for summary in run_summaries
            if isinstance(summary.get("run_id"), int)
        ]
    result = []
    seen = set()
    for run_id in run_ids:
        if run_id in seen:
            continue
        seen.add(run_id)
        result.append(run_id)
    return result


def _target_size_refinement_searches(goal_plan: dict, selected_searches: list[dict], limit: int) -> list[dict]:
    facts = goal_plan.get("interpreted_intent") or {}
    target_sizes = [str(size) for size in facts.get("screen_sizes") or []]
    if not target_sizes:
        return []
    selected_keys = {_search_key(search) for search in selected_searches}
    result = []
    for search in goal_plan.get("search_rounds", []):
        if _search_key(search) in selected_keys:
            continue
        query = str(search.get("query") or "")
        padded_query = f" {query} "
        if any(f"{size}寸" in query or f" {size} " in padded_query for size in target_sizes):
            result.append(search)
        if len(result) >= limit:
            break
    return result


def _has_ready_evidence(candidate: dict) -> bool:
    state = candidate.get("collection_state") or {}
    return bool(state.get("has_detail"))


def _search_key(search: dict) -> tuple:
    filters = search.get("filters") or {}
    return (search.get("platform"), search.get("query"), tuple(sorted(filters.items())))


def _ratio(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total, 3)


def _int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
