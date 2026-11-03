# Deep Research

## When To Read

Read only when the user explicitly asks for broader or more complete market coverage, or asks whether additional distinct searches are still producing useful new candidates.

## Stage Goal

Expand a task across meaningfully distinct runs, measure cumulative unique coverage and marginal gain, and stop when additional platform access has little value or the coverage ceiling is reached.

## Minimum Data Prerequisites

Know the task's current runs, effective goal, cumulative unique count, prior query identities, and per-run gains. New searches still follow the discovery safety and cooldown rules.

## Reuse Saved Evidence

Compare saved runs before adding another. Design a query that covers a genuine missing identity, generation, form factor, or terminology branch instead of repeating the same broad request.

## Canonical Commands

```powershell
python -m shopping_agent.cli compare-runs --run-id 61 --run-id 62 --goal "上海找一台二手相机机身" --target-city 上海 --listing-limit 80 --shortlist-limit 12 --pretty
```

Run comparison is optional and should be used only when its result changes whether or how to expand. Actual additional searches follow the search-discovery reference rather than being duplicated here.

## Output And Evidence Semantics

Cross-run counts are deduplicated by listing identity. Report cumulative unique coverage, each run's new unique count, and its marginal gain. A repeated listing is provenance, not a new candidate.

The long-horizon target is 300-600 unique candidates, but it is never a first-answer gate. After useful early answers, low marginal gain across consecutive distinct runs supports stopping; stop expansion at 600. Counts measure coverage, not candidate quality.

## Exit Conditions

Exit after at most two additional searches before the next user-visible update, when consecutive gains are low, when cooldown or protection blocks access, when the user's coverage question is answered, or at 600 unique candidates.

## Related Stages

Search discovery owns each real search. Candidate review performs semantic reassessment after expansion. Deep research does not automatically trigger details, media, or OCR.
