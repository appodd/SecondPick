from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shopping_agent.browser.session import BrowserSession, SearchFilters, SearchSnapshot
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_listing_snapshot,
    add_page_snapshot,
    connect,
    create_query,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.platforms.xianyu_parser import ParsedXianyuListing, parse_xianyu_api_items, parse_xianyu_html_cards
from shopping_agent.safety import SafetyError, reserve_search_access


@dataclass
class SearchSpikeResult:
    snapshot: SearchSnapshot
    text_path: Path
    links_path: Path
    run_id: int
    saved_links: int
    parsed_listings: int
    status_path: Path | None = None


class SearchSpikeSafetyError(SafetyError):
    def __init__(self, message: str, result: SearchSpikeResult) -> None:
        super().__init__(message)
        self.result = result


async def capture_search_spike(
    config: AppConfig,
    platform: str,
    query: str,
    wait_ms: int = 5000,
    headless: bool = False,
    filters: SearchFilters | None = None,
    scroll_steps: int = 0,
    scroll_wait_ms: int = 900,
    max_pages: int = 1,
) -> SearchSpikeResult:
    reserve_search_access(config, platform=platform, query=query)
    session = BrowserSession(config.browser_profile_dir, headless=headless)
    snapshot = await session.capture_search_snapshot(
        platform=platform,
        query=query,
        output_dir=config.screenshots_dir,
        wait_ms=wait_ms,
        filters=filters,
        scroll_steps=scroll_steps,
        scroll_wait_ms=scroll_wait_ms,
        max_pages=max_pages,
    )
    if snapshot.access_blocked and config.safety.stop_on_access_blocked:
        raise SafetyError(f"Access blocked while capturing {platform} search page for query: {query}")

    base = snapshot.html_path.with_suffix("")
    text_path = base.with_suffix(".txt")
    links_path = base.with_suffix(".links.txt")
    status_path = base.with_suffix(".status.json")
    text_path.write_text(snapshot.visible_text, encoding="utf-8")
    links_path.write_text("\n".join(snapshot.links), encoding="utf-8")
    status_path.write_text(
        json.dumps(
            {
                "platform": platform,
                "query": query,
                "requested_page_count": snapshot.requested_page_count,
                "api_page_count": snapshot.api_page_count,
                "stop_reason": snapshot.stop_reason,
                "access_blocked": snapshot.access_blocked,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    parsed_listings = _parse_platform_listings(platform, snapshot.html_path, getattr(snapshot, "api_items", None))
    candidate_links = [link for link in snapshot.links if _looks_like_listing_link(platform, link)]
    listings_to_save = _listing_records_to_save(platform, parsed_listings, candidate_links, snapshot.page_title, query)

    initialize(config.database_path)
    saved_links = 0
    with connect(config.database_path) as conn:
        query_label = _query_label(query, filters, scroll_steps=scroll_steps)
        run_id = create_search_run(conn, goal=query_label, city=config.default_city)
        create_query(conn, run_id=run_id, platform=platform, query_text=query_label)
        add_page_snapshot(
            conn,
            run_id=run_id,
            platform=platform,
            query_text=query_label,
            url=snapshot.url,
            title=snapshot.page_title,
            screenshot_path=snapshot.screenshot_path,
            html_path=snapshot.html_path,
            text_path=text_path,
            links_path=links_path,
            link_count=len(snapshot.links),
            access_blocked=snapshot.access_blocked,
        )
        for parsed in listings_to_save:
            if parsed.url is None:
                continue
            listing_id = upsert_listing(conn, platform=platform, url=parsed.url)
            add_listing_snapshot(
                conn,
                listing_id=listing_id,
                run_id=run_id,
                title=parsed.title or _truncate(parsed.description, 120),
                price_text=parsed.price_text,
                location=parsed.location,
                seller_name=parsed.seller_name,
                description=parsed.description,
                search_condition=parsed.condition,
            )
            saved_links += 1

    result = SearchSpikeResult(
        snapshot=snapshot,
        text_path=text_path,
        links_path=links_path,
        run_id=run_id,
        saved_links=saved_links,
        parsed_listings=len([listing for listing in listings_to_save if listing.url is not None]),
        status_path=status_path,
    )
    should_stop = snapshot.stop_reason is not None and (
        snapshot.stop_reason != "access_blocked"
        or config.safety.stop_on_access_blocked
    )
    if should_stop:
        raise SearchSpikeSafetyError(
            f"Stopped {platform} search capture: {snapshot.stop_reason}; "
            f"captured {snapshot.api_page_count} of {snapshot.requested_page_count} requested API pages.",
            result,
        )
    return result


def _looks_like_listing_link(platform: str, link: str) -> bool:
    if platform == "xianyu":
        return "goofish.com" in link and ("/item" in link or "id=" in link)
    if platform == "taobao":
        return "item.taobao.com" in link or "detail.tmall.com" in link
    if platform == "jd":
        return "item.jd.com" in link
    if platform == "zhuanzhuan":
        return "zhuanzhuan.com" in link and ("info" in link or "detail" in link)
    return False


def _parse_platform_listings(
    platform: str,
    html_path: Path,
    api_items: list[dict] | None = None,
) -> list[ParsedXianyuListing]:
    if platform == "xianyu":
        if api_items:
            api_json = {"data": {"resultList": [{"data": {"item": {"main": {"exContent": ex}}}} for ex in api_items]}}
            parsed = parse_xianyu_api_items(api_json)
            if parsed:
                return parsed
        return parse_xianyu_html_cards(html_path.read_text(encoding="utf-8"))
    return []


def _listing_records_to_save(
    platform: str,
    parsed_listings: list[ParsedXianyuListing],
    candidate_links: list[str],
    page_title: str,
    query: str,
) -> list[ParsedXianyuListing]:
    if parsed_listings:
        return [listing for listing in parsed_listings if listing.url and _looks_like_listing_link(platform, listing.url)]

    return [
        ParsedXianyuListing(
            description=f"Captured from raw search snapshot for query: {query}",
            price_text=None,
            location=None,
            condition=None,
            brand=None,
            service_tags=[],
            interest_text=None,
            published_text=None,
            url=link,
            title=f"Captured candidate for query: {query}",
        )
        for link in candidate_links
    ]


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1] + "..."


def _query_label(query: str, filters: SearchFilters | None, scroll_steps: int = 0) -> str:
    filters = filters or SearchFilters()
    if not filters.has_any() and scroll_steps <= 0:
        return query
    parts = [query]
    if filters.min_price is not None:
        parts.append(f"min_price={filters.min_price}")
    if filters.max_price is not None:
        parts.append(f"max_price={filters.max_price}")
    if filters.area:
        parts.append(f"area={filters.area}")
    if filters.sort and filters.sort != "default":
        parts.append(f"sort={filters.sort}")
    if scroll_steps > 0:
        parts.append(f"scroll_steps={scroll_steps}")
    return " ".join(parts)
