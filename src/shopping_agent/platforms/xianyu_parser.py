from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Iterable


@dataclass
class ParsedXianyuListing:
    description: str
    price_text: str | None
    location: str | None
    condition: str | None
    brand: str | None
    service_tags: list[str]
    interest_text: str | None
    published_text: str | None
    url: str | None = None
    title: str | None = None
    seller_name: str | None = None


PROVINCES = {
    "上海",
    "北京",
    "广东",
    "江苏",
    "浙江",
    "山东",
    "重庆",
    "四川",
    "福建",
    "湖北",
    "湖南",
    "河南",
    "河北",
    "安徽",
    "江西",
    "辽宁",
    "陕西",
    "天津",
    "云南",
    "广西",
    "贵州",
    "山西",
    "吉林",
    "黑龙江",
    "内蒙古",
    "海南",
    "甘肃",
    "新疆",
    "宁夏",
    "青海",
    "西藏",
    "香港",
    "澳门",
    "台湾",
}

CONDITION_MARKERS = {
    "全新",
    "几乎全新",
    "轻微使用痕迹",
    "明显使用痕迹",
}

SERVICE_MARKERS = {
    "功能完好无维修",
    "验货宝",
    "验号担保",
    "包邮",
    "回复超快",
    "百分百好评",
}


def parse_xianyu_api_items(api_json: dict) -> list[ParsedXianyuListing]:
    """Parse listings from the Xianyu PC search MTOP JSON response.

    The search API (mtop.taobao.idlemtopsearch.pc.search) returns a structured
    resultList where each item carries itemId, price, title, area, seller and
    tags directly. This avoids DOM scraping and its dependence on CSS-module
    hashes and the virtualized-list scroll recycling.
    """
    data = (api_json or {}).get("data") or {}
    result_list = data.get("resultList") or []
    listings: list[ParsedXianyuListing] = []
    seen_item_ids: set[str] = set()
    for entry in result_list:
        item_main = ((entry.get("data") or {}).get("item") or {}).get("main") or {}
        ex = item_main.get("exContent") or {}
        item_id = ex.get("itemId")
        if not item_id or item_id in seen_item_ids:
            continue
        seen_item_ids.add(item_id)
        title = _normalize_space(ex.get("title") or "")
        description = _normalize_space(ex.get("description") or ex.get("desc") or title)
        price_text = _api_price_text(ex.get("price"))
        location = ex.get("area")
        condition = _api_condition(ex.get("fishTags"))
        url = f"https://www.goofish.com/item?id={item_id}"
        interest_text = ex.get("want") or None
        listings.append(
            ParsedXianyuListing(
                description=description,
                price_text=price_text,
                location=location,
                condition=condition,
                brand=None,
                service_tags=[],
                interest_text=interest_text or None,
                published_text=None,
                url=url,
                title=title or None,
                seller_name=_api_seller_name(ex),
            )
        )
    return listings


def _api_seller_name(ex_content: dict) -> str | None:
    value = (
        ex_content.get("userNickName")
        or ex_content.get("userNick")
        or ex_content.get("sellerNick")
    )
    normalized = _normalize_space(str(value or ""))
    return normalized or None


def _api_price_text(price_segments: list | None) -> str | None:
    """Join price rich-text segments (sign + integer) into e.g. '¥2599'."""
    if not price_segments:
        return None
    parts = [str(seg.get("text") or "") for seg in price_segments if isinstance(seg, dict)]
    joined = "".join(parts).strip()
    return joined or None


def _api_condition(fish_tags: dict | None) -> str | None:
    """Extract a human-readable condition label from fishTags tag lists.

    fishTags groups tags by row (r1..r5); each row has tagList entries whose
    content may carry condition words. Return the first known condition marker.
    """
    if not fish_tags:
        return None
    # Longest markers first so "几乎全新" is not shadowed by its substring "全新".
    markers = sorted(CONDITION_MARKERS, key=len, reverse=True)
    for row in ("r1", "r2", "r3", "r4", "r5"):
        tag_list = (fish_tags.get(row) or {}).get("tagList") or []
        for tag in tag_list:
            content = ((tag.get("data") or {}).get("content")) or ""
            for marker in markers:
                if marker in content:
                    return marker
    return None


