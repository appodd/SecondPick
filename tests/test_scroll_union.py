from __future__ import annotations

import asyncio
from pathlib import Path

from shopping_agent.browser.session import (
    SearchSnapshot,
    _ScrollWindow,
    _scroll_search_results,
)
from shopping_agent.platforms.xianyu_parser import parse_xianyu_html_cards


def _item_url(item_id: str) -> str:
    return f"https://www.goofish.com/item?id={item_id}&categoryId=126854525"


def _card_html(item_id: str, desc: str) -> str:
    # Minimal Xianyu card: an item anchor whose description comes from the
    # title attribute so _parse_card returns a listing (description is required
    # for a card to be kept). No price/location needed for the union assertion.
    return (
        f'<a href="{_item_url(item_id)}" title="{desc}">'
        f"<div>{desc}</div></a>"
    )


def test_parse_xianyu_html_cards_unions_concatenated_windows() -> None:
    card_a = _card_html("111", "MacBook Pro 13 M1 2020 8GB")
    card_b = _card_html("222", "MacBook Pro 14 M1 2021 16GB")
    doc_a = f"<html><body>{card_a}</body></html>"
    doc_b = f"<html><body>{card_b}</body></html>"

    # Each per-step window alone yields exactly its own card.
    assert {listing.url for listing in parse_xianyu_html_cards(doc_a)} == {_item_url("111")}
    assert {listing.url for listing in parse_xianyu_html_cards(doc_b)} == {_item_url("222")}

    # capture_search_snapshot now saves concatenated per-step windows; the parser
    # dedupes by URL, so the saved union HTML parses into the union of cards.
    union = parse_xianyu_html_cards("\n".join([doc_a, doc_b]))
    assert {listing.url for listing in union} == {_item_url("111"), _item_url("222")}

    # Dedup: repeating a window does not double-count a card.
    dup = parse_xianyu_html_cards("\n".join([doc_a, doc_a]))
    assert len(dup) == 1
    assert dup[0].url == _item_url("111")


class _FakePage:
    """Minimal async page double for _scroll_search_results.

    Routes page.evaluate calls by expression text and serves per-step
    html/links pairs so we can assert per-step window capture without a browser.
    """

    def __init__(
        self,
        heights: list[int],
        scrolled: list[int],
        htmls: list[str],
        links: list[list[str]],
    ) -> None:
        self._heights = heights
        self._scrolled = scrolled
        self._htmls = htmls
        self._links = links
        self._height_i = 0
        self._scrolled_i = 0
        self._capture_i = 0

    async def evaluate(self, expr: str):
        if expr == "document.documentElement.scrollHeight":
            value = self._heights[self._height_i]
            self._height_i += 1
            return value
        if expr.startswith("window.scrollBy"):
            return None
        if expr == "window.scrollY + window.innerHeight":
            value = self._scrolled[self._scrolled_i]
            self._scrolled_i += 1
            return value
        raise AssertionError(f"unexpected evaluate expression: {expr!r}")

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    async def content(self) -> str:
        value = self._htmls[self._capture_i]
        self._capture_i += 1
        return value

    async def eval_on_selector_all(self, selector: str, js: str) -> list[str]:
        return list(self._links[self._capture_i - 1])


def test_scroll_search_results_returns_window_per_step() -> None:
    page = _FakePage(
        heights=[1000, 2000, 3000, 4000],  # grows each step -> never bottom-stable
        scrolled=[0, 0, 0],                # below bottom -> stable check stays false
        htmls=["<a id=a>", "<a id=b>", "<a id=c>"],
        links=[["la"], ["lb"], ["lc"]],
    )

    windows = asyncio.run(_scroll_search_results(page, scroll_steps=3, scroll_wait_ms=0))

    assert len(windows) == 3
    assert [window.html for window in windows] == ["<a id=a>", "<a id=b>", "<a id=c>"]
    assert [window.links for window in windows] == [["la"], ["lb"], ["lc"]]


def test_scroll_search_results_breaks_when_bottom_stable() -> None:
    page = _FakePage(
        heights=[1000, 1000, 1000],  # height stops growing
        scrolled=[1000, 1000],      # scrolled to bottom each step -> stable
        htmls=["<a id=a>", "<a id=b>", "<a id=c>", "<a id=d>", "<a id=e>"],
        links=[["la"], ["lb"], ["lc"], ["ld"], ["le"]],
    )

    windows = asyncio.run(_scroll_search_results(page, scroll_steps=5, scroll_wait_ms=0))

    # Two consecutive stable steps trips the early break after the 2nd window.
    assert len(windows) == 2
    assert [window.html for window in windows] == ["<a id=a>", "<a id=b>"]


def test_scroll_search_results_no_steps_returns_empty() -> None:
    page = _FakePage(heights=[], scrolled=[], htmls=[], links=[])
    assert asyncio.run(_scroll_search_results(page, scroll_steps=0, scroll_wait_ms=0)) == []


def test_search_snapshot_scroll_union_fields_default() -> None:
    # Existing call sites construct SearchSnapshot without the new scroll fields;
    # they must default so backward compatibility holds.
    snapshot = SearchSnapshot(
        platform="xianyu",
        query="macbook",
        url="https://www.goofish.com/search?q=macbook",
        screenshot_path=Path("data/screenshots/x.png"),
        html_path=Path("data/screenshots/x.html"),
        page_title="x",
        visible_text="",
        links=[],
        access_blocked=False,
    )
    assert snapshot.scroll_window_count == 0
    assert snapshot.scroll_union_link_count == 0
    assert snapshot.filter_status == []
    assert isinstance(_ScrollWindow(html="h", links=["l"]), _ScrollWindow)
