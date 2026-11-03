from __future__ import annotations

from pathlib import Path

from shopping_agent.cli import build_parser
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_listing_snapshot,
    connect,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.run_diff import build_run_diff


def test_run_diff_detects_new_missing_and_price_changes_by_item_id() -> None:
    config = AppConfig(database_path=Path("data/test-run-diff.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        before_run = create_search_run(conn, goal="MacBook Pro M1", city="上海")
        after_run = create_search_run(conn, goal="MacBook Pro M1", city="上海")
        changed_before_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=100&categoryId=old",
        )
        missing_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=200")
        changed_after_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=100&categoryId=new",
        )
        new_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=300")

        add_listing_snapshot(
            conn,
            listing_id=changed_before_id,
            run_id=before_run,
            title="MacBook Pro 14 M1 Pro 32G",
            price_text="¥6200",
            location="上海",
        )
        add_listing_snapshot(
            conn,
            listing_id=missing_id,
            run_id=before_run,
            title="MacBook Pro 13 M1 16G",
            price_text="¥4300",
            location="上海",
        )
        add_listing_snapshot(
            conn,
            listing_id=changed_after_id,
            run_id=after_run,
            title="MacBook Pro 14 M1 Pro 32G 降价",
            price_text="¥5900",
            location="上海",
        )
        add_listing_snapshot(
            conn,
            listing_id=new_id,
            run_id=after_run,
            title="MacBook Pro 14 M2 Pro 16G",
            price_text="¥6800",
            location="杭州",
        )

    diff = build_run_diff(config, before_run_id=before_run, after_run_id=after_run, goal="MacBook Pro M1")

    assert diff["summary"]["before_count"] == 2
    assert diff["summary"]["after_count"] == 2
    assert diff["summary"]["common_count"] == 1
    assert diff["summary"]["new_count"] == 1
    assert diff["summary"]["missing_count"] == 1
    assert diff["summary"]["price_drop_count"] == 1
    assert diff["price_changes"][0]["identity_key"] == "xianyu:item:100"
    assert diff["price_changes"][0]["direction"] == "down"
    assert diff["price_changes"][0]["delta"] == -300
    assert diff["new_listings"][0]["listing_id"] == new_id
    assert diff["missing_listings"][0]["listing_id"] == missing_id
    assert "title" in diff["text_changes"][0]["changed_fields"]


def test_run_diff_cli_accepts_required_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "run-diff",
            "--before-run-id",
            "10",
            "--after-run-id",
            "11",
            "--goal",
            "MacBook Pro M1",
            "--pretty",
        ]
    )

    assert args.command == "run-diff"
    assert args.before_run_id == 10
    assert args.after_run_id == 11
    assert args.goal == "MacBook Pro M1"
    assert args.pretty is True
