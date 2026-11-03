# Detail Investigation

## When To Read

Read when a question about selected listings depends on full description, structured attributes, seller history fields, other active listings, image URLs, or a conflict not answerable from search cards.

## Stage Goal

Reuse saved deep evidence first, then capture a listing detail only when the unresolved question can materially change the answer. One capture should preserve a broad reusable detail snapshot for later follow-ups.

## Minimum Data Prerequisites

A saved read needs a task or run scope plus one or more in-scope listing IDs. A live capture needs a selected URL or run and the account-risk acknowledgement. Keep live detail collection sequential and visible.

## Reuse Saved Evidence

Read selected saved evidence before opening Xianyu. A valid previous snapshot can answer later questions even if a newer attempt was blocked. Do not recapture merely to refresh facts that are already adequate.

## Canonical Commands

```powershell
python -m shopping_agent.cli candidate-evidence --task-id 8 --listing-id 3259 --listing-id 3268 --pretty
python -m shopping_agent.cli candidate-evidence --run-id 62 --listing-id 3259 --raw-text-chars 1200 --pretty
python -m shopping_agent.cli capture-detail --url "https://www.goofish.com/item?id=123" --run-id 62 --task-id 8 --wait-ms 5000 --i-understand-account-risk
python -m shopping_agent.cli capture-detail --run-id 62 --limit 2 --task-id 8 --wait-ms 5000 --i-understand-account-risk
```

## Output And Evidence Semantics

Preserve provenance: `search_card` is discovery evidence; `seller_entered_attribute` and seller description are seller claims; `platform_seller_field` is a platform-presented signal; `detail_dom_fallback` is a lower-confidence extraction fallback. Keep `evidence_conflicts` explicit instead of silently choosing the most favorable statement.

Captured, blocked, and not-captured statuses are distinct. A protection page is not product evidence. Account age, sold count, credit, real-name status, and response rate do not establish trustworthiness or seller type. Missing seller fields likewise do not prove a new or personal seller.

## Exit Conditions

Exit when saved or newly captured detail answers the named question, or when access protection prevents collection. Do not continue into images, OCR, external lookup, or additional listings without a concrete remaining question.

## Related Stages

Candidate review selects listing IDs and states the gap. Visual evidence handles concrete image questions. External verification checks claims that require an independent source.
