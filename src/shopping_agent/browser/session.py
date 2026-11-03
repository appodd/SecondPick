from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

import asyncio
import json

from playwright.async_api import async_playwright
from shopping_agent.browser.auth_state import restore_session_cookies, save_session_cookies


PLATFORM_LOGIN_URLS = {
    "xianyu": "https://www.goofish.com/",
    "taobao": "https://www.taobao.com/",
    "jd": "https://www.jd.com/",
    "zhuanzhuan": "https://www.zhuanzhuan.com/",
}

PLATFORM_SEARCH_URLS = {
    "xianyu": "https://www.goofish.com/search?q={query}",
    "taobao": "https://s.taobao.com/search?q={query}",
    "jd": "https://search.jd.com/Search?keyword={query}",
    "zhuanzhuan": "https://www.zhuanzhuan.com/search?keyword={query}",
}


@dataclass
class SearchSnapshot:
    platform: str
    query: str
    url: str
    screenshot_path: Path
    html_path: Path
    page_title: str
    visible_text: str
    links: list[str]
    access_blocked: bool
    filter_status: list[str] = field(default_factory=list)
    scroll_window_count: int = 0
    scroll_union_link_count: int = 0
    api_items: list[dict] = field(default_factory=list)
    api_page_count: int = 0
    requested_page_count: int = 1
    stop_reason: str | None = None


@dataclass(frozen=True)
class LoginResult:
    platform: str
    authenticated: bool | None


@dataclass
class SearchFilters:
    min_price: int | None = None
    max_price: int | None = None
    area: str | None = None
    sort: str | None = None

    def has_any(self) -> bool:
        return any(
            (
                self.min_price is not None,
                self.max_price is not None,
                bool(self.area),
                bool(self.sort and self.sort != "default"),
            )
        )

    def slug_suffix(self) -> str:
        parts = []
        if self.min_price is not None:
            parts.append(f"min-{self.min_price}")
        if self.max_price is not None:
            parts.append(f"max-{self.max_price}")
        if self.area:
            parts.append(f"area-{self.area}")
        if self.sort and self.sort != "default":
            parts.append(f"sort-{self.sort}")
        return "-".join(parts)


@dataclass
class DetailSnapshot:
    url: str
    screenshot_path: Path
    html_path: Path
    text_path: Path
    links_path: Path
    images_path: Path
    page_title: str
    visible_text: str
    links: list[str]
    image_urls: list[str]
    access_blocked: bool
    api_detail: dict | None = None
    login_required: bool = False


@asynccontextmanager
async def _closing_context(pending_context, profile_dir: Path | None = None):
    context = await pending_context
    try:
        if profile_dir is not None:
            await restore_session_cookies(context, profile_dir)
        yield context
    finally:
        try:
            if profile_dir is not None:
                # A manually closed window cannot export state. Cleanup must
                # still run and must preserve the original capture exception.
                try:
                    await save_session_cookies(context, profile_dir)
                except Exception:
                    pass
        finally:
            await context.close()


