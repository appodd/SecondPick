from __future__ import annotations

from shopping_agent.cli import _resolve_detail_capture_metadata
from shopping_agent.config import AppConfig
from shopping_agent.db import add_listing_snapshot, connect, create_search_run, initialize, upsert_listing
from shopping_agent.detail import listing_url_belongs_to_run


def test_existing_search_run_url_keeps_web_search_source() -> None:
    assert _resolve_detail_capture_metadata(
        url="https://www.goofish.com/item?id=3259",
        run_id=61,
        source_type=None,
        source_label=None,
        url_belongs_to_run=True,
    ) == ("web_search", "网页搜索", "detail_capture")


def test_url_without_run_defaults_to_manual_seed() -> None:
    assert _resolve_detail_capture_metadata(
        url="https://www.goofish.com/item?id=manual",
        run_id=None,
        source_type=None,
        source_label=None,
        url_belongs_to_run=False,
    ) == ("mobile_manual", "手机端手动加入", "manual_seed")


def test_explicit_source_metadata_is_preserved_for_existing_run() -> None:
    assert _resolve_detail_capture_metadata(
        url="https://www.goofish.com/item?id=3259",
        run_id=61,
        source_type="curated_search",
        source_label="人工筛选的网页候选",
        url_belongs_to_run=True,
    ) == ("curated_search", "人工筛选的网页候选", "detail_capture")


def test_url_outside_existing_run_keeps_manual_source() -> None:
    assert _resolve_detail_capture_metadata(
        url="https://www.goofish.com/item?id=manual",
        run_id=61,
        source_type=None,
        source_label=None,
        url_belongs_to_run=False,
    ) == ("mobile_manual", "手机端手动加入", "detail_capture")


def test_url_outside_existing_run_cannot_override_manual_provenance() -> None:
    assert _resolve_detail_capture_metadata(
        url="https://www.goofish.com/item?id=manual",
        run_id=61,
        source_type="web_search",
        source_label="网页搜索",
        url_belongs_to_run=False,
    ) == ("mobile_manual", "手机端手动加入", "detail_capture")


def test_listing_url_membership_uses_saved_run_evidence(tmp_path) -> None:
    config = AppConfig(database_path=tmp_path / "detail-membership.sqlite")
    initialize(config.database_path)
    saved_url = "https://www.goofish.com/item?id=saved"
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="saved listing", city="上海")
        listing_id = upsert_listing(conn, platform="xianyu", url=saved_url)
        add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id, title="saved")

    assert listing_url_belongs_to_run(config, run_id=run_id, url=saved_url) is True
    assert (
        listing_url_belongs_to_run(
            config,
            run_id=run_id,
            url="https://www.goofish.com/item?id=other",
        )
        is False
    )
