from __future__ import annotations

from pathlib import Path

from shopping_agent.cli import build_parser
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
from shopping_agent.run_summary import build_run_summary


def test_run_summary_cli_accepts_pretty_option() -> None:
    parser = build_parser()

    args = parser.parse_args(["run-summary", "--run-id", "33", "--pretty"])

    assert args.command == "run-summary"
    assert args.run_id == 33
    assert args.pretty is True


def test_build_run_summary_reports_result_quality() -> None:
    config = AppConfig(database_path=Path("data/test-run-summary.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="iMac 27", city="上海")
        create_query(conn, run_id=run_id, platform="xianyu", query_text="iMac 27")
        add_page_snapshot(
            conn,
            run_id=run_id,
            platform="xianyu",
            query_text="iMac 27",
            url="https://www.goofish.com/search?q=iMac+27",
            title="iMac 27",
            screenshot_path=Path("data/screenshots/search.png"),
            html_path=Path("data/screenshots/search.html"),
            text_path=Path("data/screenshots/search.txt"),
            links_path=Path("data/screenshots/search.links.txt"),
            link_count=10,
            access_blocked=False,
        )
        upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=dummy")
        listing_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=1")
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="2019 iMac 27",
            price_text="¥3550",
            location="上海",
            description="2019 iMac 27 Retina 5K",
        )

    summary = build_run_summary(config, run_id)

    assert summary["run_id"] == run_id
    assert summary["result_quality"]["listing_count"] == 1
    assert summary["result_quality"]["priced_listing_ratio"] == 1.0
    assert summary["result_quality"]["located_listing_ratio"] == 1.0
    assert summary["result_quality"]["has_real_listing_data"] is True
    assert summary["result_quality"]["candidate_for_detail_capture"] is True
    assert summary["listings"][0]["listing_id"] == listing_id
    assert summary["listings"][0]["first_snapshot_id"] != listing_id
    assert summary["listings"][0]["price_text"] == "¥3550"
    assert summary["listings"][0]["source_type"] == "web_search"
    assert summary["listings"][0]["source_label"] == "网页搜索"
    assert summary["listings"][0]["collection_state"] == {
        "detail_snapshot_count": 0,
        "product_image_count": 0,
        "downloaded_product_image_count": 0,
        "ocr_result_count": 0,
        "has_detail": False,
        "has_downloaded_images": False,
        "has_ocr": False,
    }


def test_run_summary_separates_total_count_from_returned_listings(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-run-summary-limit.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="MacBook Air M2", city="上海")
        for index in range(25):
            listing_id = upsert_listing(
                conn,
                platform="xianyu",
                url=f"https://www.goofish.com/item?id=summary-{index}",
            )
            add_listing_snapshot(
                conn,
                listing_id=listing_id,
                run_id=run_id,
                title=f"候选 {index}",
                price_text=f"¥{3000 + index}" if index < 20 else None,
                location="上海" if index < 20 else None,
                description="测试候选",
            )
        conn.commit()

    summary = build_run_summary(config, run_id)

    assert summary["result_quality"]["listing_count"] == 25
    assert summary["result_quality"]["priced_listing_count"] == 20
    assert summary["result_quality"]["priced_listing_ratio"] == 0.8
    assert summary["result_quality"]["located_listing_ratio"] == 0.8
    assert summary["returned_listing_count"] == 20
    assert summary["listing_limit"] == 20
    assert summary["truncated"] is True
    assert len(summary["listings"]) == 20
