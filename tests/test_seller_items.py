from __future__ import annotations

from pathlib import Path

from shopping_agent.candidate_query import CandidateQueryOptions, query_candidates
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_detail_snapshot,
    add_listing_snapshot,
    add_seller_items,
    connect,
    create_search_run,
    fetch_seller_items_for_listing,
    initialize,
    upsert_listing,
)


def _seed_with_seller_items(config: AppConfig, tmp_path: Path) -> tuple[int, int, int]:
    initialize(config.database_path)
    text_dir = tmp_path / "sitexts"
    text_dir.mkdir()
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="MacBook Air M2", city="上海")
        # Listing A: personal seller, in-stock items include a broadband transfer
        a_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=8001")
        add_listing_snapshot(conn, listing_id=a_id, run_id=run_id, title="MacBook Air M2",
            price_text="¥3666", location="深圳", seller_name="个人卖家A", description="自用近新",
            seller_credit_level="信用极好", seller_sold_count=6, seller_realname_verified=True)
        add_seller_items(conn, seller_listing_id=a_id, seller_name="个人卖家A", items=[
            {"itemId": "1001", "title": "搬家宽带不用了，千兆宽带转让"},
            {"itemId": "1002", "title": "MacBook Air笔记本"},
        ], source_run_id=run_id)
        # Listing B: professional merchant, many electronics in stock
        b_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=8002")
        add_listing_snapshot(conn, listing_id=b_id, run_id=run_id, title="MacBook Air M2 商家",
            price_text="¥3699", location="成都", seller_name="专业商家B", description="95新商家机",
            seller_credit_level="信用极好", seller_sold_count=1250, seller_realname_verified=True)
        add_seller_items(conn, seller_listing_id=b_id, seller_name="专业商家B", items=[
            {"itemId": "2001", "title": "MacBook Pro M1 16G"},
            {"itemId": "2002", "title": "MacBook Air M2 13寸"},
            {"itemId": "2003", "title": "MacBook Pro M2 Pro"},
            {"itemId": "2004", "title": "iMac 27寸"},
        ], source_run_id=run_id)
        # Listing C: no seller items captured
        c_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=8003")
        add_listing_snapshot(conn, listing_id=c_id, run_id=run_id, title="MacBook Air M2 C",
            price_text="¥3450", location="上海", seller_name="卖家C", description="自用",
            seller_sold_count=5)
        conn.commit()
    return run_id, a_id, b_id, c_id


def test_seller_items_persisted_and_fetched(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-seller-items.sqlite")
    run_id, a_id, b_id, _ = _seed_with_seller_items(config, tmp_path)
    with connect(config.database_path) as conn:
        a_items = fetch_seller_items_for_listing(conn, a_id)
        assert len(a_items) == 2
        assert any("宽带" in (r["title"] or "") for r in a_items)
        b_items = fetch_seller_items_for_listing(conn, b_id)
        assert len(b_items) == 4


def test_query_candidates_omits_seller_other_items(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-seller-items.sqlite")
    run_id, a_id, b_id, c_id = _seed_with_seller_items(config, tmp_path)
    r = query_candidates(config, CandidateQueryOptions(run_ids=[run_id], limit=10))
    by_id = {c["listing_id"]: c for c in r["candidates"]}
    assert all("seller_other_items" not in by_id[listing_id] for listing_id in (a_id, b_id, c_id))
