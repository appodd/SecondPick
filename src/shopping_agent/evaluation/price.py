from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Small Python 3.9 compatible StrEnum replacement."""


class PriceEvidenceLevel(StrEnum):
    CURRENT_SAME_CONFIG = "A"
    RECENT_SOLD_OR_HISTORY = "B"
    SHOP_USED_OR_REFURBISHED = "C"
    ARTICLE_OR_OLD_REFERENCE = "D"
