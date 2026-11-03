from __future__ import annotations

from dataclasses import dataclass

from shopping_agent.candidate_pool import CandidatePoolOptions, build_candidate_pool
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    connect,
    fetch_listing_collection_states,
    fetch_listing_snapshots_for_run,
    fetch_queries_for_run,
    fetch_research_task,
    fetch_task_runs,
    fetch_unique_listing_ids_for_run,
    initialize,
)
from shopping_agent.extraction.listing_parser import parse_price_value
from shopping_agent.task_coverage import build_search_coverage


@dataclass
class DetailCandidateOptions:
    limit: int = 20


def build_detail_candidates(
    config: AppConfig,
    task_id: int,
    options: DetailCandidateOptions | None = None,
) -> dict:
    options = options or DetailCandidateOptions()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task = fetch_research_task(conn, task_id)
        if task is None:
            raise ValueError(f"Research task not found: {task_id}")
        task_runs = fetch_task_runs(conn, task_id)
        run_ids = [int(row["run_id"]) for row in task_runs]
        queries_by_run = {
            run_id: fetch_queries_for_run(conn, run_id) for run_id in run_ids
        }
        run_records = [
            {
                "run_id": run_id,
                "source_queries": queries_by_run.get(run_id, []),
            }
            for run_id in run_ids
        ]
        listing_ids_by_run = {
            run_id: fetch_unique_listing_ids_for_run(conn, run_id)
            for run_id in run_ids
        }
        search_coverage = build_search_coverage(run_records, listing_ids_by_run)
        ready_for_detail_selection = search_coverage["status"] in {
            "sufficient",
            "capped",
        }
        if not ready_for_detail_selection:
            return {
                "task_id": task_id,
                "coverage_status": search_coverage["status"],
                "suggested_action": search_coverage["suggested_action"],
                "ready_for_detail_selection": False,
                "eligible_count": 0,
                "returned_count": 0,
                "market_context": _market_context([]),
                "candidates": [],
            }
        occurrences_by_listing: dict[int, list[tuple[int, object]]] = {}
        for run_id in run_ids:
            first_by_listing = {}
            for row in fetch_listing_snapshots_for_run(conn, run_id):
                first_by_listing.setdefault(int(row["listing_id"]), row)
            for listing_id, row in first_by_listing.items():
                occurrences_by_listing.setdefault(listing_id, []).append((run_id, row))
        collection_states = fetch_listing_collection_states(
            conn, list(occurrences_by_listing)
        )

    duplicate_groups = _near_duplicate_groups(config, run_ids, task["goal"])
    duplicate_group_ids_by_listing = {
        int(listing_id): [str(group["group_id"])]
        for group in duplicate_groups
        for listing_id in group["listing_ids"]
    }
    candidates = []
    for listing_id, occurrences in occurrences_by_listing.items():
        state = collection_states.get(
            listing_id,
            {
                "detail_snapshot_count": 0,
                "valid_detail_snapshot_count": 0,
                "product_image_url_count": 0,
            },
        )
        if state["valid_detail_snapshot_count"] > 0:
            continue
        latest_run_id, latest_row = max(
            occurrences,
            key=lambda occurrence: (
                occurrence[1]["collected_at"] or "",
                occurrence[1]["id"],
            ),
        )
        source_run_ids = sorted({run_id for run_id, _ in occurrences})
        source_queries = list(
            dict.fromkeys(
                query
                for run_id in source_run_ids
                for query in queries_by_run.get(run_id, [])
            )
        )
        description = str(latest_row["description"] or "")
        title = str(latest_row["title"] or "")
        candidates.append(
            {
                "listing_id": listing_id,
                "url": latest_row["url"],
                "search_card": {
                    "title": title,
                    "description": description,
                    "price_text": latest_row["price_text"],
                    "price_value": parse_price_value(latest_row["price_text"]),
                    "location": latest_row["location"],
                    "seller_name": latest_row["seller_name"],
                    "condition": latest_row["search_condition"],
                    "collected_at": latest_row["collected_at"],
                },
                "provenance": {
                    "source_run_ids": source_run_ids,
                    "source_queries": source_queries,
                },
                "card_metadata": {
                    "description_chars": len(description),
                    "description_equals_title": _normalize_text(description)
                    == _normalize_text(title),
                    "price_band": "unknown",
                    "near_duplicate_group_ids": duplicate_group_ids_by_listing.get(
                        listing_id, []
                    ),
                },
                "collection_state": {
                    "has_detail": False,
                    "detail_snapshot_count": state["detail_snapshot_count"],
                    "product_image_url_count": state["product_image_url_count"],
                },
                "coverage_reasons": [],
            }
        )

    market_context = _market_context(candidates)
    _assign_price_bands(candidates, market_context)
    selected = _select_for_coverage(candidates, max(options.limit, 0))
    return {
        "task_id": task_id,
        "coverage_status": search_coverage["status"],
        "suggested_action": search_coverage["suggested_action"],
        "ready_for_detail_selection": True,
        "eligible_count": len(candidates),
        "returned_count": len(selected),
        "market_context": market_context,
        "candidates": selected,
    }


