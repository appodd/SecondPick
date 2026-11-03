"""Adoption gate for Codex-proposed foldback search terms.

A foldback term is only worth keeping in the workflow when the real run it
produced is at least as good as the audit run it was meant to improve. This
module compares a baseline (audit) run against a foldback run using the same
metrics compare-runs already produces, and returns a verdict the driving Codex
session can act on instead of blindly adopting every WINNING_TERM.
"""

from __future__ import annotations

from typing import Any


def evaluate_foldback_adoption(
    *,
    baseline_run_id: int,
    foldback_run_id: int,
    baseline_metrics: dict[str, Any],
    foldback_metrics: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    """Decide whether a foldback search term should be adopted or rejected.

    Conservative gate: adopt only when the foldback run does not increase noise
    AND does not reduce useful candidates relative to the baseline audit run.
    Precision/recall trade-offs are surfaced as a reason rather than auto-decided,
    so the driving model can still accept a recall cut when the stage calls for it.
    """
    baseline_noise = float(baseline_metrics.get("noise_ratio", 0.0))
    foldback_noise = float(foldback_metrics.get("noise_ratio", 0.0))
    baseline_useful = int(baseline_metrics.get("useful_candidate_count", 0))
    foldback_useful = int(foldback_metrics.get("useful_candidate_count", 0))
    noise_delta = round(foldback_noise - baseline_noise, 3)
    useful_delta = foldback_useful - baseline_useful

    adopted = noise_delta <= 0 and useful_delta >= 0
    if adopted:
        verdict = "adopted"
        if noise_delta < 0 and useful_delta > 0:
            reason = (
                f"Foldback '{query}' improved on the audit run: noise {baseline_noise:.3f}->"
                f"{foldback_noise:.3f} ({noise_delta:+.3f}), useful {baseline_useful}->"
                f"{foldback_useful} ({useful_delta:+}). Adopt into search_rounds."
            )
        else:
            reason = (
                f"Foldback '{query}' is at least as good as the audit run: noise {baseline_noise:.3f}->"
                f"{foldback_noise:.3f} ({noise_delta:+.3f}), useful {baseline_useful}->"
                f"{foldback_useful} ({useful_delta:+}). Adopt (neutral or positive)."
            )
    else:
        verdict = "rejected"
        parts = []
        if noise_delta > 0:
            parts.append(
                f"noise rose {baseline_noise:.3f}->{foldback_noise:.3f} ({noise_delta:+.3f})"
            )
        if useful_delta < 0:
            parts.append(
                f"useful candidates fell {baseline_useful}->{foldback_useful} ({useful_delta:+})"
            )
        reason = (
            f"Foldback '{query}' made results worse ({'; '.join(parts) or 'no improvement'}). "
            "Do NOT adopt; feed this failure back to the next subagent pass so it avoids the "
            "same term shape, and keep the audit run as the baseline."
        )

    return {
        "baseline_run_id": baseline_run_id,
        "foldback_run_id": foldback_run_id,
        "query": query,
        "verdict": verdict,
        "adopted": adopted,
        "noise_ratio_delta": noise_delta,
        "useful_candidate_delta": useful_delta,
        "baseline_noise_ratio": baseline_noise,
        "foldback_noise_ratio": foldback_noise,
        "baseline_useful_candidate_count": baseline_useful,
        "foldback_useful_candidate_count": foldback_useful,
        "reason": reason,
    }