class BrowserSession:
    """Playwright persistent browser session backed by a local profile directory."""

    def __init__(self, profile_dir: Path, headless: bool = False) -> None:
        self.profile_dir = profile_dir
        self.headless = headless

    async def open_for_login(self, platform: str) -> LoginResult:
        url = PLATFORM_LOGIN_URLS.get(platform)
        if url is None:
            supported = ", ".join(sorted(PLATFORM_LOGIN_URLS))
            raise ValueError(f"Unsupported platform '{platform}'. Supported platforms: {supported}")

        self.profile_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as playwright, _closing_context(
            playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1440, "height": 1000},
                locale="zh-CN",
            ), self.profile_dir
        ) as context:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            print(f"Opened {platform} at {url}")
            print("Complete login in the browser window, then press Enter here to close it.")
            await _wait_for_enter()
            result = _login_result(platform, await _visible_frame_urls(page))
            return result

    async def capture_search_snapshot(
        self,
        platform: str,
        query: str,
        output_dir: Path,
        wait_ms: int = 5000,
        filters: SearchFilters | None = None,
        scroll_steps: int = 0,
        scroll_wait_ms: int = 900,
        max_pages: int = 1,
    ) -> SearchSnapshot:
        """Capture a Xianyu search snapshot.

        Primary path: intercept the MTOP ``pc.search`` JSON response and extract
        structured listings (itemId/title/price/area/condition) directly. ``max_pages``
        drives the browser's own next-page arrow to accumulate multiple pages of
        API responses into ``api_items`` (each page ~30 items).

        Fallback path: when API interception yields nothing, ``scroll_steps`` falls
        back to DOM scraping with per-step window unioning to counter the virtualized
        list. This is kept for resilience but is deprecated; prefer ``max_pages``.
        """
        url_template = PLATFORM_SEARCH_URLS.get(platform)
        if url_template is None:
            supported = ", ".join(sorted(PLATFORM_SEARCH_URLS))
            raise ValueError(f"Unsupported platform '{platform}'. Supported platforms: {supported}")

        output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        url = url_template.format(query=quote_plus(query))
        filters = filters or SearchFilters()
        slug_input = f"{platform}-{query}"
        if filters.has_any():
            slug_input = f"{slug_input}-{filters.slug_suffix()}"
        if scroll_steps > 0:
            slug_input = f"{slug_input}-scroll-{scroll_steps}"
        if max_pages > 1:
            slug_input = f"{slug_input}-pages-{max_pages}"
        slug = _slugify(slug_input)
        screenshot_path = output_dir / f"{slug}.png"
        html_path = output_dir / f"{slug}.html"

        async with async_playwright() as playwright, _closing_context(
            playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1440, "height": 1000},
                locale="zh-CN",
            ), self.profile_dir
        ) as context:
            page = context.pages[0] if context.pages else await context.new_page()
            api_items: list[dict] = []
            api_response_pages = 0
            pagination_exhausted = False
            pagination_incomplete: bool | None = None

            async def _on_search_response(resp):
                nonlocal api_response_pages
                try:
                    if "idlemtopsearch.pc.search/1.0" not in resp.url:
                        return
                    if "shade" in resp.url or "activate" in resp.url:
                        return
                    body = await resp.text()
                    obj = json.loads(body)
                    result_list = ((obj.get("data") or {}).get("resultList") or [])
                    for entry in result_list:
                        ex = ((entry.get("data") or {}).get("item") or {}).get("main") or {}
                        ex_content = ex.get("exContent") or {}
                        if ex_content.get("itemId"):
                            api_items.append(ex_content)
                    if result_list:
                        api_response_pages += 1
                except Exception:
                    pass

            if platform == "xianyu":
                page.on("response", lambda r: asyncio.create_task(_on_search_response(r)))
            await page.goto(url, wait_until="domcontentloaded")
            filter_status = await _apply_search_filters(page, platform, filters)
            await page.wait_for_timeout(wait_ms)
            login_required = _is_login_required(
                platform,
                await _visible_frame_urls(page),
            )
            # Pagination: the MTOP search endpoint returns one fixed-size page per
            # POST (rowsPerPage=30). Unlike infinite scroll, Xianyu PC search exposes
            # a classic numbered pager; clicking the right arrow fires a new signed
            # pc.search request with pageNumber+1, which the response listener above
            # captures and accumulates into api_items automatically. We drive the
            # browser's own next-page arrow so the platform's risk-control signing
            # (sign/bx-ua/umidtoken) stays intact; we never forge pagination
            # requests. Stop early when the arrow is disabled (last page).
            if platform == "xianyu" and max_pages > 1 and api_items and not login_required:
                arrow_selector = f"button{_class_stem_selector('search-pagination-arrow-container')}"
                for _ in range(max_pages - 1):
                    right_arrow = page.locator(arrow_selector).last
                    try:
                        if await right_arrow.get_attribute("disabled") is not None:
                            pagination_exhausted = True
                            break
                        await right_arrow.scroll_into_view_if_needed(timeout=2000)
                        before = len(api_items)
                        await right_arrow.click(timeout=3000)
                        for _ in range(40):
                            if len(api_items) > before:
                                break
                            await page.wait_for_timeout(250)
                        if len(api_items) == before:
                            pagination_incomplete = True
                            break
                    except Exception:
                        pagination_incomplete = True
                        break
            # Xianyu renders a virtualized list: the DOM keeps a fixed-size anchor
            # window (~30 item cards) and recycles cards as the user scrolls, so a
            # single end-of-scroll snapshot silently drops listings that scrolled
            # out of view. Capture a DOM window before scrolling (first screen) and
            # after every scroll step, then union them so the saved HTML and link
            # set reflect every card that was visible. The listing parser dedupes
            # cards by URL, so concatenated documents parse into the union.
            #
            # API interception note: when the MTOP search response was captured
            # (api_items non-empty), we already have structured listings and skip the
            # slow DOM scroll loop below. The MTOP endpoint returns a single
            # full-screen page per request; scrolling does NOT trigger additional
            # pc.search requests (verified empirically), and the request is signed
            # so pagination cannot be forged client-side. More samples therefore come
            # from multiple distinct searches (see research-loop), not from paging a
            # single search. DOM scrolling stays only as a fallback when the API
            # interception yields nothing.
            windows = [
                _ScrollWindow(html=await page.content(), links=await _capture_links(page))
            ]
            if scroll_steps > 0 and not api_items:
                windows.extend(
                    await _scroll_search_results(
                        page, scroll_steps=scroll_steps, scroll_wait_ms=scroll_wait_ms
                    )
                )
            page_title = await page.title()
            visible_text = await page.locator("body").inner_text(timeout=5000)
            access_blocked = _is_access_blocked(visible_text)
            login_required = login_required or _is_login_required(
                platform,
                await _visible_frame_urls(page),
            )
            stop_reason = _search_stop_reason(
                platform=platform,
                requested_page_count=max_pages,
                api_page_count=api_response_pages,
                access_blocked=access_blocked,
                login_required=login_required,
                pagination_exhausted=pagination_exhausted,
                pagination_incomplete=pagination_incomplete,
            )
            html = "\n".join(window.html for window in windows)
            link_set: list[str] = []
            seen_links: set[str] = set()
            for window in windows:
                for link in window.links:
                    if link and link not in seen_links:
                        seen_links.add(link)
                        link_set.append(link)
            await page.screenshot(path=str(screenshot_path), full_page=True)
            html_path.write_text(html, encoding="utf-8")

        return SearchSnapshot(
            platform=platform,
            query=query,
            url=url,
            screenshot_path=screenshot_path,
            html_path=html_path,
            page_title=page_title,
            visible_text=visible_text,
            links=link_set,
            access_blocked=access_blocked,
            filter_status=filter_status,
            scroll_window_count=len(windows),
            scroll_union_link_count=len(link_set),
            api_items=api_items,
            api_page_count=api_response_pages,
            requested_page_count=max_pages,
            stop_reason=stop_reason,
        )

    async def capture_detail_snapshot(
        self,
        url: str,
        output_dir: Path,
        wait_ms: int = 5000,
        verification_callback=None,
        verification_result_callback=None,
    ) -> DetailSnapshot:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(f"detail-{url}")
        screenshot_path = output_dir / f"{slug}.png"
        html_path = output_dir / f"{slug}.html"
        text_path = output_dir / f"{slug}.txt"
        links_path = output_dir / f"{slug}.links.txt"
        images_path = output_dir / f"{slug}.images.txt"

        async with async_playwright() as playwright, _closing_context(
            playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1440, "height": 1000},
                locale="zh-CN",
            ), self.profile_dir
        ) as context:
            page = context.pages[0] if context.pages else await context.new_page()
            api_detail: dict | None = None

            async def _on_detail_response(resp):
                nonlocal api_detail
                try:
                    if "idle.pc.detail/1.0" not in resp.url:
                        return
                    body = await resp.text()
                    obj = json.loads(body)
                    data = obj.get("data") or {}
                    item = data.get("itemDO") or {}
                    seller = data.get("sellerDO") or {}
                    if item.get("itemId"):
                        api_detail = {"item": item, "seller": seller}
                except Exception:
                    pass

            page.on("response", lambda r: asyncio.create_task(_on_detail_response(r)))
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(wait_ms)
            page_title = await page.title()
            visible_text = await page.locator("body").inner_text(timeout=5000)
            frame_urls = await _visible_frame_urls(page)
            login_required = _is_login_required("xianyu", frame_urls)
            access_blocked = _is_access_blocked(visible_text, frame_urls)
            while access_blocked and verification_callback is not None:
                # Keep this exact browser context alive for manual verification.
                # The callback only waits for the user's signal; it never solves
                # or dismisses the platform's verification challenge.
                await verification_callback(page)
                visible_text = await page.locator("body").inner_text(timeout=5000)
                frame_urls = await _visible_frame_urls(page)
                login_required = _is_login_required("xianyu", frame_urls)
                access_blocked = _is_access_blocked(visible_text, frame_urls)
                if verification_result_callback is not None:
                    await verification_result_callback(not access_blocked and not login_required)
            page_title = await page.title()
            html = await page.content()
            links = await page.eval_on_selector_all(
                "a[href]",
                "elements => [...new Set(elements.map(a => a.href).filter(Boolean))]",
            )
            image_urls = await page.eval_on_selector_all(
                "img",
                """
                elements => [...new Set(elements.map(img =>
                  img.currentSrc || img.src || img.getAttribute('data-src') || ''
                ).filter(Boolean))]
                """,
            )
            await page.screenshot(path=str(screenshot_path), full_page=True)
            html_path.write_text(html, encoding="utf-8")
            text_path.write_text(visible_text, encoding="utf-8")
            links_path.write_text("\n".join(links), encoding="utf-8")
            images_path.write_text("\n".join(image_urls), encoding="utf-8")

        return DetailSnapshot(
            url=url,
            screenshot_path=screenshot_path,
            html_path=html_path,
            text_path=text_path,
            links_path=links_path,
            images_path=images_path,
            page_title=page_title,
            visible_text=visible_text,
            links=links,
            image_urls=image_urls,
            access_blocked=access_blocked,
            api_detail=api_detail,
            login_required=login_required,
        )


