from __future__ import annotations

import json
from pathlib import Path

from shopping_agent.candidate_query import CandidateQueryOptions, query_candidates
from shopping_agent.cli import build_parser
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_detail_snapshot,
    add_listing_snapshot,
    add_seller_items,
    connect,
    create_search_run,
    initialize,
    upsert_listing,
)


def _make_detail(stats, price, desc, condition, repair):
    lines = [
        "搜索", "网页版发闲置功能又升级啦！", "卖家甲", "上海", "1小时前来过",
        *stats, "闲鱼号", "担保交易", "举报", "¥", price, "包邮", "2人想要", "50浏览",
        desc,
        "品", "牌", "：", "Apple/苹果", "型", "号", "：", "MacBook Air 2022 13寸",
        "内", "存", "容", "量", "：", "8GB", "拆", "修", "：", repair,
        "成", "色", "：", condition, "硬", "盘", "容", "量", "：", "256GB",
        "聊一聊", "立即购买", "收藏",
    ]
    return "\n".join(lines)


def _seed(config: AppConfig, tmp_path: Path) -> tuple[int, dict]:
    initialize(config.database_path)
    text_dir = tmp_path / "qtexts"
    text_dir.mkdir()
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="MacBook Air M2", city="上海")
        ids = {}
        specs = [
            ("mint_low", 2600, "来闲鱼3年", ["来闲鱼3年", "卖出5件宝贝", "好评率100%"], "自用近新无硬伤", "几乎全新", "无任何拆修", None),
            ("damaged_low", 2499, "来闲鱼9年", ["来闲鱼9年", "卖出3829件宝贝", "好评率93%"], "屏幕碎角闪屏", "明显磕碰划痕", "无任何拆修", "信用良好"),
            ("fair_personal", 3690, "来闲鱼8年", ["来闲鱼8年", "卖出48件宝贝", "好评率100%"], "箱说全", "细微磕碰划痕", "无任何拆修", None),
            ("fair_pro", 3699, "来闲鱼8年", ["来闲鱼8年", "卖出1249件宝贝", "好评率98%"], "95新商家机", "几乎全新", "无任何拆修", "信用极好"),
        ]
        for key, price, _y, stats, desc, cond, repair, credit in specs:
            lid = upsert_listing(conn, platform="xianyu", url=f"https://www.goofish.com/item?id=9{key}")
            ids[key] = lid
            kwargs = dict(
                listing_id=lid, run_id=run_id, title=f"MacBook Air M2 {key}",
                price_text=f"¥{price}", location="上海", seller_name=f"卖家{key}",
                description=desc, seller_good_rate=stats[2].replace("好评率", ""),
            )
            if "3829" in stats[1]:
                kwargs["seller_sold_count"] = 3829
                kwargs["seller_registered_days"] = 3285
            elif "1249" in stats[1]:
                kwargs["seller_sold_count"] = 1249
                kwargs["seller_registered_days"] = 2920
            elif "48" in stats[1]:
                kwargs["seller_sold_count"] = 48
                kwargs["seller_registered_days"] = 2920
            else:
                kwargs["seller_sold_count"] = 5
                kwargs["seller_registered_days"] = 1095
            if credit:
                kwargs["seller_credit_level"] = credit
                kwargs["seller_realname_verified"] = True
            add_listing_snapshot(conn, **kwargs)
            tpath = text_dir / f"{key}.txt"
            tpath.write_text(_make_detail(stats, str(price), desc, cond, repair), encoding="utf-8")
            add_detail_snapshot(conn, lid, run_id, f"https://www.goofish.com/item?id=9{key}",
                                f"MBA {key}", text_dir / f"{key}_s.png", text_dir / f"{key}.html",
                                tpath, text_dir / f"{key}.links.txt", text_dir / f"{key}.images.txt",
                                0, 0, False)
        conn.commit()
    return run_id, ids


