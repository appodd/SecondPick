# Search Discovery

## When To Read

Read when no saved evidence covers the effective goal, or when an observable quality failure justifies one correction search. Do not read merely because the user changed a preference that existing candidates may already satisfy.

## Stage Goal

Perform one effective large-scale discovery search using a concise product identity. Search cards discover candidates; this stage does not rank them or open their details.

## Minimum Data Prerequisites

Know the platform, concise identity query, and task ID when the run belongs to a task. The query should contain brand, model, generation, and necessary form factor, not the full conversational goal. Budget and location may use supported platform filters instead of bloating query text.

## Reuse Saved Evidence

Reuse a matching completed run. Search again only when there is no usable scope or a correction search is supported by evidence such as target-model absence, accessory/service domination, empty required location, too few usable candidates, or an evidently wrong query.

## Canonical Commands

```powershell
python -m shopping_agent.cli spike-search xianyu "MacBook Air M2" --max-pages 3 --task-id 8 --wait-ms 5000 --i-understand-account-risk
python -m shopping_agent.cli spike-search xianyu "R9000P 2023 4060" --min-price 5000 --max-price 7000 --area 上海 --max-pages 3 --task-id 9 --wait-ms 5000 --i-understand-account-risk
```

Never add `--headless` for real Xianyu collection. Real searches require a visible browser, sequential access, explicit account-risk acknowledgement, and the persistent Python-enforced minimum interval of 1800 seconds between Xianyu search attempts.

## Output And Evidence Semantics

A completed run contains saved search-card observations and capture status. Search-card title, description, price, location, condition, and seller name remain platform or seller-presented facts. A successful collection does not prove that every candidate is relevant or genuine.

A correction search replaces a known-bad discovery scope for immediate review; do not merge the bad run merely to inflate coverage. During cooldown, explain the limitation and work from saved evidence rather than retrying.

## Exit Conditions

Exit after one usable run. Allow one correction search only after naming the observable quality gap and only when cooldown permits. Stop immediately on any login, CAPTCHA, rate-limit, or access-protection signal.

## Related Stages

Candidate review reads the resulting cards. Deep research owns user-requested multi-run expansion; detail investigation owns selected listing pages.
