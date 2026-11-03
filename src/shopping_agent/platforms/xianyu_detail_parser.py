from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


@dataclass
class ParsedXianyuDetail:
    seller_name: str | None
    seller_location: str | None
    seller_stats: list[str]
    price_text: str | None
    wanted_text: str | None
    view_text: str | None
    description: str
    attributes: dict[str, str]
    # Structured seller fields (populated from MTOP pc.detail sellerDO; None for DOM fallback)
    seller_credit_level: str | None = None
    seller_registered_days: int | None = None
    seller_sold_count: int | None = None
    seller_good_rate: str | None = None
    seller_realname_verified: bool | None = None
    seller_reply_rate_24h: str | None = None


def parse_xianyu_detail_api(api_detail: dict | None) -> ParsedXianyuDetail | None:
    """Parse a Xianyu PC detail page from the MTOP pc.detail JSON response.

    The API carries structured itemDO/sellerDO fields, so this avoids scraping
    the rendered visible text. Returns None when api_detail is missing or has no
    usable item data, letting callers fall back to the DOM visible-text parser.
    """
    if not api_detail:
        return None
    item = api_detail.get("item") or {}
    seller = api_detail.get("seller") or {}
    if not item.get("itemId"):
        return None
    title = item.get("title") or ""
    desc = item.get("desc") or ""
    description = desc or title
    price_text = None
    sold_price = item.get("soldPrice")
    if sold_price:
        price_text = f"\u00a5{sold_price}"
    seller_name = seller.get("nick") or seller.get("uniqueName")
    seller_location = seller.get("city") or seller.get("publishCity")
    seller_stats = []
    sold = seller.get("hasSoldNumInteger")
    if sold is not None:
        seller_stats.append(f"\u5356\u51fa\u8fc7{sold}\u4ef6\u5b9d\u8d1d")
    reply = seller.get("replyRatio24h")
    if reply:
        seller_stats.append(f"24\u5c0f\u65f6\u56de\u590d\u7387{reply}")
    zhima = (seller.get("zhimaLevelInfo") or {}).get("levelName")
    if zhima:
        seller_stats.append(f"\u82bd\u9ebb\u4fe1\u7528{zhima}")
    summary = seller.get("xianyuSummary")
    if summary:
        seller_stats.append(summary)
    wanted_text = None
    want_cnt = item.get("wantCnt")
    if want_cnt is not None:
        unit = item.get("wantCntUnit") or "人想要"
        wanted_text = f"{want_cnt}{unit}"
    view_text = None
    browse_cnt = item.get("browseCnt")
    if browse_cnt is not None:
        view_text = f"{browse_cnt}\u6d4f\u89c8"
    attributes: dict[str, str] = {}
    for label in item.get("itemLabelExtList") or []:
        prop = label.get("propertyText")
        text = label.get("text")
        if prop and text:
            attributes[prop] = text
    seller_credit_level = (seller.get("zhimaLevelInfo") or {}).get("levelName")
    seller_registered_days = seller.get("userRegDay")
    seller_sold_count = seller.get("hasSoldNumInteger")
    seller_good_rate = seller.get("newGoodRatioRate")
    identity_tags = seller.get("identityTags") or []
    seller_realname_verified = any(
        ("实人" in (tag.get("text") or "")) or ("认证" in (tag.get("text") or ""))
        for tag in identity_tags if isinstance(tag, dict)
    ) or None
    seller_reply_rate_24h = seller.get("replyRatio24h")
    return ParsedXianyuDetail(
        seller_name=seller_name,
        seller_location=seller_location,
        seller_stats=seller_stats,
        price_text=price_text,
        wanted_text=wanted_text,
        view_text=view_text,
        description=description,
        attributes=attributes,
        seller_credit_level=seller_credit_level,
        seller_registered_days=seller_registered_days,
        seller_sold_count=seller_sold_count,
        seller_good_rate=seller_good_rate,
        seller_realname_verified=seller_realname_verified,
        seller_reply_rate_24h=seller_reply_rate_24h,
    )


def parse_xianyu_detail_text(visible_text: str) -> ParsedXianyuDetail:
    lines = [line.strip() for line in visible_text.splitlines() if line.strip()]
    main_lines = _before_recommendations(lines)

    price_index = _find_price_index(main_lines)
    seller_name = _extract_seller_name(main_lines)
    seller_location = _extract_seller_location(main_lines)
    seller_stats = _extract_seller_stats(main_lines)
    price_text = f"¥{main_lines[price_index]}" if price_index is not None else None
    wanted_text = _first_suffix(main_lines, "人想要")
    view_text = _first_suffix(main_lines, "浏览")
    attributes = _extract_attributes(main_lines)
    description = _extract_description(main_lines, price_index)

    return ParsedXianyuDetail(
        seller_name=seller_name,
        seller_location=seller_location,
        seller_stats=seller_stats,
        price_text=price_text,
        wanted_text=wanted_text,
        view_text=view_text,
        description=description,
        attributes=attributes,
    )


