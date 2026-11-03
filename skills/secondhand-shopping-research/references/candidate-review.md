# Candidate Review

## When To Read

Read when the current question requires reviewing all saved candidates in a task/run scope, comparing options semantically, or applying explicit deterministic constraints.

## Stage Goal

Let Codex inspect every deduplicated compact search card exactly once, then judge product identity, relevance, tradeoffs, and which listings or evidence gaps deserve attention. Python must not choose representative products.

## Minimum Data Prerequisites

Use exactly one task scope or one or more run IDs. Keep that scope unchanged for the complete candidate read. A mechanical query requires run IDs plus user-stated filter conditions.

## Reuse Saved Evidence

Read saved cards before requesting details or new platform access. For an unchanged scope, call `candidate-index` once without `--limit`; this returns every deduplicated compact card and must not be followed by overlapping alternate reads.

## Canonical Commands

```powershell
python -m shopping_agent.cli candidate-index --run-id 62 --pretty
python -m shopping_agent.cli query-candidates --run-id 62 --min-price 5500 --max-price 7200 --location 上海 --seller-sold-max 50 --text-exclude 维修 --text-scope title --text-scope search_description --sort price_asc --limit 40 --pretty
```

Use one combined mechanical query for one unchanged scope and one set of known constraints. It may filter price, price ratio, location, saved condition, seller sold count, credit, real-name status, listing IDs, damage keywords, and text fields. It is not a semantic product classifier.

If the answer names, compares, explains, or assesses candidates, it must make one complete `candidate-index` call before `query-candidates`; a mechanical query may then narrow the already reviewed scope. Direct `query-candidates` without an index is allowed only for a strictly mechanical count/list request with no semantic comparison.

For one unchanged scope, make at most one `query-candidates` call. Combine all known mechanical constraints in it; do not split price bands or refine the same scope with overlapping follow-up queries.

## Output And Evidence Semantics

`deduplicated_count` is the unique scope before filters. In the canonical full response, `returned_count` equals `deduplicated_count`, every candidate appears exactly once, `page.has_more=false`, and `page.next_cursor=null`. Explicit `--limit` enables optional diagnostic pagination; its cursor remains bound to `scope_revision`, and stale or malformed cursors must be rejected rather than silently reused.

For mechanical results, `eligible_count` is every match before the requested result limit, while `returned_count` is the displayed subset. Cross-run provenance is retained and a listing is never counted once per source run.

`search_description=null` with `search_description_status=redundant_with_title` means the locally saved description repeated the title, so duplicate text was omitted. It does not prove that the platform exposed no description.

Keywords and seller-volume fields are observations only. They do not prove damage, repair history, authenticity, seller type, reliability, or value.

## Exit Conditions

Exit when the complete declared scope has been reviewed and current cards answer the question, or when a small named set of material evidence gaps has been identified. Do not fetch deeper evidence by default.

## Related Stages

Task memory supplies the effective goal. Detail investigation resolves listing-specific gaps. Search discovery is used only when the scope itself is inadequate; deep research is used only for explicit broader coverage.