async def _wait_for_enter() -> None:
    import asyncio

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, input)


def _slugify(value: str) -> str:
    normalized = []
    for char in value.lower():
        if char.isalnum():
            normalized.append(char)
        elif char in {"-", "_"}:
            normalized.append(char)
        else:
            normalized.append("-")
    slug = "".join(normalized).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:80] or "snapshot"


def _is_access_blocked(visible_text: str, visible_frame_urls: list[str] | None = None) -> bool:
    blocked_markers = [
        "非法访问",
        "请使用正常浏览器访问",
        "访问受限",
        "安全验证",
    ]
    return any(marker in visible_text for marker in blocked_markers) or any(
        "/_____tmd_____/punish" in urlsplit(url).path
        for url in visible_frame_urls or []
    )


def _is_login_required(platform: str, visible_frame_urls: list[str]) -> bool:
    if platform != "xianyu":
        return False
    return any(
        "passport.goofish.com/mini_login" in frame_url
        for frame_url in visible_frame_urls
    )


def _login_result(platform: str, visible_frame_urls: list[str]) -> LoginResult:
    if platform != "xianyu":
        return LoginResult(platform=platform, authenticated=None)
    return LoginResult(
        platform=platform,
        authenticated=not _is_login_required(platform, visible_frame_urls),
    )


