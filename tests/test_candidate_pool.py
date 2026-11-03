from __future__ import annotations

from pathlib import Path

from shopping_agent.candidate_pool import CandidatePoolOptions, build_candidate_pool
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_listing_snapshot,
    connect,
    create_search_run,
    initialize,
    upsert_listing,
)


def test_candidate_pool_default_capacity_supports_task_target() -> None:
    assert CandidatePoolOptions().limit == 600


def test_build_candidate_pool_merges_runs_and_scores_tool_signals() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_1 = create_search_run(conn, goal="2019 iMac 27 上海", city="上海")
        run_2 = create_search_run(conn, goal="2020 iMac 27 上海", city="上海")
        target_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=1")
        accessory_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=2")
        add_listing_snapshot(
            conn,
            listing_id=target_id,
            run_id=run_1,
            title="2019 iMac 27 5K 580X",
            price_text="¥5000",
            location="上海",
            description="2019 iMac 27 5K 580X 1T SSD",
        )
        add_listing_snapshot(
            conn,
            listing_id=target_id,
            run_id=run_2,
            title="2019 iMac 27 5K 580X 降价",
            price_text="¥4900",
            location="上海",
            description="2019 iMac 27 5K 580X 1T SSD",
        )
        add_listing_snapshot(
            conn,
            listing_id=accessory_id,
            run_id=run_2,
            title="iMac 27 电源线配件",
            price_text="¥99",
            location="上海",
            description="iMac 27 配件 电源线",
        )

    pool = build_candidate_pool(
        config,
        run_ids=[run_1, run_2],
        options=CandidatePoolOptions(goal="2019 iMac 27寸，上海优先"),
    )

    assert pool["candidate_count"] == 2
    assert pool["all_candidates"][0]["listing_id"] == target_id
    assert pool["all_candidates"][0]["signals"]["target_year_hint"] is True
    assert pool["all_candidates"][0]["signals"]["target_city_hint"] is True
    assert pool["all_candidates"][1]["signals"]["likely_accessory_or_parts"] is True


def test_candidate_pool_does_not_mark_full_imac_as_accessory_for_generic_parts_word() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool-accessory.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="2019 iMac 27 上海", city="上海")
        listing_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=3")
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="2019 iMac 27 5K 主机",
            price_text="¥5399",
            location="上海",
            description="完整 iMac 27 一体机，描述里提到各主要零部件估价，但不是配件单卖。",
        )

    pool = build_candidate_pool(config, run_ids=[run_id])

    assert pool["all_candidates"][0]["signals"]["likely_accessory_or_parts"] is False


def test_candidate_pool_shortlist_excludes_accessories_low_price_and_wrong_size() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool-noise.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="2019 iMac 27 5K", city="上海")
        good_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=10")
        cable_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=11")
        small_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=12")
        service_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=13")
        add_listing_snapshot(
            conn,
            listing_id=good_id,
            run_id=run_id,
            title="2019 iMac 27 5K 580X 上海自提",
            price_text="¥5000",
            location="上海",
            description="2019 iMac 27 5K 580X 32G 1T SSD",
        )
        add_listing_snapshot(
            conn,
            listing_id=cable_id,
            run_id=run_id,
            title="原装苹果 MFI mophie 充电线 CarPlay 数据线",
            price_text="¥39",
            location="广东",
            description="支持 CarPlay 的苹果认证数据线，不是 iMac 主机。",
        )
        add_listing_snapshot(
            conn,
            listing_id=small_id,
            run_id=run_id,
            title="21.5寸 苹果一体机 自提 2017年 iMac",
            price_text="¥5445",
            location="上海",
            description="21.5寸 iMac，自用闲置，非 27 寸。",
        )
        add_listing_snapshot(
            conn,
            listing_id=service_id,
            run_id=run_id,
            title="iMac 27 上海上门拆机升级固态内存 CPU",
            price_text="¥84",
            location="上海",
            description="iMac 维修升级服务，上门拆机升级。",
        )

    pool = build_candidate_pool(
        config,
        run_ids=[run_id],
        options=CandidatePoolOptions(shortlist_limit=3),
    )

    shortlist_ids = [candidate["listing_id"] for candidate in pool["shortlist_for_next_evidence"]]
    assert shortlist_ids == [good_id]
    by_id = {candidate["listing_id"]: candidate for candidate in pool["all_candidates"]}
    assert by_id[cable_id]["signals"]["likely_accessory_or_parts"] is True
    assert by_id[small_id]["signals"]["likely_non_target_size"] is True
    assert by_id[service_id]["signals"]["suspicious_low_price_for_target"] is True


