from __future__ import annotations

import re
from dataclasses import dataclass
from collections import Counter


@dataclass
class ProductImageCandidate:
    source_url: str
    normalized_key: str
    score: int


def select_xianyu_product_images(image_urls: list[str], max_images: int = 12) -> list[str]:
    candidates = [
        candidate
        for url in image_urls
        if (candidate := _candidate_from_url(url)) is not None
    ]
    dominant_owner = _dominant_owner_id([candidate.source_url for candidate in candidates])
    if dominant_owner is not None:
        candidates = [
            candidate
            for candidate in candidates
            if _owner_id(candidate.source_url) == dominant_owner
        ]
    best_by_key: dict[str, ProductImageCandidate] = {}
    for candidate in candidates:
        existing = best_by_key.get(candidate.normalized_key)
        if existing is None or candidate.score > existing.score:
            best_by_key[candidate.normalized_key] = candidate

    sorted_candidates = sorted(
        best_by_key.values(),
        key=lambda item: (-item.score, image_urls.index(item.source_url)),
    )
    return [candidate.source_url for candidate in sorted_candidates[:max_images]]


def _candidate_from_url(url: str) -> ProductImageCandidate | None:
    if "alicdn.com/bao/uploaded/" not in url:
        return None
    if "xy_item" not in url and "mtopupload" not in url and "fleamarket" not in url:
        return None
    if any(marker in url for marker in ("userheader", "sns_logo")):
        return None
    if any(marker in url for marker in ("_110x", "_220x", "_450x")):
        return None
    if "790x" not in url and "heic_Q90" not in url and "jpg_Q90" not in url:
        return None

    key = _normalized_image_key(url)
    if key is None:
        return None
    return ProductImageCandidate(source_url=url, normalized_key=key, score=_score_url(url))


def _dominant_owner_id(urls: list[str]) -> str | None:
    owner_ids = [_owner_id(url) for url in urls]
    owner_ids = [owner_id for owner_id in owner_ids if owner_id is not None]
    if not owner_ids:
        return None
    owner_id, count = Counter(owner_ids).most_common(1)[0]
    return owner_id if count >= 2 else None


def _owner_id(url: str) -> str | None:
    match = re.search(r"/bao/uploaded/i\d/(\d{6,})/", url)
    return match.group(1) if match else None


def _normalized_image_key(url: str) -> str | None:
    match = re.search(r"/([^/?]+?)_(?:\d+x|Q90|!!|\.jpg|\.heic|\.png)", url)
    if match:
        return match.group(1)
    match = re.search(r"/([^/?]+)$", url)
    return match.group(1) if match else None


def _score_url(url: str) -> int:
    score = 0
    if "xy_item" in url:
        score += 50
    if "fleamarket" in url:
        score += 45
    if "790x" in url:
        score += 30
    if "_Q90" in url or "heic_Q90" in url:
        score += 20
    if "220x" in url or "110x" in url:
        score -= 20
    if "450x" in url:
        score -= 5
    if "mtopupload" in url:
        score -= 10
    return score
