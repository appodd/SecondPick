from __future__ import annotations

import sqlite3
from pathlib import Path

from shopping_agent.db import (
    add_listing_snapshot,
    connect,
    create_search_run,
    fetch_latest_listing_snapshots_for_run,
    initialize,
    upsert_listing,
)


def test_search_card_condition_is_persisted_separately(tmp_path: Path) -> None:
    database_path = tmp_path / "shopping.sqlite"
    initialize(database_path)

    with connect(database_path) as conn:
        run_id = create_search_run(conn, goal="R9000P 4060", city="上海")
        listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=123",
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="R9000P 2023",
            price_text="¥5299",
            location="上海",
            seller_name="示例卖家",
            description="R9-7945HX RTX 4060 16G+1T",
            search_condition="几乎全新",
        )

        row = fetch_latest_listing_snapshots_for_run(conn, run_id)[0]

    assert row["title"] == "R9000P 2023"
    assert row["description"] == "R9-7945HX RTX 4060 16G+1T"
    assert row["seller_name"] == "示例卖家"
    assert row["search_condition"] == "几乎全新"


def test_latest_listing_snapshots_use_collection_time_and_keep_first_seen_order(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "latest-by-time.sqlite"
    initialize(database_path)

    with connect(database_path) as conn:
        run_id = create_search_run(conn, goal="R9000P 4060", city="上海")
        first_listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=first",
        )
        second_listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=second",
        )
        newer_snapshot_id = add_listing_snapshot(
            conn,
            listing_id=first_listing_id,
            run_id=run_id,
            title="newer by collection time",
        )
        add_listing_snapshot(
            conn,
            listing_id=second_listing_id,
            run_id=run_id,
            title="second listing",
        )
        older_snapshot_id = add_listing_snapshot(
            conn,
            listing_id=first_listing_id,
            run_id=run_id,
            title="later insert with older collection time",
        )
        conn.execute(
            "UPDATE listing_snapshots SET collected_at = ? WHERE id = ?",
            ("2026-08-04T12:00:00+00:00", newer_snapshot_id),
        )
        conn.execute(
            "UPDATE listing_snapshots SET collected_at = ? WHERE id = ?",
            ("2026-08-03T12:00:00+00:00", older_snapshot_id),
        )
        conn.commit()

        rows = fetch_latest_listing_snapshots_for_run(conn, run_id)

    assert [row["listing_id"] for row in rows] == [first_listing_id, second_listing_id]
    assert rows[0]["id"] == newer_snapshot_id
    assert rows[0]["title"] == "newer by collection time"


def test_initialize_migrates_existing_listing_snapshots(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE listing_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              listing_id INTEGER NOT NULL,
              run_id INTEGER NOT NULL,
              title TEXT,
              description TEXT,
              collected_at TEXT NOT NULL
            );
            INSERT INTO listing_snapshots (
              listing_id, run_id, title, description, collected_at
            ) VALUES (1, 1, '旧标题', '旧描述', '2026-08-03T00:00:00+00:00');
            """
        )

    initialize(database_path)

    with sqlite3.connect(database_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(listing_snapshots)")
        }
        legacy_row = conn.execute(
            "SELECT title, description, search_condition FROM listing_snapshots"
        ).fetchone()

    assert "search_condition" in columns
    assert legacy_row == ("旧标题", "旧描述", None)


def test_initialize_migrates_existing_detail_snapshots_for_attributes(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-detail.sqlite"
    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE detail_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              listing_id INTEGER NOT NULL,
              run_id INTEGER,
              url TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            INSERT INTO detail_snapshots (listing_id, run_id, url, created_at)
            VALUES (1, 1, 'https://www.goofish.com/item?id=1', '2026-08-03T00:00:00+00:00');
            """
        )

    initialize(database_path)

    with sqlite3.connect(database_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(detail_snapshots)")
        }
        legacy_row = conn.execute(
            "SELECT attributes_json, attributes_source FROM detail_snapshots"
        ).fetchone()

    assert {"attributes_json", "attributes_source"} <= columns
    assert legacy_row == ("{}", None)
