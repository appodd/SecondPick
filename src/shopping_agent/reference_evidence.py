from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_reference_evidence,
    connect,
    fetch_reference_evidence,
    initialize,
)
from shopping_agent.extraction.listing_parser import parse_price_value


SOURCE_TYPE_CHOICES = (
    "official_specs",
    "trusted_specs",
    "current_listing",
    "sold_history",
    "merchant_refurbished",
    "article_or_forum",
)

DEFAULT_EVIDENCE_LEVELS = {
    "official_specs": "spec_reference",
    "trusted_specs": "spec_reference",
    "current_listing": "A_external_current_listing_unverified",
    "sold_history": "B_recent_sold_or_history",
    "merchant_refurbished": "C_merchant_refurbished_or_shop",
    "article_or_forum": "D_background_reference",
}


@dataclass
class ReferenceEvidenceInput:
    source_type: str
    title: str
    url: str
    run_id: int | None = None
    listing_id: int | None = None
    goal: str | None = None
    platform: str | None = None
    price_text: str | None = None
    price_value: int | None = None
    currency: str = "CNY"
    evidence_level: str | None = None
    model_key: str | None = None
    spec_summary: str | None = None
    comparable_scope: str | None = None
    notes: str | None = None
    checked_at: str | None = None


def default_evidence_level(source_type: str) -> str:
    return DEFAULT_EVIDENCE_LEVELS.get(source_type, "D_background_reference")


def save_reference_evidence(config: AppConfig, evidence: ReferenceEvidenceInput) -> dict:
    initialize(config.database_path)
    price_value = evidence.price_value
    if price_value is None:
        price_value = parse_price_value(evidence.price_text)
    checked_at = evidence.checked_at or date.today().isoformat()
    evidence_level = evidence.evidence_level or default_evidence_level(evidence.source_type)
    with connect(config.database_path) as conn:
        evidence_id = add_reference_evidence(
            conn,
            run_id=evidence.run_id,
            listing_id=evidence.listing_id,
            goal=evidence.goal,
            source_type=evidence.source_type,
            platform=evidence.platform,
            title=evidence.title,
            url=evidence.url,
            price_text=evidence.price_text,
            price_value=price_value,
            currency=evidence.currency,
            evidence_level=evidence_level,
            model_key=evidence.model_key,
            spec_summary=evidence.spec_summary,
            comparable_scope=evidence.comparable_scope,
            notes=evidence.notes,
            checked_at=checked_at,
        )
    return {
        "id": evidence_id,
        "run_id": evidence.run_id,
        "listing_id": evidence.listing_id,
        "goal": evidence.goal,
        "source_type": evidence.source_type,
        "platform": evidence.platform,
        "title": evidence.title,
        "url": evidence.url,
        "price_text": evidence.price_text,
        "price_value": price_value,
        "currency": evidence.currency,
        "evidence_level": evidence_level,
        "model_key": evidence.model_key,
        "spec_summary": evidence.spec_summary,
        "comparable_scope": evidence.comparable_scope,
        "notes": evidence.notes,
        "checked_at": checked_at,
    }


def build_reference_evidence_summary(
    config: AppConfig,
    *,
    run_id: int | None = None,
    listing_id: int | None = None,
    goal: str | None = None,
    limit: int = 50,
) -> dict:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        rows = fetch_reference_evidence(
            conn,
            run_id=run_id,
            listing_id=listing_id,
            goal=goal,
            limit=limit,
        )
    entries = [_row_to_dict(row) for row in rows]
    return {
        "decision_owner": "llm",
        "is_final_recommendation": False,
        "source_scope": "model_recorded_reference_evidence",
        "filters": {
            "run_id": run_id,
            "listing_id": listing_id,
            "goal": goal,
            "limit": limit,
        },
        "reference_count": len(entries),
        "priced_sample_count": len([entry for entry in entries if entry["price_value"] is not None]),
        "source_type_counts": _counts(entry["source_type"] for entry in entries),
        "evidence_level_counts": _counts(entry["evidence_level"] for entry in entries),
        "price_summary_by_source_type": _price_group_summaries(entries, key="source_type"),
        "price_summary_by_evidence_level": _price_group_summaries(entries, key="evidence_level"),
        "official_spec_sources": [
            entry
            for entry in entries
            if entry["source_type"] in {"official_specs", "trusted_specs"}
        ],
        "market_price_sources": [
            entry for entry in entries if entry["price_value"] is not None
        ],
        "entries": entries,
        "notes": [
            "This ledger records reference evidence the model chose to save during evaluation.",
            "It is not a final price judgment, seller judgment, or recommendation.",
            "Use evidence_level, source_type, sample count, checked_at, comparable_scope, and notes before relying on a price band.",
            "Official specs and trusted product databases support identity/configuration checks; they are not market price samples unless priced.",
        ],
    }


def _row_to_dict(row: Any) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "listing_id": row["listing_id"],
        "goal": row["goal"],
        "source_type": row["source_type"],
        "platform": row["platform"],
        "title": row["title"],
        "url": row["url"],
        "price_text": row["price_text"],
        "price_value": row["price_value"],
        "currency": row["currency"],
        "evidence_level": row["evidence_level"],
        "model_key": row["model_key"],
        "spec_summary": row["spec_summary"],
        "comparable_scope": row["comparable_scope"],
        "notes": row["notes"],
        "checked_at": row["checked_at"],
        "created_at": row["created_at"],
    }


def _counts(values) -> list[dict]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return [
        {"value": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _price_group_summaries(entries: list[dict], *, key: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        if entry["price_value"] is None:
            continue
        group_key = str(entry.get(key) or "")
        if not group_key:
            continue
        groups.setdefault(group_key, []).append(entry)
    summaries = []
    for group_key, members in groups.items():
        summaries.append(
            {
                key: group_key,
                "sample_count": len(members),
                "price_summary": _price_summary(
                    [int(member["price_value"]) for member in members]
                ),
                "samples": [
                    {
                        "id": member["id"],
                        "source_type": member["source_type"],
                        "platform": member["platform"],
                        "title": member["title"],
                        "url": member["url"],
                        "price_text": member["price_text"],
                        "price_value": member["price_value"],
                        "checked_at": member["checked_at"],
                        "comparable_scope": member["comparable_scope"],
                    }
                    for member in members[:8]
                ],
            }
        )
    summaries.sort(
        key=lambda item: (
            -item["sample_count"],
            item["price_summary"]["median"] if item["price_summary"]["median"] is not None else 10**12,
            item[key],
        )
    )
    return summaries


def _price_summary(values: list[int]) -> dict:
    values = sorted(values)
    if not values:
        return {
            "count": 0,
            "min": None,
            "q1": None,
            "median": None,
            "q3": None,
            "max": None,
            "spread": None,
            "values": [],
        }
    return {
        "count": len(values),
        "min": values[0],
        "q1": _percentile(values, 0.25),
        "median": _percentile(values, 0.5),
        "q3": _percentile(values, 0.75),
        "max": values[-1],
        "spread": values[-1] - values[0],
        "values": values,
    }


def _percentile(values: list[int], fraction: float) -> int:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    weight = position - lower_index
    return int(round(values[lower_index] * (1 - weight) + values[upper_index] * weight))
