from __future__ import annotations

from shopping_agent.models import ListingEvaluation, RecommendationLevel


def classify_recommendation(evaluation: ListingEvaluation) -> RecommendationLevel:
    if evaluation.risks and evaluation.price_score < 0.3:
        return RecommendationLevel.HIGH_RISK
    if evaluation.identity_confidence < 0.5:
        return RecommendationLevel.INSUFFICIENT_INFO
    if evaluation.price_score >= 0.75 and evaluation.seller_score >= 0.6:
        return RecommendationLevel.STRONG_WATCH
    return RecommendationLevel.CONSIDER