def _search_stop_reason(
    *,
    platform: str,
    requested_page_count: int,
    api_page_count: int,
    access_blocked: bool,
    login_required: bool,
    pagination_exhausted: bool = False,
    pagination_incomplete: bool | None = None,
) -> str | None:
    if access_blocked:
        return "access_blocked"
    if login_required:
        return "login_required"
    if platform != "xianyu" or requested_page_count <= 1 or pagination_exhausted:
        return None
    if pagination_incomplete is None:
        pagination_incomplete = api_page_count < requested_page_count
    if pagination_incomplete:
        return "pagination_incomplete"
    return None


async def _visible_frame_urls(page) -> list[str]:
    frame_urls: list[str] = []
    frames = page.locator("iframe")
    for index in range(await frames.count()):
        frame = frames.nth(index)
        try:
            if not await frame.is_visible(timeout=200):
                continue
            src = await frame.get_attribute("src")
        except Exception:
            continue
        if src:
            frame_urls.append(src)
    return frame_urls


def _class_stem_selector(stem: str) -> str:
    """Playwright CSS selector matching any element whose class contains the
    CSS-module stem, i.e. "stem--hash". Xianyu ships hashed class names like
    "search-price-input--p1NQEAuz"; only the stem before "--" is stable across
    site rebuilds. The trailing "--" avoids matching a longer stem (e.g.
    "search-price-input--" will not match "search-price-input-container--").
    """
    return f'[class*="{stem}--"]'