def test_query_candidates_condition_best(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query.sqlite")
    run_id, ids = _seed(config, tmp_path)
    r = query_candidates(config, CandidateQueryOptions(
        run_ids=[run_id], condition="几乎全新", sort_by="condition_best", limit=10))
    assert r["returned_count"] == 2
    result_ids = [c["listing_id"] for c in r["candidates"]]
    assert ids["mint_low"] in result_ids
    assert ids["fair_pro"] in result_ids
    for c in r["candidates"]:
        assert c["mechanical_facts"]["condition"] == "几乎全新"


def test_query_candidates_low_price_has_damage_keywords(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-low.sqlite")
    run_id, ids = _seed(config, tmp_path)
    r = query_candidates(config, CandidateQueryOptions(
        run_ids=[run_id], price_ratio_max=0.85, sort_by="price_asc", limit=10))
    assert r["returned_count"] == 2
    damaged = [c for c in r["candidates"] if c["listing_id"] == ids["damaged_low"]][0]
    assert "碎" in damaged["damage_keyword_hits"]
    assert "闪屏" in damaged["damage_keyword_hits"]
    mint = [c for c in r["candidates"] if c["listing_id"] == ids["mint_low"]][0]
    assert mint["damage_keyword_hits"] == []


def test_query_candidates_does_not_treat_ten_thousand_unit_as_one_yuan(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-ten-thousand.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="camera body", city="上海")
        listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=ten-thousand-price",
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="富士 X-S20 套机",
            price_text="¥1.07万",
            location="上海",
        )
        conn.commit()

    result = query_candidates(
        config,
        CandidateQueryOptions(
            run_ids=[run_id],
            max_price=7200,
            locations=["上海"],
            limit=10,
        ),
    )

    assert result["deduplicated_count"] == 1
    assert result["eligible_count"] == 0
    assert result["returned_count"] == 0
    assert result["market_context"]["min"] == 10_700


def test_query_candidates_high_volume_sellers(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-pro.sqlite")
    run_id, ids = _seed(config, tmp_path)
    r = query_candidates(config, CandidateQueryOptions(
        run_ids=[run_id], seller_sold_min=200, sort_by="seller_most_active", limit=10))
    assert r["returned_count"] == 2
    assert r["candidates"][0]["listing_id"] == ids["damaged_low"]
    facts = r["candidates"][0]["mechanical_facts"]
    assert facts["seller_sold_count"] == 3829
    assert "seller_type" not in facts


def test_query_candidates_sold_bounds_distinguish_unknown_from_zero(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-sold-bounds.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="seller sold bounds", city="上海")
        ids = {}
        for label, sold_count in (("unknown", None), ("zero", 0), ("fifty", 50), ("two_hundred", 200)):
            listing_id = upsert_listing(
                conn,
                platform="xianyu",
                url=f"https://www.goofish.com/item?id={label}",
            )
            ids[label] = listing_id
            add_listing_snapshot(
                conn,
                listing_id=listing_id,
                run_id=run_id,
                title=label,
                seller_sold_count=sold_count,
            )

    all_result = query_candidates(config, CandidateQueryOptions(run_ids=[run_id]))
    max_result = query_candidates(
        config,
        CandidateQueryOptions(run_ids=[run_id], seller_sold_max=50),
    )
    min_result = query_candidates(
        config,
        CandidateQueryOptions(run_ids=[run_id], seller_sold_min=50),
    )

    assert {item["listing_id"] for item in all_result["candidates"]} == set(ids.values())
    assert {item["listing_id"] for item in max_result["candidates"]} == {
        ids["zero"],
        ids["fifty"],
    }
    assert {item["listing_id"] for item in min_result["candidates"]} == {
        ids["fifty"],
        ids["two_hundred"],
    }


def test_query_candidates_rejects_seller_type_flags() -> None:
    parser = build_parser()

    for flag in ("--personal-only", "--professional-only"):
        try:
            parser.parse_args(["query-candidates", "--run-id", "1", flag])
        except SystemExit:
            continue
        raise AssertionError(f"Expected argparse to reject {flag}")


def test_query_candidates_cli_uses_price_ratio_flags_only() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "query-candidates",
            "--run-id",
            "1",
            "--price-ratio-min",
            "0.75",
            "--price-ratio-max",
            "1.1",
        ]
    )

    assert args.price_ratio_min == 0.75
    assert args.price_ratio_max == 1.1
    for flag in ("--price-pct-min", "--price-pct-max"):
        try:
            parser.parse_args(["query-candidates", "--run-id", "1", flag, "0.85"])
        except SystemExit:
            continue
        raise AssertionError(f"Expected argparse to reject {flag}")


