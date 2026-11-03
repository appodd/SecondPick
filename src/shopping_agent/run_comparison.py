from __future__ import annotations

from shopping_agent.region_preference import region_preference

from dataclasses import dataclass

from shopping_agent.candidate_pool import CandidatePoolOptions, build_candidate_pool
from shopping_agent.config import AppConfig
from shopping_agent.run_summary import RunSummaryOptions, build_run_summary


NOISE_SIGNAL_KEYS = (
    "likely_accessory_or_parts",
    "likely_service_listing",
    "likely_non_target_size",
    "suspicious_low_price_for_target",
)


@dataclass
class RunComparisonOptions:
    goal: str | None = None
    target_city: str | None = None
    listing_limit: int = 80
    shortlist_limit: int = 12


def build_run_comparison(
    config: AppConfig,
    run_ids: list[int],
    options: RunComparisonOptions | None = None,
) -> dict:
    options = options or RunComparisonOptions()
    run_metrics = [
        _build_single_run_metrics(config, run_id=run_id, options=options)
        for run_id in run_ids
    ]
    return {
        "goal": options.goal,
        "target_city": region_preference(options.goal, explicit_city=options.target_city)['city'] or '',
        "run_ids": run_ids,
        "decision_owner": "llm",
        "is_final_recommendation": False,
        "notes": [
            "This comparison measures search-run quality only; it is not a purchase recommendation.",
            "Use it to decide whether a web filter, deeper scroll, broader keyword, or adjacent model search improved the candidate pool.",
            "A lower noise ratio or higher useful-candidate count is evidence for the LLM, not a hard rule.",
        ],
        "run_metrics": run_metrics,
        "relative_to_first_run": _relative_to_first_run(run_metrics),
        "metric_leaders": _metric_leaders(run_metrics),
        "suggested_llm_checks": [
            "Compare representative listing snapshots before trusting any web filter.",
            "If a filtered run has fewer candidates but much lower noise, decide whether recall or precision matters more for the user's current stage.",
            "If target-city count is low, consider a city/area filter or accept nearby shipping/inspection options.",
            "If useful candidates are still low, revise keywords or inspect detail-page recommendation links instead of only scrolling deeper.",
        ],
    }


def _build_single_run_metrics(config: AppConfig, *, run_id: int, options: RunComparisonOptions) -> dict:
    summary = build_run_summary(
        config,
        run_id=run_id,
        options=RunSummaryOptions(listing_limit=options.listing_limit),
    )
    pool = build_candidate_pool(
        config,
        run_ids=[run_id],
        options=CandidatePoolOptions(
            goal=options.goal,
            target_city=region_preference(options.goal, explicit_city=options.target_city)['city'] or '',
            limit=options.listing_limit,
            shortlist_limit=options.shortlist_limit,
        ),
    )
    candidates = pool["all_candidates"]
    signal_counts = _signal_counts(candidates)
    noisy_count = _noisy_candidate_count(candidates)
    candidate_count = len(candidates)
    quality = summary["result_quality"]
    prices = sorted(
        candidate["price_value"]
        for candidate in candidates
        if candidate.get("price_value") is not None
    )
    return {
        "run_id": run_id,
        "queries": _queries(summary),
        "page_count": quality["page_count"],
        "access_blocked": quality["access_blocked"],
        "listing_count": quality["listing_count"],
        "unique_candidate_count": candidate_count,
        "shortlist_count": len(pool["shortlist_for_next_evidence"]),
        "priced_listing_count": quality["priced_listing_count"],
        "located_listing_count": quality["located_listing_count"],
        "priced_listing_ratio": quality["priced_listing_ratio"],
        "located_listing_ratio": quality["located_listing_ratio"],
        "target_city_count": signal_counts["target_city_hint"],
        "noisy_candidate_count": noisy_count,
        "noise_ratio": _ratio(noisy_count, candidate_count),
        "useful_candidate_count": max(candidate_count - noisy_count, 0),
        "signal_counts": signal_counts,
        "price_stats": _price_stats(prices),
        "top_listing_ids": [candidate["listing_id"] for candidate in candidates[:5]],
    }


def _queries(summary: dict) -> list[str]:
    queries = []
    for page in summary.get("pages", []):
        query = page.get("query")
        if query and query not in queries:
            queries.append(query)
    return queries


def _signal_counts(candidates: list[dict]) -> dict:
    keys = ("target_city_hint", *NOISE_SIGNAL_KEYS)
    return {
        key: sum(1 for candidate in candidates if (candidate.get("signals") or {}).get(key))
        for key in keys
    }


def _noisy_candidate_count(candidates: list[dict]) -> int:
    return sum(
        1
        for candidate in candidates
        if any((candidate.get("signals") or {}).get(key) for key in NOISE_SIGNAL_KEYS)
    )


def _price_stats(prices: list[int]) -> dict:
    if not prices:
        return {"count": 0, "min": None, "median": None, "max": None}
    middle = len(prices) // 2
    if len(prices) % 2:
        median = prices[middle]
    else:
        median = int((prices[middle - 1] + prices[middle]) / 2)
    return {
        "count": len(prices),
        "min": prices[0],
        "median": median,
        "max": prices[-1],
    }


def _relative_to_first_run(run_metrics: list[dict]) -> list[dict]:
    if not run_metrics:
        return []
    baseline = run_metrics[0]
    return [
        {
            "run_id": metrics["run_id"],
            "unique_candidate_delta": metrics["unique_candidate_count"] - baseline["unique_candidate_count"],
            "useful_candidate_delta": metrics["useful_candidate_count"] - baseline["useful_candidate_count"],
            "target_city_delta": metrics["target_city_count"] - baseline["target_city_count"],
            "noise_ratio_delta": round(metrics["noise_ratio"] - baseline["noise_ratio"], 3),
            "priced_listing_ratio_delta": round(metrics["priced_listing_ratio"] - baseline["priced_listing_ratio"], 3),
            "located_listing_ratio_delta": round(metrics["located_listing_ratio"] - baseline["located_listing_ratio"], 3),
        }
        for metrics in run_metrics[1:]
    ]


def _metric_leaders(run_metrics: list[dict]) -> dict:
    return {
        "highest_unique_candidate_count_run_id": _leader(run_metrics, "unique_candidate_count"),
        "highest_useful_candidate_count_run_id": _leader(run_metrics, "useful_candidate_count"),
        "highest_target_city_count_run_id": _leader(run_metrics, "target_city_count"),
        "lowest_noise_ratio_run_id": _leader(run_metrics, "noise_ratio", reverse=False),
    }


def _leader(run_metrics: list[dict], key: str, *, reverse: bool = True) -> int | None:
    if not run_metrics:
        return None
    sorted_metrics = sorted(run_metrics, key=lambda item: item[key], reverse=reverse)
    return sorted_metrics[0]["run_id"]


def _ratio(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total, 3)