# The Xianyu filter bar is a row of separate search-select-* dropdowns, each
# identified by its title text. A sort option lives under its OWN dropdown, so
# map our sort key to (dropdown title, option label) using the real on-page
# text rather than assuming a single "综合" dropdown.
_XIANYU_SORT_OPTIONS: dict[str, tuple[str, str]] = {
    "newest": ("综合", "最近活跃"),
    "price_asc": ("价格", "价格从低到高"),
    "price_desc": ("价格", "价格从高到低"),
}


async def _apply_search_filters(page, platform: str, filters: SearchFilters) -> list[str]:
    """Apply Xianyu web filters via their UI components and return a status log.

    Xianyu is a SPA: clicking a filter or confirming a price range refreshes results
    via AJAX, which does NOT fire domcontentloaded. Each filter must wait for the
    result list to refresh (network idle + stable wait) before the caller captures
    the page, otherwise the snapshot still reflects the pre-filter results.
    """
    status: list[str] = []
    if platform != "xianyu" or not filters.has_any():
        return status
    await _apply_xianyu_price_filters(page, filters, status)
    await _apply_xianyu_area_filter(page, filters.area, status)
    await _apply_xianyu_sort_filter(page, filters.sort, status)
    return status


async def _apply_xianyu_price_filters(page, filters: SearchFilters, status: list[str]) -> None:
    if filters.min_price is None and filters.max_price is None:
        return
    inputs = page.locator(f"input{_class_stem_selector('search-price-input')}")
    if await inputs.count() < 2:
        inputs = page.locator("input[placeholder='¥']")
    if await inputs.count() < 2:
        status.append("price:input_not_found")
        return

    if filters.min_price is not None:
        await inputs.nth(0).fill(str(filters.min_price))
        await inputs.nth(0).dispatch_event("input")
        await inputs.nth(0).dispatch_event("change")
    if filters.max_price is not None:
        await inputs.nth(1).fill(str(filters.max_price))
        await inputs.nth(1).dispatch_event("input")
        await inputs.nth(1).dispatch_event("change")

    # Xianyu applies the price filter via AJAX once the input value changes;
    # the confirm button is often outside the viewport and not reliably
    # clickable, so it is best-effort. Wait for results to refresh either way.
    confirmed = False
    button = page.locator(f"button{_class_stem_selector('search-price-confirm-button')}").first
    if await button.count():
        try:
            await button.dispatch_event("click")
            confirmed = True
        except Exception as exc:
            status.append(f"price:confirm_click_error:{type(exc).__name__}")
    if not confirmed:
        # Fallback: pressing Enter on the filled input also submits the form.
        try:
            await inputs.nth(1 if filters.max_price is not None else 0).press("Enter")
        except Exception as exc:
            status.append(f"price:enter_error:{type(exc).__name__}")
    await _wait_for_search_refresh(page)
    bounds = []
    if filters.min_price is not None:
        bounds.append(f"min={filters.min_price}")
    if filters.max_price is not None:
        bounds.append(f"max={filters.max_price}")
    status.append("price:applied:" + ",".join(bounds) + ("" if confirmed else ":no_confirm"))


async def _apply_xianyu_area_filter(page, area: str | None, status: list[str]) -> None:
    if not area:
        return
    # The trigger is the "区域" span (areaText--*); clicking opens an area popup
    # whose city options are not present in the static DOM, so the option click
    # is best-effort against the supplied area text.
    trigger = page.locator(_class_stem_selector("areaText")).filter(has_text="区域").first
    opened = False
    if await trigger.count():
        try:
            await trigger.click(timeout=2000)
            await page.wait_for_timeout(400)
            opened = True
        except Exception as exc:
            status.append(f"area:trigger_click_error:{type(exc).__name__}")
    else:
        opened = await _click_visible_text(page, "区域")
    clicked = await _click_visible_text(page, area)
    if opened and clicked:
        await _wait_for_search_refresh(page)
        status.append(f"area:applied:{area}")
    else:
        status.append(f"area:not_applied:{area}")