def parse_xianyu_html_cards(html: str) -> list[ParsedXianyuListing]:
    """Parse listing cards from Xianyu search HTML.

    The visible text parser is only a fallback. Search pages contain each listing
    link and summary inside one anchor card, so card-local parsing avoids pairing
    the Nth text block with the Nth global link.
    """

    parser = _XianyuCardParser()
    parser.feed(html)
    parser.close()
    listings: list[ParsedXianyuListing] = []
    seen_urls: set[str] = set()
    for card in parser.cards:
        parsed = _parse_card(card)
        if parsed is None or parsed.url is None or parsed.url in seen_urls:
            continue
        listings.append(parsed)
        seen_urls.add(parsed.url)
    return listings


def parse_xianyu_visible_text(visible_text: str) -> list[ParsedXianyuListing]:
    lines = [line.strip() for line in visible_text.splitlines() if line.strip()]
    start = _find_results_start(lines)
    if start is None:
        return []

    listings: list[ParsedXianyuListing] = []
    current: list[str] = []
    for line in lines[start:]:
        if line == "¥":
            if current:
                current.append(line)
            continue
        if current and _looks_like_new_listing_start(line, current):
            parsed = _parse_listing_block(current)
            if parsed is not None:
                listings.append(parsed)
            current = [line]
        else:
            current.append(line)

    if current:
        parsed = _parse_listing_block(current)
        if parsed is not None:
            listings.append(parsed)

    return listings


def _find_results_start(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line in {"转卖", "严选"}:
            return index + 1
    for index, line in enumerate(lines):
        if line.startswith("苹果") or line.lower().startswith(("imac", "apple")):
            return index
    return None


def _looks_like_new_listing_start(line: str, current: list[str]) -> bool:
    return _contains_price(current) and _looks_like_description(line)


def _contains_price(lines: Iterable[str]) -> bool:
    previous_was_yen = False
    for line in lines:
        if line == "¥":
            previous_was_yen = True
            continue
        if previous_was_yen and line.replace(".", "", 1).isdigit():
            return True
        previous_was_yen = False
    return False


def _looks_like_description(line: str) -> bool:
    lowered = line.lower()
    markers = ["imac", "苹果", "apple", "一体机", "27寸", "27 寸"]
    return any(marker in lowered for marker in markers) and not line.startswith(("¥", "累计降价"))


def _parse_listing_block(lines: list[str]) -> ParsedXianyuListing | None:
    price_index = _find_price_index(lines)
    if price_index is None:
        return None

    description_lines = lines[: price_index - 1] if price_index > 0 and lines[price_index - 1] == "¥" else lines[:price_index]
    description = " ".join(_drop_metadata(description_lines)).strip()
    if not description:
        return None

    price_text = lines[price_index]
    condition = _first_match(lines, CONDITION_MARKERS)
    brand = _extract_brand(lines)
    service_tags = [line for line in lines if line in SERVICE_MARKERS]
    location = _extract_location(lines, price_index)
    interest_text = _first_suffix(lines, ("人想要",))
    published_text = _first_suffix(lines, ("分钟前发布", "小时前发布", "小时前降价", "分钟前降价", "天前发布", "天前降价"))

    return ParsedXianyuListing(
        url=None,
        title=description,
        description=description,
        price_text=f"¥{price_text}",
        location=location,
        condition=condition,
        brand=brand,
        service_tags=service_tags,
        interest_text=interest_text,
        published_text=published_text,
    )


def _find_price_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line == "¥" and index + 1 < len(lines):
            candidate = lines[index + 1]
            if candidate.replace(".", "", 1).isdigit():
                return index + 1
    return None


def _drop_metadata(lines: list[str]) -> list[str]:
    return [
        line
        for line in lines
        if line not in CONDITION_MARKERS
        and line not in SERVICE_MARKERS
        and line != "Apple/苹果"
    ]


def _first_match(lines: list[str], candidates: set[str]) -> str | None:
    for line in lines:
        if line in candidates:
            return line
    return None


def _extract_brand(lines: list[str]) -> str | None:
    for line in lines:
        if "/" in line and ("苹果" in line or "Apple" in line):
            return line
    return None


def _extract_location(lines: list[str], price_index: int) -> str | None:
    for line in lines[price_index + 1 :]:
        if line in PROVINCES:
            return line
    return None


def _first_suffix(lines: list[str], suffixes: tuple[str, ...]) -> str | None:
    for line in lines:
        if line.endswith(suffixes):
            return line
    return None


@dataclass
class _Card:
    url: str
    lines: list[str]
    titles: list[str]


class _XianyuCardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[_Card] = []
        self._active_url: str | None = None
        self._lines: list[str] = []
        self._titles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value for name, value in attrs}
        href = attr_map.get("href")
        if tag == "a" and href and "goofish.com/item" in href:
            if self._active_url is not None:
                self._finish_active_card()
            self._active_url = href
            self._lines = []
            self._titles = []

        if self._active_url is not None:
            title = attr_map.get("title")
            if title:
                self._titles.append(_normalize_space(title))

    def handle_endtag(self, tag: str) -> None:
        if self._active_url is None or tag != "a":
            return
        self._finish_active_card()

    def handle_data(self, data: str) -> None:
        if self._active_url is None:
            return
        line = _normalize_space(data)
        if line:
            self._lines.append(line)

    def close(self) -> None:
        if self._active_url is not None:
            self._finish_active_card()
        super().close()

    def _finish_active_card(self) -> None:
        if self._active_url is None:
            return
        self.cards.append(
            _Card(
                url=self._active_url.replace("&amp;", "&"),
                lines=[line for line in (_normalize_space(line) for line in self._lines) if line],
                titles=[title for title in (_normalize_space(title) for title in self._titles) if title],
            )
        )
        self._active_url = None
        self._lines = []
        self._titles = []


