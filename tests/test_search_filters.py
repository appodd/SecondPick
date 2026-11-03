from __future__ import annotations

from pathlib import Path

import pytest

from shopping_agent.browser.session import (
    LoginResult,
    SearchFilters,
    SearchSnapshot,
    _XIANYU_SORT_OPTIONS,
    _class_stem_selector,
    _is_login_required,
    _login_result,
    _search_stop_reason,
)
from shopping_agent.cli import _search_capture_status_lines, build_parser
from shopping_agent.spike import _query_label


def test_spike_search_accepts_price_filters() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "spike-search",
            "xianyu",
            "MacBook Pro 14寸 2023 M2",
            "--min-price",
            "3000",
            "--max-price",
            "9000",
            "--i-understand-account-risk",
        ]
    )

    assert args.min_price == 3000
    assert args.max_price == 9000


def test_spike_search_accepts_objective_xianyu_web_filters() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "spike-search",
            "xianyu",
            "MacBook Pro 14",
            "--area",
            "Shanghai",
            "--sort",
            "newest",
            "--i-understand-account-risk",
        ]
    )

    assert args.area == "Shanghai"
    assert args.sort == "newest"


def test_spike_search_rejects_personal_only() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["spike-search", "xianyu", "MacBook", "--personal-only"])


def test_spike_search_accepts_scroll_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "spike-search",
            "xianyu",
            "macbook",
            "--scroll-steps",
            "8",
            "--scroll-wait-ms",
            "700",
            "--i-understand-account-risk",
        ]
    )

    assert args.scroll_steps == 8
    assert args.scroll_wait_ms == 700


def test_search_filter_label_records_price_bounds() -> None:
    label = _query_label(
        "MacBook Pro 14寸 2023 M2",
        SearchFilters(min_price=3000, max_price=9000),
    )

    assert label == "MacBook Pro 14寸 2023 M2 min_price=3000 max_price=9000"


def test_search_filter_label_records_objective_xianyu_web_filters() -> None:
    label = _query_label(
        "MacBook Pro 14",
        SearchFilters(area="Shanghai", sort="newest"),
    )

    assert label == "MacBook Pro 14 area=Shanghai sort=newest"


def test_search_filter_ignores_default_sort() -> None:
    label = _query_label(
        "MacBook Pro 14",
        SearchFilters(sort="default"),
    )

    assert label == "MacBook Pro 14"
    assert SearchFilters(sort="default").has_any() is False


def test_search_filter_label_records_scroll_steps() -> None:
    label = _query_label(
        "macbook",
        SearchFilters(),
        scroll_steps=8,
    )

    assert label == "macbook scroll_steps=8"


def test_search_filter_slug_suffix_is_stable() -> None:
    filters = SearchFilters(
        min_price=3000,
        max_price=9000,
        area="Shanghai",
        sort="newest",
    )

    assert filters.has_any() is True
    assert filters.slug_suffix() == "min-3000-max-9000-area-Shanghai-sort-newest"
def test_search_snapshot_has_filter_status_default() -> None:
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
    assert snapshot.filter_status == []
    assert snapshot.requested_page_count == 1
    assert snapshot.stop_reason is None


def test_xianyu_visible_passport_frame_requires_login() -> None:
    assert _is_login_required(
        "xianyu",
        ["https://passport.goofish.com/mini_login.htm?appName=xianyu"],
    ) is True
    assert _is_login_required(
        "xianyu",
        ["https://www.goofish.com/search?q=Sony+A7C2"],
    ) is False


def test_xianyu_login_result_reports_visible_login_modal_as_incomplete() -> None:
    assert _login_result(
        "xianyu",
        ["https://passport.goofish.com/mini_login.htm?appName=xianyu"],
    ) == LoginResult(platform="xianyu", authenticated=False)


def test_xianyu_login_result_reports_missing_login_modal_as_authenticated() -> None:
    assert _login_result("xianyu", []) == LoginResult(
        platform="xianyu",
        authenticated=True,
    )


def test_xianyu_incomplete_api_pagination_has_explicit_stop_reason() -> None:
    assert _search_stop_reason(
        platform="xianyu",
        requested_page_count=3,
        api_page_count=1,
        access_blocked=False,
        login_required=False,
    ) == "pagination_incomplete"


def test_xianyu_missing_api_pagination_has_explicit_stop_reason() -> None:
    assert _search_stop_reason(
        platform="xianyu",
        requested_page_count=3,
        api_page_count=0,
        access_blocked=False,
        login_required=False,
    ) == "pagination_incomplete"


def test_xianyu_login_stop_takes_priority_over_incomplete_pagination() -> None:
    assert _search_stop_reason(
        platform="xianyu",
        requested_page_count=3,
        api_page_count=1,
        access_blocked=False,
        login_required=True,
    ) == "login_required"


def test_search_capture_status_lines_show_requested_and_actual_pages() -> None:
    snapshot = SearchSnapshot(
        platform="xianyu",
        query="索尼 A7C2 单机",
        url="https://www.goofish.com/search?q=Sony+A7C2",
        screenshot_path=Path("data/screenshots/x.png"),
        html_path=Path("data/screenshots/x.html"),
        page_title="索尼 A7C2 单机_闲鱼",
        visible_text="",
        links=[],
        access_blocked=False,
        api_page_count=1,
        requested_page_count=3,
        stop_reason="login_required",
    )

    assert _search_capture_status_lines(snapshot) == [
        "Search pages: requested 3, captured API responses 1",
        "Collection stop reason: login_required",
    ]


def test_class_stem_selector_matches_hashed_suffix() -> None:
    assert _class_stem_selector("search-price-input") == '[class*="search-price-input--"]'
    assert "search-price-input-container--" not in _class_stem_selector("search-price-input")


def test_xianyu_sort_options_match_cli_choices_and_real_labels() -> None:
    assert set(_XIANYU_SORT_OPTIONS) == {"newest", "price_asc", "price_desc"}
    assert _XIANYU_SORT_OPTIONS["newest"] == ("综合", "最近活跃")
    assert _XIANYU_SORT_OPTIONS["price_asc"] == ("价格", "价格从低到高")
    assert _XIANYU_SORT_OPTIONS["price_desc"] == ("价格", "价格从高到低")
