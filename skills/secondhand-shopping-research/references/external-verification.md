# External Verification

## When To Read

Read when the current answer requires an independent specification, release fact, compatibility fact, or other claim that saved marketplace evidence cannot establish.

## Stage Goal

Find and, when useful for later conversation, persist a bounded external reference. Prefer official primary sources for product specifications and clearly distinguish them from marketplace or editorial sources.

## Minimum Data Prerequisites

Know the exact claim to verify and the product identity involved. Persistence needs a source URL, title, source type, and enough task/run/listing context to explain what the reference supports.

## Reuse Saved Evidence

Inspect previously saved references for the same listing, run, or exact goal before web search. Do not repeat a lookup when a current authoritative source already resolves the claim.

## Canonical Commands

```powershell
python -m shopping_agent.cli reference-list --listing-id 3259 --limit 20 --pretty
python -m shopping_agent.cli reference-add --listing-id 3259 --source-type official_spec --platform lenovo --title "R9000P 2023 product specification" --url "https://example.com/official-spec" --spec-summary "Official configuration options" --comparable-scope "Checks whether the claimed CPU and GPU combination existed" --pretty
```

Use the Runtime's available web search only for the specific unresolved claim. Do not start collecting from additional secondhand marketplaces unless the user explicitly expands platform scope.

## Output And Evidence Semantics

Official documentation can establish published specifications or compatibility, not the condition or identity of the physical unit being sold. Seller claims remain seller claims even when a model family supports that configuration. Editorial, retailer, forum, and cached sources must be labeled according to their actual authority and date.

A failed search leaves a claim unverified; it does not prove the information is false or nonexistent.

## Exit Conditions

Exit when an adequate independent source resolves the named claim, when saved sources already suffice, or when no suitable source is available. Report source limitations and do not broaden the search without a new question.

## Related Stages

Detail investigation identifies seller claims and conflicts. Candidate review may use verified family-level facts for interpretation, while keeping unit-level conclusions separate.