def _before_recommendations(lines: list[str]) -> list[str]:
    if "为你推荐" in lines:
        return lines[: lines.index("为你推荐")]
    return lines


def _find_price_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line == "¥" and index + 1 < len(lines):
            candidate = lines[index + 1]
            if candidate.replace(".", "", 1).isdigit():
                return index + 1
    return None


def _extract_seller_name(lines: list[str]) -> str | None:
    ignored = {"搜索", "网页版发闲置功能又升级啦！"}
    for line in lines:
        if line in ignored:
            continue
        if line.endswith(("来过", "件宝贝")) or line.startswith("好评率"):
            continue
        if line in {"闲鱼号", "担保交易", "举报"}:
            continue
        return line
    return None


def _extract_seller_location(lines: list[str]) -> str | None:
    seller_name = _extract_seller_name(lines)
    if seller_name is None:
        return None
    try:
        index = lines.index(seller_name)
    except ValueError:
        return None
    if index + 1 < len(lines):
        return lines[index + 1]
    return None


def _extract_seller_stats(lines: list[str]) -> list[str]:
    stats = []
    for line in lines:
        if line.endswith("来过") or line.startswith("来闲鱼") or line.startswith("卖出") or line.startswith("好评率"):
            stats.append(line)
    return stats


def _extract_description(lines: list[str], price_index: int | None) -> str:
    if price_index is None:
        return ""
    start = price_index + 1
    while start < len(lines) and (
        lines[start] in {"包邮", "担保交易", "举报"}
        or lines[start].endswith("人想要")
        or lines[start].endswith("浏览")
    ):
        start += 1

    end = len(lines)
    for marker in ("品", "聊一聊", "立即购买", "收藏"):
        if marker in lines[start:]:
            end = min(end, lines.index(marker, start))
    attribute_start = _find_attribute_start(lines, start, end)
    if attribute_start is not None:
        end = min(end, attribute_start)
    return "\n".join(lines[start:end]).strip()


def _find_attribute_start(lines: list[str], start: int, end: int) -> int | None:
    split_label_start = None
    for index in range(start, end):
        line = lines[index]
        if line == "\uff1a":
            if split_label_start is not None and index + 1 < end:
                return split_label_start
            split_label_start = None
            continue
        if len(line) == 1 and "\u4e00" <= line <= "\u9fff":
            if split_label_start is None:
                split_label_start = index
            continue
        split_label_start = None
        if line.endswith("\uff1a") and index + 1 < end:
            return index
    return None


def _extract_attributes(lines: list[str]) -> dict[str, str]:
    attrs = {}
    compact = _compact_split_labels(lines)
    for index, token in enumerate(compact):
        if token.endswith("：") and index + 1 < len(compact):
            key = token[:-1]
            attrs[key] = compact[index + 1]
    return attrs


def _compact_split_labels(lines: list[str]) -> list[str]:
    compact = []
    buffer = ""
    for line in lines:
        if line == "：":
            if buffer:
                compact.append(f"{buffer}：")
                buffer = ""
            continue
        if len(line) == 1 and "\u4e00" <= line <= "\u9fff":
            buffer += line
            continue
        if buffer:
            compact.append(buffer)
            buffer = ""
        compact.append(line)
    if buffer:
        compact.append(buffer)
    return compact


def _first_suffix(lines: list[str], suffix: str) -> str | None:
    for line in lines:
        if line.endswith(suffix):
            return line
    return None


def parse_xianyu_recommendation_links(
    links: list[str],
    current_url: str | None = None,
    limit: int = 30,
) -> list[str]:
    """Extract unique Goofish item URLs from a detail page's raw links.

    The detail page mixes the current item, seller links, platform chrome, and
    "for you" recommendations. We only expose candidate item links as evidence
    for the LLM to decide whether they are worth opening.
    """

    current_item_id = _xianyu_item_id(current_url) if current_url else None
    seen_item_ids: set[str] = set()
    result: list[str] = []
    for link in links:
        item_id = _xianyu_item_id(link)
        if item_id is None:
            continue
        if item_id == current_item_id or item_id in seen_item_ids:
            continue
        seen_item_ids.add(item_id)
        result.append(f"https://www.goofish.com/item?id={item_id}")
        if len(result) >= limit:
            break
    return result


def _xianyu_item_id(url: str | None) -> str | None:
    if not url or "goofish.com" not in url:
        return None
    parsed = urlparse(url)
    if "/item" not in parsed.path and "item" not in parsed.path:
        return None
    item_ids = parse_qs(parsed.query).get("id")
    if not item_ids:
        return None
    item_id = item_ids[0].strip()
    return item_id if item_id.isdigit() else None