def test_query_candidates_single_listing_returns_compact_structured_facts(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-single.sqlite")
    run_id, ids = _seed(config, tmp_path)
    r = query_candidates(config, CandidateQueryOptions(
        run_ids=[run_id], listing_ids=[ids["fair_pro"]]))
    assert r["returned_count"] == 1
    c = r["candidates"][0]
    assert c["listing_id"] == ids["fair_pro"]
    assert c["mechanical_facts"]["condition"] == "几乎全新"
    assert c["mechanical_facts"]["memory"] == "8GB"
    assert c["mechanical_facts"]["storage"] == "256GB"
    assert "detail_text_excerpt" not in c


def test_query_candidates_returns_evidence_not_labels(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-nolabel.sqlite")
    run_id, ids = _seed(config, tmp_path)
    r = query_candidates(config, CandidateQueryOptions(run_ids=[run_id], limit=10))
    for c in r["candidates"]:
        assert set(c) == {
            "listing_id",
            "source_run_ids",
            "url",
            "title",
            "search_description",
            "search_description_status",
            "price_text",
            "price_value",
            "price_ratio_to_median",
            "location",
            "search_condition",
            "has_detail",
            "mechanical_facts",
            "damage_keyword_hits",
            "filter_evidence",
        }
        assert set(c["mechanical_facts"]) == {
            "condition",
            "repair",
            "memory",
            "storage",
            "model",
            "seller_sold_count",
            "seller_credit_level",
            "seller_realname_verified",
        }
        assert "seller_type" not in c["mechanical_facts"]
        assert "evidence" not in c
        assert "seller_other_items" not in c
        assert "collection_state" not in c
        assert "detail_text_excerpt" not in c
    assert "market_context" in r
    assert "query_hint" in r


def test_query_candidates_ignores_duplicate_run_ids(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-repeated-run.sqlite")
    run_id, ids = _seed(config, tmp_path)

    result = query_candidates(
        config,
        CandidateQueryOptions(run_ids=[run_id, run_id], limit=10),
    )

    assert result["run_ids"] == [run_id]
    assert result["returned_count"] == len(ids)
    assert len({item["listing_id"] for item in result["candidates"]}) == len(ids)
    assert result["market_context"]["priced_count"] == len(ids)
    assert all(item["source_run_ids"] == [run_id] for item in result["candidates"])


def test_query_candidates_deduplicates_across_runs_and_uses_latest_snapshot(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-multi-run.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        first_run = create_search_run(conn, goal="MacBook Air M2", city="上海")
        second_run = create_search_run(conn, goal="A2681", city="上海")
        shared_id = upsert_listing(
            conn, platform="xianyu", url="https://www.goofish.com/item?id=shared"
        )
        unique_id = upsert_listing(
            conn, platform="xianyu", url="https://www.goofish.com/item?id=unique"
        )
        add_listing_snapshot(
            conn,
            listing_id=shared_id,
            run_id=first_run,
            title="旧标题",
            price_text="¥3600",
            location="上海",
            description="旧描述",
        )
        add_listing_snapshot(
            conn,
            listing_id=shared_id,
            run_id=second_run,
            title="新标题",
            price_text="¥3500",
            location="上海",
            description="新描述",
        )
        add_listing_snapshot(
            conn,
            listing_id=unique_id,
            run_id=second_run,
            title="独有候选",
            price_text="¥4500",
            location="杭州",
            description="独有描述",
        )
        conn.commit()

    result = query_candidates(
        config,
        CandidateQueryOptions(run_ids=[first_run, second_run], limit=10),
    )

    assert result["returned_count"] == 2
    shared = next(item for item in result["candidates"] if item["listing_id"] == shared_id)
    assert shared["title"] == "新标题"
    assert shared["price_value"] == 3500
    assert shared["source_run_ids"] == [first_run, second_run]
    assert result["market_context"]["priced_count"] == 2
    assert result["market_context"]["median"] == 4000


def test_query_candidates_uses_latest_detail_from_requested_runs(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-latest-detail.sqlite")
    initialize(config.database_path)
    old_detail = tmp_path / "old-detail.txt"
    new_detail = tmp_path / "new-detail.txt"
    old_detail.write_text(
        _make_detail([], "3600", "旧详情", "明显磕碰划痕", "无任何拆修"),
        encoding="utf-8",
    )
    new_detail.write_text(
        _make_detail([], "3500", "新详情", "几乎全新", "无任何拆修"),
        encoding="utf-8",
    )
    with connect(config.database_path) as conn:
        first_run = create_search_run(conn, goal="MacBook Air M2", city="上海")
        second_run = create_search_run(conn, goal="A2681", city="上海")
        listing_id = upsert_listing(
            conn, platform="xianyu", url="https://www.goofish.com/item?id=detail-shared"
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=first_run,
            title="旧快照",
            price_text="¥3600",
            location="上海",
            description="旧详情",
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=second_run,
            title="新快照",
            price_text="¥3500",
            location="上海",
            description="新详情",
        )
        add_detail_snapshot(
            conn,
            listing_id,
            first_run,
            "https://www.goofish.com/item?id=detail-shared",
            "旧详情",
            tmp_path / "old.png",
            tmp_path / "old.html",
            old_detail,
            tmp_path / "old.links.txt",
            tmp_path / "old.images.txt",
            0,
            0,
            False,
        )
        add_detail_snapshot(
            conn,
            listing_id,
            second_run,
            "https://www.goofish.com/item?id=detail-shared",
            "新详情",
            tmp_path / "new.png",
            tmp_path / "new.html",
            new_detail,
            tmp_path / "new.links.txt",
            tmp_path / "new.images.txt",
            0,
            0,
            False,
        )
        conn.commit()

    result = query_candidates(
        config,
        CandidateQueryOptions(
            run_ids=[first_run, second_run],
            listing_ids=[listing_id],
        ),
    )

    candidate = result["candidates"][0]
    assert candidate["mechanical_facts"]["condition"] == "几乎全新"
    assert "detail_text_excerpt" not in candidate


def test_query_candidates_omits_saved_seller_other_items(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-seller-items.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="MacBook Air M2", city="上海")
        listing_id = upsert_listing(
            conn, platform="xianyu", url="https://www.goofish.com/item?id=seller-items"
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="卖家在售测试",
            price_text="¥3500",
            location="上海",
            description="测试",
        )
        add_seller_items(
            conn,
            seller_listing_id=listing_id,
            seller_name="卖家甲",
            source_run_id=run_id,
            items=[
                {"itemId": "same", "title": "同一商品", "link": "item://same"},
                {"itemId": "same", "title": "同一商品重复", "link": "item://same"},
            ],
        )
        conn.commit()

    result = query_candidates(
        config,
        CandidateQueryOptions(run_ids=[run_id], listing_ids=[listing_id]),
    )

    assert "seller_other_items" not in result["candidates"][0]


def test_query_candidates_prefers_persisted_api_attributes_without_deep_provenance(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-provenance.sqlite")
    initialize(config.database_path)
    detail_text = tmp_path / "detail.txt"
    detail_text.write_text(
        "\n".join(
            [
                "搜索",
                "卖家甲",
                "上海",
                "来闲鱼6年",
                "卖出14件宝贝",
                "¥",
                "3100",
                "当前商品描述",
                "品",
                "牌",
                "：",
                "Apple/苹果",
                "型",
                "号",
                "：",
                "iPhone 15 Pro",
                "存",
                "储",
                "容",
                "量",
                "：",
                "128GB",
                "成",
                "色",
                "：",
                "几乎全新",
                "拆",
                "修",
                "和",
                "功",
                "能",
                "：",
                "无任何维修",
                "为你推荐",
                "其他手机 12GB 运存",
            ]
        ),
        encoding="utf-8",
    )
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="iPhone 15 Pro", city="上海")
        listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=provenance",
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="iPhone 15 Pro 原色",
            price_text="¥3100",
            location="上海",
            seller_name="卖家甲",
            description="电池95，全原装无拆修",
            seller_registered_days=2413,
            seller_sold_count=14,
            seller_realname_verified=True,
        )
        add_detail_snapshot(
            conn,
            listing_id,
            run_id,
            "https://www.goofish.com/item?id=provenance",
            "详情",
            tmp_path / "detail.png",
            tmp_path / "detail.html",
            detail_text,
            tmp_path / "detail.links.txt",
            tmp_path / "detail.images.txt",
            0,
            0,
            False,
            attributes_json=json.dumps(
                {
                    "型号": "iPhone 15 Pro",
                    "存储容量": "128GB",
                    "成色": "几乎全新",
                    "拆修和功能": "无任何维修",
                },
                ensure_ascii=False,
            ),
            attributes_source="xianyu_api_item_labels",
        )

    result = query_candidates(
        config,
        CandidateQueryOptions(run_ids=[run_id], listing_ids=[listing_id]),
    )

    candidate = result["candidates"][0]
    assert candidate["mechanical_facts"]["model"] == "iPhone 15 Pro"
    assert candidate["mechanical_facts"]["storage"] == "128GB"
    assert candidate["mechanical_facts"]["memory"] is None
    assert "evidence" not in candidate
    assert "evidence_conflicts" not in candidate


def test_query_candidates_leaves_attribute_conflicts_to_candidate_evidence(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-conflict.sqlite")
    initialize(config.database_path)
    detail_text = tmp_path / "conflict.txt"
    detail_text.write_text(
        _make_detail([], "3100", "详情", "明显磕碰划痕", "更换过屏幕"),
        encoding="utf-8",
    )
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="iPhone 15 Pro", city="上海")
        listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=conflict",
        )
        add_listing_snapshot(conn, listing_id=listing_id, run_id=run_id, title="冲突候选")
        add_detail_snapshot(
            conn,
            listing_id,
            run_id,
            "https://www.goofish.com/item?id=conflict",
            "详情",
            tmp_path / "conflict.png",
            tmp_path / "conflict.html",
            detail_text,
            tmp_path / "conflict.links.txt",
            tmp_path / "conflict.images.txt",
            0,
            0,
            False,
            attributes_json=json.dumps(
                {"成色": "几乎全新", "拆修": "无任何拆修"},
                ensure_ascii=False,
            ),
            attributes_source="xianyu_api_item_labels",
        )

    candidate = query_candidates(
        config,
        CandidateQueryOptions(run_ids=[run_id], listing_ids=[listing_id]),
    )["candidates"][0]

    assert candidate["mechanical_facts"]["condition"] == "几乎全新"
    assert "evidence_conflicts" not in candidate


def test_query_candidates_applies_generic_filters_before_limit(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-generic-filters.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        first_run = create_search_run(conn, goal="iPhone 15 Pro", city="上海")
        second_run = create_search_run(conn, goal="苹果15pro 国行", city="上海")
        shared_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=filter-shared",
        )
        white_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=filter-white",
        )
        merchant_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=filter-merchant",
        )
        outside_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=filter-outside",
        )
        add_listing_snapshot(
            conn,
            listing_id=shared_id,
            run_id=first_run,
            title="iPhone 15 Pro 白色 国行 128GB",
            description="上海自提，正常使用痕迹",
            price_text="¥3600",
            location="上海",
        )
        add_listing_snapshot(
            conn,
            listing_id=shared_id,
            run_id=second_run,
            title="iPhone 15 Pro 白色 国行 128GB",
            description="上海自提，正常使用痕迹",
            price_text="¥3500",
            location="上海市",
        )
        add_listing_snapshot(
            conn,
            listing_id=white_id,
            run_id=second_run,
            title="苹果15 Pro 白色钛金属",
            description="大陆国行，可同城自提",
            price_text="¥3800",
            location="上海",
        )
        add_listing_snapshot(
            conn,
            listing_id=merchant_id,
            run_id=second_run,
            title="苹果15 Pro 白色 国行",
            description="商家质保一年，支持分期置换",
            price_text="¥3400",
            location="上海",
        )
        add_listing_snapshot(
            conn,
            listing_id=outside_id,
            run_id=second_run,
            title="苹果15 Pro 白色 国行",
            description="个人闲置",
            price_text="¥3300",
            location="杭州",
        )

    result = query_candidates(
        config,
        CandidateQueryOptions(
            run_ids=[first_run, second_run],
            locations=["上海"],
            text_includes=["白色", "国行"],
            text_excludes=["商家", "分期"],
            text_match_mode="all",
            text_scopes=["title", "search_description"],
            sort_by="price_asc",
            limit=1,
        ),
    )

    assert result["deduplicated_count"] == 4
    assert result["eligible_count"] == 2
    assert result["returned_count"] == 1
    assert result["limit"] == 1
    assert result["truncated"] is True
    assert result["filters_applied"] == {
        "locations": ["上海"],
        "text_includes": ["白色", "国行"],
        "text_excludes": ["商家", "分期"],
        "text_match_mode": "all",
        "text_scopes": ["title", "search_description"],
    }
    candidate = result["candidates"][0]
    assert candidate["listing_id"] == shared_id
    assert candidate["filter_evidence"]["location_matches"] == [
        {"term": "上海", "value": "上海市"}
    ]
    assert candidate["filter_evidence"]["text_matches"]["白色"] == ["title"]
    assert candidate["filter_evidence"]["text_matches"]["国行"] == ["title"]


