from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, HttpUrl


class StrEnum(str, Enum):
    """Small Python 3.9 compatible StrEnum replacement."""


class Platform(StrEnum):
    XIAN_YU = "xianyu"
    TAOBAO = "taobao"
    JD = "jd"
    ZHUANZHUAN = "zhuanzhuan"


class RecommendationLevel(StrEnum):
    STRONG_WATCH = "strong_watch"
    CONSIDER = "consider"
    INSUFFICIENT_INFO = "insufficient_info"
    NOT_RECOMMENDED = "not_recommended"
    HIGH_RISK = "high_risk"


class SearchQuery(BaseModel):
    raw_goal: str
    query_text: str
    city: str = "上海"
    platform: Platform
    created_at: datetime


class SearchResult(BaseModel):
    platform: Platform
    url: HttpUrl
    title: Optional[str] = None
    price_text: Optional[str] = None
    location: Optional[str] = None
    seller_name: Optional[str] = None


class ListingDetail(SearchResult):
    description: Optional[str] = None
    image_urls: list[HttpUrl] = []
    screenshot_path: Optional[Path] = None
    collected_at: datetime


class ImageAnalysis(BaseModel):
    image_path: Path
    ocr_text: str = ""
    detected_specs: dict[str, str] = {}
    risk_notes: list[str] = []
    confidence: Optional[float] = None


class ListingEvaluation(BaseModel):
    listing_url: HttpUrl
    recommendation: RecommendationLevel
    identity_confidence: float
    price_score: float
    condition_score: float
    seller_score: float
    transaction_score: float
    risks: list[str]
    questions_for_seller: list[str]
    suggested_offer_text: Optional[str] = None