def _near_duplicate_groups(config: AppConfig, run_ids: list[int], goal: str) -> list[dict]:
    if not run_ids:
        return []
    pool = build_candidate_pool(
        config,
        run_ids=run_ids,
        options=CandidatePoolOptions(goal=goal, limit=600, shortlist_limit=0),
    )
    return list(pool.get("near_duplicate_groups") or [])


def _market_context(candidates: list[dict]) -> dict:
    prices = sorted(
        candidate["search_card"]["price_value"]
        for candidate in candidates
        if candidate["search_card"]["price_value"] is not None
    )
    if not prices:
        return {
            "unique_candidates": len(candidates),
            "priced_count": 0,
            "price_min": None,
            "price_p25": None,
            "price_median": None,
            "price_p75": None,
            "price_max": None,
        }
    return {
        "unique_candidates": len(candidates),
        "priced_count": len(prices),
        "price_min": prices[0],
        "price_p25": _quantile(prices, 0.25),
        "price_median": _quantile(prices, 0.5),
        "price_p75": _quantile(prices, 0.75),
        "price_max": prices[-1],
    }


def _quantile(values: list[int], fraction: float) -> int:
    if len(values) == 1:
        return values[0]
    return values[min(int(round(fraction * (len(values) - 1))), len(values) - 1)]


def _assign_price_bands(candidates: list[dict], market_context: dict) -> None:
    p25 = market_context["price_p25"]
    p75 = market_context["price_p75"]
    for candidate in candidates:
        price = candidate["search_card"]["price_value"]
        if price is None:
            band = "unknown"
        elif price <= p25:
            band = "low"
        elif price >= p75:
            band = "high"
        else:
            band = "mid"
        candidate["card_metadata"]["price_band"] = band


def _select_for_coverage(candidates: list[dict], limit: int) -> list[dict]:
    remaining = sorted(candidates, key=lambda candidate: candidate["listing_id"])
    selected = []
    covered_queries: set[str] = set()
    covered_bands: set[str] = set()
    covered_locations: set[str] = set()
    covered_completeness: set[str] = set()
    covered_duplicate_groups: set[str] = set()

    while remaining and len(selected) < limit:
        best = max(
            remaining,
            key=lambda candidate: (
                _coverage_gain(
                    candidate,
                    covered_queries,
                    covered_bands,
                    covered_locations,
                    covered_completeness,
                    covered_duplicate_groups,
                ),
                -candidate["listing_id"],
            ),
        )
        remaining.remove(best)
        reasons = _coverage_reasons(
            best,
            covered_queries,
            covered_bands,
            covered_locations,
            covered_completeness,
            covered_duplicate_groups,
        )
        best["coverage_reasons"] = reasons
        selected.append(best)
        covered_queries.update(best["provenance"]["source_queries"])
        covered_bands.add(best["card_metadata"]["price_band"])
        location = best["search_card"]["location"]
        if location:
            covered_locations.add(str(location))
        covered_completeness.add(_card_completeness(best))
        covered_duplicate_groups.update(
            best["card_metadata"]["near_duplicate_group_ids"]
        )
    return selected


def _coverage_gain(
    candidate: dict,
    covered_queries: set[str],
    covered_bands: set[str],
    covered_locations: set[str],
    covered_completeness: set[str],
    covered_duplicate_groups: set[str],
) -> int:
    queries = set(candidate["provenance"]["source_queries"])
    band = candidate["card_metadata"]["price_band"]
    location = candidate["search_card"]["location"]
    completeness = _card_completeness(candidate)
    duplicate_groups = set(candidate["card_metadata"]["near_duplicate_group_ids"])
    return (
        4 * len(queries - covered_queries)
        + (3 if band != "unknown" and band not in covered_bands else 0)
        + (1 if band == "unknown" and band not in covered_bands else 0)
        + (1 if location and str(location) not in covered_locations else 0)
        + (1 if completeness not in covered_completeness else 0)
        + (1 if duplicate_groups - covered_duplicate_groups else 0)
    )


def _coverage_reasons(
    candidate: dict,
    covered_queries: set[str],
    covered_bands: set[str],
    covered_locations: set[str],
    covered_completeness: set[str],
    covered_duplicate_groups: set[str],
) -> list[dict]:
    reasons = []
    for query in candidate["provenance"]["source_queries"]:
        if query not in covered_queries:
            reasons.append({"code": "query_coverage", "value": query})
    band = candidate["card_metadata"]["price_band"]
    if band not in covered_bands:
        reasons.append({"code": "price_band_coverage", "value": band})
    location = candidate["search_card"]["location"]
    if location and str(location) not in covered_locations:
        reasons.append({"code": "location_coverage", "value": str(location)})
    completeness = _card_completeness(candidate)
    if completeness not in covered_completeness:
        reasons.append({"code": "card_completeness_coverage", "value": completeness})
    for group_id in candidate["card_metadata"]["near_duplicate_group_ids"]:
        if group_id not in covered_duplicate_groups:
            reasons.append({"code": "near_duplicate_group_coverage", "value": group_id})
    return reasons


def _card_completeness(candidate: dict) -> str:
    card = candidate["search_card"]
    metadata = candidate["card_metadata"]
    if (
        not card["description"]
        or metadata["description_equals_title"]
        or card["price_value"] is None
        or card["location"] is None
    ):
        return "thin"
    return "complete"
def _normalize_text(value: str) -> str:
    return "".join(str(value or "").lower().split())
