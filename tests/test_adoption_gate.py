from __future__ import annotations

from shopping_agent.adoption_gate import evaluate_foldback_adoption


def _metrics(noise: float, useful: int) -> dict:
    return {"noise_ratio": noise, "useful_candidate_count": useful}


def test_foldback_that_lowers_noise_and_raises_useful_is_adopted() -> None:
    verdict = evaluate_foldback_adoption(
        baseline_run_id=1,
        foldback_run_id=2,
        baseline_metrics=_metrics(0.50, 10),
        foldback_metrics=_metrics(0.30, 14),
        query="better term",
    )
    assert verdict["adopted"] is True
    assert verdict["verdict"] == "adopted"
    assert verdict["noise_ratio_delta"] == -0.2
    assert verdict["useful_candidate_delta"] == 4


def test_foldback_that_worsens_noise_is_rejected() -> None:
    # Real run9-vs-run12 data: noise 0.533 -> 0.633, useful 14 -> 11.
    verdict = evaluate_foldback_adoption(
        baseline_run_id=9,
        foldback_run_id=12,
        baseline_metrics=_metrics(0.533, 14),
        foldback_metrics=_metrics(0.633, 11),
        query="MacBook Pro 13 M1 整机",
    )
    assert verdict["adopted"] is False
    assert verdict["verdict"] == "rejected"
    assert verdict["noise_ratio_delta"] == 0.1
    assert verdict["useful_candidate_delta"] == -3
    assert "made results worse" in verdict["reason"]
    assert "MacBook Pro 13 M1" in verdict["reason"]


def test_neutral_foldback_is_adopted() -> None:
    verdict = evaluate_foldback_adoption(
        baseline_run_id=1,
        foldback_run_id=2,
        baseline_metrics=_metrics(0.40, 10),
        foldback_metrics=_metrics(0.40, 10),
        query="same-quality term",
    )
    assert verdict["adopted"] is True
    assert verdict["verdict"] == "adopted"


def test_noise_up_but_useful_up_is_rejected() -> None:
    # Precision/recall trade-off: more useful candidates but also more noise.
    # Conservative gate rejects and surfaces it rather than auto-accepting.
    verdict = evaluate_foldback_adoption(
        baseline_run_id=1,
        foldback_run_id=2,
        baseline_metrics=_metrics(0.30, 10),
        foldback_metrics=_metrics(0.45, 13),
        query="trades precision for recall",
    )
    assert verdict["adopted"] is False
    assert verdict["verdict"] == "rejected"
    assert "noise rose" in verdict["reason"]
