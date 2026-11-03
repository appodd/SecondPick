from __future__ import annotations

from dataclasses import dataclass

from shopping_agent.config import AppConfig
from shopping_agent.evidence import ListingEvidenceBundle, build_listing_evidence
from shopping_agent.evaluation.consistency import ListingConsistencyReport, evaluate_listing_consistency


@dataclass
class ListingAnalysis:
    listing_id: int
    url: str
    price_text: str | None
    location: str | None
    seller_name: str | None
    description: str
    ocr_count: int
    evidence: ListingEvidenceBundle
    report: ListingConsistencyReport


def analyze_listing(config: AppConfig, listing_id: int) -> ListingAnalysis:
    evidence = build_listing_evidence(config, listing_id)
    report = evaluate_listing_consistency(evidence)
    return ListingAnalysis(
        listing_id=evidence.listing_id,
        url=evidence.url,
        price_text=evidence.price_text,
        location=evidence.location,
        seller_name=evidence.seller_name,
        description=evidence.description,
        ocr_count=sum(1 for item in evidence.ocr_evidence if item.ocr_text),
        evidence=evidence,
        report=report,
    )