def _parse_card(card: _Card) -> ParsedXianyuListing | None:
    lines = _dedupe_preserve_order(card.lines)
    titles = _dedupe_preserve_order(card.titles)
    combined = _dedupe_preserve_order(lines + titles)
    description = _extract_card_description(lines, titles)
    if not description:
        return None
    return ParsedXianyuListing(
        url=card.url,
        title=description,
        description=description,
        price_text=_extract_card_price(lines),
        location=_extract_card_location(combined),
        condition=_first_match(combined, CONDITION_MARKERS),
        brand=_extract_brand(combined),
        service_tags=[line for line in combined if line in SERVICE_MARKERS],
        interest_text=_first_suffix(combined, ("人想要",)),
        published_text=_first_suffix(
            combined,
            ("分钟前发布", "小时前发布", "小时前降价", "分钟前降价", "天前发布", "天前降价", "小时内发布"),
        ),
    )


def _extract_card_description(lines: list[str], titles: list[str]) -> str:
    for title in titles:
        if _looks_like_card_description(title):
            return title

    price_index = _find_price_index(lines)
    candidates = lines[: price_index - 1] if price_index and price_index > 0 and lines[price_index - 1] == "¥" else lines[:price_index]
    cleaned = [line for line in _drop_metadata(candidates) if _looks_like_card_description(line)]
    return cleaned[0] if cleaned else ""


def _extract_card_price(lines: list[str]) -> str | None:
    price_index = _find_price_index(lines)
    if price_index is not None:
        return f"¥{lines[price_index]}"
    match = re.search(r"¥\s*([0-9]+(?:\.[0-9]+)?)", " ".join(lines))
    if match:
        return f"¥{match.group(1)}"
    return None


def _extract_card_location(lines: list[str]) -> str | None:
    for line in lines:
        if line in PROVINCES:
            return line
    return None


def _looks_like_card_description(value: str) -> bool:
    if not value:
        return False
    if value in PROVINCES or value in CONDITION_MARKERS or value in SERVICE_MARKERS:
        return False
    if value.startswith("累计降价") or value.endswith(("人想要", "分钟前发布", "小时前发布", "小时内发布")):
        return False
    if value in {"¥", "搜索", "综合", "新降价", "新发布", "价格"}:
        return False
    return len(value) >= 8


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