async def _apply_xianyu_sort_filter(page, sort: str | None, status: list[str]) -> None:
    if not sort or sort == "default":
        return
    entry = _XIANYU_SORT_OPTIONS.get(sort)
    if entry is None:
        status.append(f"sort:unknown:{sort}")
        return
    dropdown_title, option_label = entry
    # Open the dropdown that owns this sort option by clicking its title span.
    title = page.locator(_class_stem_selector("search-select-title")).filter(has_text=dropdown_title).first
    opened = False
    if await title.count():
        try:
            await title.scroll_into_view_if_needed(timeout=1500)
            await title.click(timeout=2000)
            await page.wait_for_timeout(450)
            opened = True
        except Exception as exc:
            status.append(f"sort:trigger_click_error:{type(exc).__name__}")
    else:
        opened = await _click_visible_text(page, dropdown_title)
    # The option item lives under this dropdown's items panel and must be visible
    # before clicking. If the title click toggled an already-open panel closed,
    # click the title once more to reopen, then click the item.
    item = page.locator(_class_stem_selector("search-select-item")).filter(has_text=option_label).first
    clicked = False
    if await item.count():
        try:
            try:
                await item.first.wait_for(state="visible", timeout=1500)
            except Exception:
                if await title.count():
                    await title.click(timeout=2000)
                    await page.wait_for_timeout(450)
                await item.first.wait_for(state="visible", timeout=1500)
            await item.first.click(timeout=2000)
            clicked = True
        except Exception as exc:
            status.append(f"sort:item_click_error:{type(exc).__name__}")
    if clicked:
        await _wait_for_search_refresh(page)
        status.append(f"sort:applied:{sort}:{option_label}")
    else:
        status.append(f"sort:not_applied:{sort}")


async def _try_click_text_filter(page, *, trigger_labels: list[str], option_labels: list[str]) -> bool:
    for trigger in trigger_labels:
        if await _click_visible_text(page, trigger):
            await page.wait_for_timeout(400)
            break

    for option in option_labels:
        if await _click_visible_text(page, option):
            await page.wait_for_timeout(700)
            await _click_visible_text(page, "确定")
            return True
    return False


async def _click_visible_text(page, text: str) -> bool:
    locator = page.get_by_text(text, exact=True)
    count = await locator.count()
    for index in range(min(count, 5)):
        item = locator.nth(index)
        try:
            if await item.is_visible(timeout=500):
                await item.click(timeout=1200)
                return True
        except Exception:
            continue
    return False


async def _wait_for_search_refresh(page, timeout_ms: int = 4000) -> None:
    """Wait for SPA search results to refresh after applying a Xianyu filter.

    Xianyu updates results via AJAX (no full navigation), so domcontentloaded
    never fires. Wait for network to go idle first, then a short stable wait so
    the result list finishes rendering before the snapshot is captured.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # networkidle can be flaky on long-polling pages; fall through to wait.
        pass
    await page.wait_for_timeout(800)


@dataclass
class _ScrollWindow:
    html: str
    links: list[str]


async def _capture_links(page) -> list[str]:
    return await page.eval_on_selector_all(
        "a[href]",
        "elements => [...new Set(elements.map(a => a.href).filter(Boolean))]",
    )


async def _scroll_search_results(
    page, scroll_steps: int, scroll_wait_ms: int
) -> list[_ScrollWindow]:
    """Scroll the search results, capturing a DOM window after each scroll step.

    Xianyu renders a virtualized list: the DOM keeps a fixed-size anchor window
    (~30 item cards) and recycles cards as the user scrolls, so a single
    end-of-scroll snapshot silently drops listings that scrolled out of view.
    Capturing a window after each scroll step lets callers union the per-step
    windows to recover full coverage. Returns an empty list when scroll_steps
    is non-positive.
    """
    if scroll_steps <= 0:
        return []
    wait_ms = max(scroll_wait_ms, 0)
    stable_height_count = 0
    previous_height = await page.evaluate("document.documentElement.scrollHeight")
    windows: list[_ScrollWindow] = []
    for _ in range(scroll_steps):
        await page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.9))")
        if wait_ms:
            await page.wait_for_timeout(wait_ms)
        windows.append(
            _ScrollWindow(html=await page.content(), links=await _capture_links(page))
        )
        current_height = await page.evaluate("document.documentElement.scrollHeight")
        current_scroll = await page.evaluate("window.scrollY + window.innerHeight")
        if current_height <= previous_height and current_scroll >= current_height - 4:
            stable_height_count += 1
        else:
            stable_height_count = 0
        previous_height = current_height
        if stable_height_count >= 2:
            break
    return windows