def test_query_candidates_text_match_any_can_use_detail_and_attributes(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "test-query-text-scopes.sqlite")
    initialize(config.database_path)
    detail_text = tmp_path / "scope-detail.txt"
    detail_text.write_text("卖家描述写明支持自提", encoding="utf-8")
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="通用筛选", city="上海")
        listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=scope-detail",
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="候选",
            description="搜索卡片没有目标词",
            location="上海",
        )
        add_detail_snapshot(
            conn,
            listing_id,
            run_id,
            "https://www.goofish.com/item?id=scope-detail",
            "详情",
            tmp_path / "scope.png",
            tmp_path / "scope.html",
            detail_text,
            tmp_path / "scope.links.txt",
            tmp_path / "scope.images.txt",
            0,
            0,
            False,
            attributes_json=json.dumps({"颜色": "白色"}, ensure_ascii=False),
            attributes_source="xianyu_api_item_labels",
        )

    result = query_candidates(
        config,
        CandidateQueryOptions(
            run_ids=[run_id],
            text_includes=["白色", "自提"],
            text_match_mode="any",
            text_scopes=["detail_description", "attributes"],
        ),
    )

    assert result["eligible_count"] == 1
    matches = result["candidates"][0]["filter_evidence"]["text_matches"]
    assert matches == {
        "白色": ["attributes"],
        "自提": ["detail_description"],
    }


def test_query_candidates_cli_accepts_generic_filter_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "query-candidates",
            "--run-id",
            "1",
            "--location",
            "上海",
            "--text-contains",
            "白色",
            "--text-contains",
            "国行",
            "--text-exclude",
            "商家",
            "--text-match",
            "all",
            "--text-scope",
            "title",
            "--text-scope",
            "search_description",
        ]
    )

    assert args.location == ["上海"]
    assert args.text_contains == ["白色", "国行"]
    assert args.text_exclude == ["商家"]
    assert args.text_match == "all"
    assert args.text_scope == ["title", "search_description"]


def test_query_candidates_cli_rejects_detail_text_output() -> None:
    parser = build_parser()

    try:
        parser.parse_args(
            ["query-candidates", "--run-id", "1", "--detail-text", "400"]
        )
    except SystemExit:
        return
    raise AssertionError("Expected argparse to reject --detail-text")