def test_candidate_pool_does_not_mark_install_dual_system_note_as_service() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool-dual-system.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="2019 iMac 27 上海", city="上海")
        listing_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=14")
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="2019 iMac 27 5K 自用整机",
            price_text="¥5000",
            location="上海",
            description="自用闲置整机，可以帮忙安装双系统，非维修升级服务。",
        )

    pool = build_candidate_pool(config, run_ids=[run_id])

    assert pool["all_candidates"][0]["signals"]["likely_service_listing"] is False


def test_candidate_pool_uses_macbook_actions_for_macbook_goal() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool-macbook.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="macbook", city="上海")
        listing_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=20")
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="2021 MacBook Pro 14寸 M1 Pro 32G 512G",
            price_text="¥6000",
            location="广东",
            description="2021 MacBook Pro 14寸 M1 Pro 32G 512G 无拆修。",
        )

    pool = build_candidate_pool(
        config,
        run_ids=[run_id],
        options=CandidatePoolOptions(goal="MacBook Pro 14 32G"),
    )

    actions_text = "\n".join(pool["suggested_next_actions"])
    assert pool["all_candidates"][0]["signals"]["target_family"] == "macbook"
    assert pool["all_candidates"][0]["signals"]["mentions_macbook"] is True
    assert "iMac" not in actions_text
    assert "MacBook" in actions_text


def test_candidate_pool_does_not_treat_memory_or_core_count_as_macbook_screen_size() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool-macbook-size.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="macbook pro 14 32g", city="上海")
        pro_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=21")
        air_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=22")
        core_count_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=23")
        sixteen_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=24")
        add_listing_snapshot(
            conn,
            listing_id=pro_id,
            run_id=run_id,
            title="MacBook Pro 14寸 M1 Pro 32G 512G",
            price_text="¥6000",
            location="广东",
            description="2021 MacBook Pro 14寸 M1 Pro 32G 512G。",
        )
        add_listing_snapshot(
            conn,
            listing_id=air_id,
            run_id=run_id,
            title="MacBook Air 13寸 M4 16G+512G",
            price_text="¥5899",
            location="上海",
            description="MacBook Air 13寸，不是 Pro 目标机型。",
        )
        add_listing_snapshot(
            conn,
            listing_id=core_count_id,
            run_id=run_id,
            title="MacBook Pro M1 Pro 10+16核 32G 512G",
            price_text="¥6200",
            location="上海",
            description="描述只写 10+16 核，没有写屏幕尺寸。",
        )
        add_listing_snapshot(
            conn,
            listing_id=sixteen_id,
            run_id=run_id,
            title="MacBook Pro 16寸 M1 Pro 32G 512G",
            price_text="¥6000",
            location="上海",
            description="2021 MacBook Pro 16寸 M1 Pro 32G 512G。",
        )

    pool = build_candidate_pool(
        config,
        run_ids=[run_id],
        options=CandidatePoolOptions(goal="MacBook Pro 14寸 32G"),
    )

    by_id = {candidate["listing_id"]: candidate for candidate in pool["all_candidates"]}
    assert by_id[pro_id]["signals"]["mentions_14"] is True
    assert by_id[pro_id]["signals"]["mentions_target_screen_size"] is True
    assert by_id[pro_id]["signals"]["likely_non_target_size"] is False
    assert by_id[air_id]["signals"]["mentions_13"] is True
    assert by_id[air_id]["signals"]["mentions_16"] is False
    assert by_id[air_id]["signals"]["likely_non_target_size"] is True
    assert by_id[core_count_id]["signals"]["mentions_16"] is False
    assert by_id[core_count_id]["signals"]["likely_non_target_size"] is False
    assert by_id[sixteen_id]["signals"]["mentions_16"] is True
    assert by_id[sixteen_id]["signals"]["likely_non_target_size"] is True
    assert by_id[pro_id]["tool_priority_score"] > by_id[air_id]["tool_priority_score"]
    shortlist_ids = [candidate["listing_id"] for candidate in pool["shortlist_for_next_evidence"]]
    assert sixteen_id not in shortlist_ids


