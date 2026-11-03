from __future__ import annotations

from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_listing_snapshot,
    connect,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.market_baseline import MarketBaselineOptions, build_market_baseline


def test_market_baseline_groups_same_spec_prices_and_excludes_noise() -> None:
    config = AppConfig(database_path=Path("data/test-market-baseline.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="MacBook Pro 14 32G", city="上海")
        prices = [6000, 5800, 6200, 5900]
        for index, price in enumerate(prices, start=1):
            listing_id = upsert_listing(conn, platform="xianyu", url=f"https://www.goofish.com/item?id={100 + index}")
            add_listing_snapshot(
                conn,
                listing_id=listing_id,
                run_id=run_id,
                title=f"2021 MacBook Pro 14寸 M1 Pro 32G 512G 样本 {index}",
                price_text=f"¥{price}",
                location="江西",
                seller_name="个人自用" if index == 1 else None,
                description="A2442 M1 Pro 14寸 32G 512G。",
            )
        one_tb_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=201")
        accessory_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=202")
        add_listing_snapshot(
            conn,
            listing_id=one_tb_id,
            run_id=run_id,
            title="2021 MacBook Pro 14寸 M1 Pro 32G 1TB",
            price_text="¥6800",
            location="上海",
            description="A2442 M1 Pro 14寸 32G 1TB。",
        )
        add_listing_snapshot(
            conn,
            listing_id=accessory_id,
            run_id=run_id,
            title="MacBook Pro 14寸 保护壳 配件",
            price_text="¥59",
            location="上海",
            description="保护壳配件，不是电脑。",
        )

    baseline = build_market_baseline(
        config,
        run_ids=[run_id],
        options=MarketBaselineOptions(goal="MacBook Pro 14寸 32G"),
    )

    assert baseline["source_scope"] == "local_candidate_pool_only"
    assert baseline["price_evidence_level"]["level"] == "A_local_active_usable"
    assert baseline["sample_policy"]["priced_candidate_count"] == 6
    assert baseline["sample_policy"]["excluded_noise_sample_count"] == 1
    assert baseline["sample_policy"]["exclusion_summary"][0]["signal_key"] == "likely_accessory_or_parts"
    assert baseline["overall"]["priced_clean_sample_count"] == 5
    assert baseline["overall"]["priced_excluded_noise_sample_count"] == 1
    group_512 = next(
        group
        for group in baseline["spec_price_groups"]
        if "storage:512g" in group["spec_tokens"]
    )
    assert group_512["sample_count"] == 4
    assert group_512["source_quality"] == "local_usable"
    assert group_512["price_evidence_level"]["level"] == "A_local_active_usable"
    assert group_512["price_summary"]["min"] == 5800
    assert group_512["price_summary"]["median"] == 5950
    assert group_512["price_summary"]["max"] == 6200
    assert accessory_id not in group_512["listing_ids"]
    assert one_tb_id not in group_512["listing_ids"]
    assert any("storage:1t" in group["spec_tokens"] for group in baseline["spec_price_groups"])


def test_market_baseline_marks_single_sample_as_weak() -> None:
    config = AppConfig(database_path=Path("data/test-market-baseline-single.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="2019 iMac 27", city="上海")
        listing_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=301")
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="2019 iMac 27 5K i5 32G 1TB SSD",
            price_text="¥4500",
            location="上海",
            description="2019 iMac 27 5K i5 32G 1TB SSD。",
        )

    baseline = build_market_baseline(
        config,
        run_ids=[run_id],
        options=MarketBaselineOptions(goal="2019 iMac 27寸"),
    )

    assert baseline["overall"]["source_quality"] == "single_local_sample"
    assert baseline["overall"]["price_evidence_level"]["level"] == "weak_single_local_active_sample"
    assert baseline["spec_price_groups"][0]["source_quality"] == "single_local_sample"
    assert baseline["spec_price_groups"][0]["price_evidence_level"]["level"] == "weak_single_local_active_sample"
