from __future__ import annotations

import re


def normalize_price_text(price_text: str | None) -> str | None:
    if price_text is None:
        return None
    return " ".join(price_text.split())


def parse_price_value(price_text: str | None) -> int | None:
    if not price_text:
        return None
    normalized = price_text.replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    multiplier = 10_000 if re.match(r"\s*万", normalized[match.end() :]) else 1
    return int(float(match.group(0)) * multiplier)
