from __future__ import annotations


TARGET_MIN = 300
TARGET_MAX = 600
MARGINAL_GAIN_THRESHOLD = 0.1


def build_search_coverage(
    run_records: list[dict],
    listing_ids_by_run: dict[int, set[int]],
) -> dict:
    cumulative_listing_ids: set[int] = set()
    run_coverage = []
    low_gain_streak = 0

    for run in run_records:
        run_id = int(run["run_id"])
        listing_ids = set(listing_ids_by_run.get(run_id, set()))
        previous_count = len(cumulative_listing_ids)
        new_listing_ids = listing_ids - cumulative_listing_ids
        cumulative_listing_ids.update(listing_ids)
        new_unique_ratio = (
            round(len(new_listing_ids) / previous_count, 4)
            if previous_count > 0
            else None
        )
        if new_unique_ratio is not None and new_unique_ratio < MARGINAL_GAIN_THRESHOLD:
            low_gain_streak += 1
        elif new_unique_ratio is not None:
            low_gain_streak = 0

        run_coverage.append(
            {
                "run_id": run_id,
                "source_queries": list(run.get("source_queries") or []),
                "unique_in_run": len(listing_ids),
                "new_unique_count": len(new_listing_ids),
                "cumulative_unique_count": len(cumulative_listing_ids),
                "new_unique_ratio": new_unique_ratio,
            }
        )

    unique_candidates = len(cumulative_listing_ids)
    if unique_candidates >= TARGET_MAX:
        status = "capped"
    elif unique_candidates < TARGET_MIN:
        status = "collecting"
    elif low_gain_streak >= 2:
        status = "sufficient"
    else:
        status = "expanding"

    return {
        "status": status,
        "unique_candidates": unique_candidates,
        "target_min": TARGET_MIN,
        "target_max": TARGET_MAX,
        "marginal_gain_threshold": MARGINAL_GAIN_THRESHOLD,
        "low_gain_streak": low_gain_streak,
        "suggested_action": (
            "stop_expansion" if status in {"sufficient", "capped"} else "continue_search"
        ),
        "runs": run_coverage,
    }