def test_candidate_pool_surfaces_near_duplicate_price_anchors() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool-near-duplicates.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_1 = create_search_run(conn, goal="MacBook Pro 14 32G", city="上海")
        run_2 = create_search_run(conn, goal="A2442 32G", city="上海")
        first_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=31")
        second_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=32")
        other_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=33")
        add_listing_snapshot(
            conn,
            listing_id=first_id,
            run_id=run_1,
            title="2021 MacBook Pro 14寸 M1 Pro 32G 512G",
            price_text="¥6000",
            location="江西",
            seller_name="苹果二手严选",
            description="A2442 M1 Pro 14寸 32G 512G 国行，电池 90。",
        )
        add_listing_snapshot(
            conn,
            listing_id=second_id,
            run_id=run_2,
            title="MacBook Pro 14 M1Pro 32GB 512GB",
            price_text="¥5880",
            location="江西",
            seller_name="苹果二手严选",
            description="21款 A2442，M1 Pro，14寸，32GB，512GB。",
        )
        add_listing_snapshot(
            conn,
            listing_id=other_id,
            run_id=run_2,
            title="MacBook Air 13寸 M4 16G 512G",
            price_text="¥5899",
            location="上海",
            seller_name="个人自用",
            description="MacBook Air 13寸，不是目标配置。",
        )

    pool = build_candidate_pool(
        config,
        run_ids=[run_1, run_2],
        options=CandidatePoolOptions(goal="MacBook Pro 14寸 32G"),
    )

    assert len(pool["near_duplicate_groups"]) == 1
    group = pool["near_duplicate_groups"][0]
    assert group["confidence"] == "high"
    assert set(group["listing_ids"]) == {first_id, second_id}
    assert group["price_summary"]["min"] == 5880
    assert group["price_summary"]["max"] == 6000
    assert "same_seller" in group["reason_codes"]
    assert "memory:32g" in group["shared_spec_tokens"]
    by_id = {candidate["listing_id"]: candidate for candidate in pool["all_candidates"]}
    assert by_id[first_id]["near_duplicate_group_ids"] == ["ndg-1"]
    assert by_id[second_id]["near_duplicate_group_ids"] == ["ndg-1"]
    assert by_id[other_id]["near_duplicate_group_ids"] == []
    assert "近似候选" in "\n".join(pool["suggested_next_actions"])


def test_candidate_pool_near_duplicates_ignore_noise() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool-near-duplicate-noise.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="2019 iMac 27", city="上海")
        first_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=41")
        second_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=42")
        add_listing_snapshot(
            conn,
            listing_id=first_id,
            run_id=run_id,
            title="iMac 27 电源线配件",
            price_text="¥99",
            location="上海",
            seller_name="苹果配件店",
            description="iMac 27 配件 电源线。",
        )
        add_listing_snapshot(
            conn,
            listing_id=second_id,
            run_id=run_id,
            title="iMac 27 电源线配件 原装线",
            price_text="¥119",
            location="上海",
            seller_name="苹果配件店",
            description="iMac 27 配件 电源线。",
        )

    pool = build_candidate_pool(
        config,
        run_ids=[run_id],
        options=CandidatePoolOptions(goal="2019 iMac 27寸"),
    )

    assert pool["near_duplicate_groups"] == []


def test_candidate_pool_near_duplicates_reject_conflicting_storage() -> None:
    config = AppConfig(database_path=Path("data/test-candidate-pool-near-duplicate-storage.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="MacBook Pro 14 32G", city="上海")
        first_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=51")
        second_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=52")
        add_listing_snapshot(
            conn,
            listing_id=first_id,
            run_id=run_id,
            title="2021 MacBook Pro 14寸 M1 Pro 32G 1TB",
            price_text="¥6280",
            location="江西",
            seller_name="苹果二手严选",
            description="A2442 M1 Pro 14寸 32G 1TB。",
        )
        add_listing_snapshot(
            conn,
            listing_id=second_id,
            run_id=run_id,
            title="2021 MacBook Pro 14寸 M1 Pro 32G 512G",
            price_text="¥5780",
            location="江西",
            seller_name="苹果二手严选",
            description="A2442 M1 Pro 14寸 32G 512G。",
        )

    pool = build_candidate_pool(
        config,
        run_ids=[run_id],
        options=CandidatePoolOptions(goal="MacBook Pro 14寸 32G"),
    )

    assert pool["near_duplicate_groups"] == []
