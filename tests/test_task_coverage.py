from __future__ import annotations

from shopping_agent.task_coverage import build_search_coverage


def _run(run_id: int, queries: list[str]) -> dict:
    return {"run_id": run_id, "source_queries": queries}


def test_search_coverage_calculates_cross_run_marginal_gain() -> None:
    coverage = build_search_coverage(
        [_run(1, ["R9000P"]), _run(2, ["R9000P 4060"])],
        {1: {1, 2, 3}, 2: {3, 4}},
    )

    assert coverage["unique_candidates"] == 4
    assert coverage["status"] == "collecting"
    assert coverage["runs"] == [
        {
            "run_id": 1,
            "source_queries": ["R9000P"],
            "unique_in_run": 3,
            "new_unique_count": 3,
            "cumulative_unique_count": 3,
            "new_unique_ratio": None,
        },
        {
            "run_id": 2,
            "source_queries": ["R9000P 4060"],
            "unique_in_run": 2,
            "new_unique_count": 1,
            "cumulative_unique_count": 4,
            "new_unique_ratio": 0.3333,
        },
    ]


def test_search_coverage_is_sufficient_after_two_low_gain_runs() -> None:
    baseline = set(range(1, 301))
    coverage = build_search_coverage(
        [_run(1, ["baseline"]), _run(2, ["variant-a"]), _run(3, ["variant-b"])],
        {
            1: baseline,
            2: set(range(301, 321)),
            3: set(range(321, 329)),
        },
    )

    assert coverage["unique_candidates"] == 328
    assert coverage["low_gain_streak"] == 2
    assert coverage["status"] == "sufficient"


def test_search_coverage_caps_at_six_hundred() -> None:
    coverage = build_search_coverage(
        [_run(1, ["baseline"])],
        {1: set(range(600))},
    )

    assert coverage["unique_candidates"] == 600
    assert coverage["status"] == "capped"


def test_search_coverage_expands_after_target_with_high_gain() -> None:
    coverage = build_search_coverage(
        [_run(1, ["baseline"]), _run(2, ["variant"])],
        {1: set(range(300)), 2: set(range(300, 350))},
    )

    assert coverage["status"] == "expanding"
    assert coverage["low_gain_streak"] == 0
