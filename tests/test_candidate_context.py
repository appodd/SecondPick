from __future__ import annotations

import base64
from pathlib import Path

import json
import pytest

from shopping_agent.candidate_context import build_candidate_evidence, build_candidate_index
from shopping_agent.cli import build_parser
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_listing_snapshot,
    add_detail_snapshot,
    add_media_asset,
    add_ocr_result,
    add_seller_items,
    attach_run_to_task,
    connect,
    create_research_task,
    create_search_run,
    initialize,
    upsert_listing,
)


def _seed_index_scope(config: AppConfig) -> dict[str, int]:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        first_run = create_search_run(conn, goal="R9000P 4060", city="上海")
        second_run = create_search_run(conn, goal="R9000P 2023 4060", city="上海")
        shared_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=shared",
        )
        redundant_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=redundant",
        )
        missing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=missing",
        )
        add_listing_snapshot(
            conn,
            listing_id=shared_id,
            run_id=first_run,
            title="old complete title",
            description="old distinct description",
            price_text="¥6600",
            location="上海",
            seller_name="卖家甲",
        )
        add_listing_snapshot(
            conn,
            listing_id=redundant_id,
            run_id=first_run,
            title="same search card text",
            description="same search card text",
            price_text="¥6500",
            location="上海",
            seller_name="卖家乙",
            search_condition="成色新",
        )
        add_listing_snapshot(
            conn,
            listing_id=shared_id,
            run_id=second_run,
            title="new complete title",
            description="new distinct description",
            price_text="¥6400",
            location="上海",
            seller_name="卖家甲",
        )
        add_listing_snapshot(
            conn,
            listing_id=missing_id,
            run_id=second_run,
            title="title without persisted description",
            description=None,
            price_text="¥6300",
            location="杭州",
            seller_name="卖家丙",
        )
        task_id = create_research_task(
            conn,
            title="R9000P 4060",
            goal="找一台上海自提的 R9000P 4060",
            city="上海",
        )
        attach_run_to_task(conn, task_id=task_id, run_id=first_run)
        attach_run_to_task(conn, task_id=task_id, run_id=second_run)
        # Windows may return the same clock tick for successive inserts. This
        # fixture tests distinct observations, not an equal-time price conflict.
        conn.execute("UPDATE listing_snapshots SET collected_at='2026-10-23T00:00:00+00:00' WHERE run_id=?", (first_run,))
        conn.execute("UPDATE listing_snapshots SET collected_at='2026-10-24T00:00:00+00:00' WHERE run_id=?", (second_run,))
        conn.commit()
    return {
        "first_run": first_run,
        "second_run": second_run,
        "shared_id": shared_id,
        "redundant_id": redundant_id,
        "missing_id": missing_id,
        "task_id": task_id,
    }


def test_candidate_index_deduplicates_runs_and_uses_latest_snapshot(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-index.sqlite")
    seeded = _seed_index_scope(config)

    result = build_candidate_index(
        config,
        run_ids=[seeded["first_run"], seeded["second_run"]],
    )

    assert result["scope"] == {
        "task_id": None,
        "run_ids": [seeded["first_run"], seeded["second_run"]],
    }
    assert result["deduplicated_count"] == 3
    assert [item["listing_id"] for item in result["candidates"]].count(seeded["shared_id"]) == 1
    shared = next(
        item for item in result["candidates"] if item["listing_id"] == seeded["shared_id"]
    )
    assert shared["source_run_ids"] == [seeded["first_run"], seeded["second_run"]]
    assert shared["title"] == "new complete title"
    assert shared["search_description"] == "new distinct description"
    assert shared["search_description_status"] == "distinct"
    assert shared["price_value"] == 6400


def test_candidate_index_explains_compacted_search_descriptions(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-description.sqlite")
    seeded = _seed_index_scope(config)

    result = build_candidate_index(config, task_id=seeded["task_id"])
    candidates = {item["listing_id"]: item for item in result["candidates"]}

    assert result["scope"] == {
        "task_id": seeded["task_id"],
        "run_ids": [seeded["first_run"], seeded["second_run"]],
    }
    assert candidates[seeded["redundant_id"]]["search_description"] is None
    assert (
        candidates[seeded["redundant_id"]]["search_description_status"]
        == "redundant_with_title"
    )
    assert candidates[seeded["missing_id"]]["search_description"] is None
    assert candidates[seeded["missing_id"]]["search_description_status"] == "missing"
    assert "not data loss" not in result["field_semantics"]["search_description"]
    assert "persisted" in result["field_semantics"]["search_description_status"]["redundant_with_title"]


def test_candidate_index_contains_only_compact_search_card_fields(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-fields.sqlite")
    seeded = _seed_index_scope(config)

    candidate = build_candidate_index(config, task_id=seeded["task_id"])["candidates"][0]

    assert set(candidate) == {
        "listing_id",
        "source_run_ids",
        "url",
        "title",
        "search_description",
        "search_description_status",
        "price_text",
        "price_value",
        "location",
        "seller_name",
        "search_condition",
        "has_detail",
        "detail_status",
        "current_quote", "price_history", "market_attributes", "market_provenance", "market_page_fields",
    }
    for forbidden in (
        "evidence",
        "seller_fields",
        "shortlist",
        "near_duplicate_groups",
        "attributes",
    ):
        assert forbidden not in candidate


@pytest.mark.parametrize(
    ("task_id", "run_ids", "message"),
    [
        (None, None, "exactly one candidate scope"),
        (1, [1], "exactly one candidate scope"),
        (None, [], "exactly one candidate scope"),
    ],
)
def test_candidate_index_rejects_missing_or_mixed_scope(
    tmp_path: Path,
    task_id: int | None,
    run_ids: list[int] | None,
    message: str,
) -> None:
    config = AppConfig(database_path=tmp_path / "invalid-scope.sqlite")

    with pytest.raises(ValueError, match=message):
        build_candidate_index(config, task_id=task_id, run_ids=run_ids)


def test_candidate_index_rejects_unknown_task_and_run(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "unknown-scope.sqlite")

    with pytest.raises(ValueError, match="Research task 999 does not exist"):
        build_candidate_index(config, task_id=999)
    with pytest.raises(ValueError, match="Search run 999 does not exist"):
        build_candidate_index(config, run_ids=[999])


def test_candidate_index_rejects_task_without_runs(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "empty-task.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task_id = create_research_task(
            conn,
            title="empty",
            goal="empty task",
            city="上海",
        )

    with pytest.raises(ValueError, match=f"Research task {task_id} has no attached runs"):
        build_candidate_index(config, task_id=task_id)


def _seed_large_index_scope(
    tmp_path: Path,
    *,
    count: int,
) -> tuple[AppConfig, int, list[int]]:
    config = AppConfig(database_path=tmp_path / "candidate-index-pages.sqlite")
    initialize(config.database_path)
    expected_ids = []
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="paged candidates", city="上海")
        for index in range(count):
            listing_id = upsert_listing(
                conn,
                platform="xianyu",
                url=f"https://www.goofish.com/item?id=paged-{index}",
            )
            add_listing_snapshot(
                conn,
                listing_id=listing_id,
                run_id=run_id,
                title=f"candidate {index:03d}",
                description=f"distinct description {index:03d}",
                price_text=f"¥{5000 + index}",
                location="上海",
            )
            expected_ids.append(listing_id)
        conn.commit()
    return config, run_id, expected_ids


def test_candidate_index_pages_cover_scope_once_without_overlap(tmp_path: Path) -> None:
    config, run_id, expected_ids = _seed_large_index_scope(tmp_path, count=95)
    cursor = None
    observed_ids = []
    page_sizes = []
    scope_revisions = set()

    while True:
        result = build_candidate_index(
            config,
            run_ids=[run_id],
            limit=40,
            cursor=cursor,
        )
        page_sizes.append(result["returned_count"])
        observed_ids.extend(item["listing_id"] for item in result["candidates"])
        scope_revisions.add(result["scope_revision"])
        assert result["deduplicated_count"] == 95
        assert result["returned_count"] == len(result["candidates"])
        cursor = result["page"]["next_cursor"]
        if cursor is None:
            break

    assert page_sizes == [40, 40, 15]
    assert observed_ids == expected_ids
    assert len(observed_ids) == len(set(observed_ids)) == 95
    assert len(scope_revisions) == 1


@pytest.mark.parametrize("count", [95, 600])
def test_candidate_index_returns_complete_scope_by_default(
    tmp_path: Path,
    count: int,
) -> None:
    config, run_id, expected_ids = _seed_large_index_scope(tmp_path, count=count)

    result = build_candidate_index(config, run_ids=[run_id])

    observed_ids = [item["listing_id"] for item in result["candidates"]]
    assert result["deduplicated_count"] == count
    assert result["returned_count"] == count
    assert observed_ids == expected_ids
    assert len(observed_ids) == len(set(observed_ids))
    assert result["page"] == {
        "offset": 0,
        "limit": None,
        "has_more": False,
        "next_cursor": None,
    }


def test_candidate_index_rejects_cursor_without_explicit_limit(tmp_path: Path) -> None:
    config, run_id, _ = _seed_large_index_scope(tmp_path, count=3)
    first = build_candidate_index(config, run_ids=[run_id], limit=2)

    with pytest.raises(ValueError, match="cursor requires an explicit limit"):
        build_candidate_index(
            config,
            run_ids=[run_id],
            cursor=first["page"]["next_cursor"],
        )


def test_candidate_index_rejects_invalid_limits_and_cursors(tmp_path: Path) -> None:
    config, run_id, _ = _seed_large_index_scope(tmp_path, count=3)

    with pytest.raises(ValueError, match="limit"):
        build_candidate_index(config, run_ids=[run_id], limit=0)
    with pytest.raises(ValueError, match="limit"):
        build_candidate_index(config, run_ids=[run_id], limit=101)
    with pytest.raises(ValueError, match="candidate cursor"):
        build_candidate_index(config, run_ids=[run_id], cursor="not-a-cursor")

    first = build_candidate_index(config, run_ids=[run_id], limit=2)
    invalid_offset = base64.urlsafe_b64encode(
        json.dumps(
            {
                "v": 1,
                "scope_revision": first["scope_revision"],
                "offset": 99,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(ValueError, match="candidate cursor"):
        build_candidate_index(
            config,
            run_ids=[run_id],
            limit=2,
            cursor=invalid_offset,
        )


def test_candidate_index_rejects_cursor_after_scope_changes(tmp_path: Path) -> None:
    config, run_id, _ = _seed_large_index_scope(tmp_path, count=3)
    first = build_candidate_index(config, run_ids=[run_id], limit=2)

    with connect(config.database_path) as conn:
        listing_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=scope-change",
        )
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="new candidate changes scope",
            description="new candidate description",
            price_text="¥6000",
            location="上海",
        )
        conn.commit()

    with pytest.raises(ValueError, match="candidate scope changed"):
        build_candidate_index(
            config,
            run_ids=[run_id],
            limit=2,
            cursor=first["page"]["next_cursor"],
        )


def _seed_evidence_scope(config: AppConfig, tmp_path: Path) -> dict[str, int]:
    initialize(config.database_path)
    scoped_detail_text = tmp_path / "scoped-detail.txt"
    unrelated_detail_text = tmp_path / "unrelated-detail.txt"
    scoped_detail_text.write_text(
        "\n".join(
            [
                "卖家甲",
                "上海",
                "来闲鱼7年",
                "卖出47件宝贝",
                "好评率100%",
                "¥",
                "6188",
                "范围内完整详情描述",
                "成",
                "色",
                "：",
                "明显磕碰划痕",
                "拆",
                "修",
                "：",
                "更换过屏幕",
            ]
        ),
        encoding="utf-8",
    )
    unrelated_detail_text.write_text("无关 run 的更新详情", encoding="utf-8")

    with connect(config.database_path) as conn:
        scoped_run = create_search_run(conn, goal="R9000P 4060", city="上海")
        unrelated_run = create_search_run(conn, goal="unrelated", city="北京")
        captured_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=captured",
        )
        search_only_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=search-only",
        )
        outside_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=outside",
        )
        add_listing_snapshot(
            conn,
            listing_id=captured_id,
            run_id=scoped_run,
            title="R9000P 2023 4060",
            description="搜索卡片描述",
            price_text="¥6188",
            location="上海",
            seller_name="卖家甲",
            seller_credit_level="信用极好",
            seller_registered_days=2555,
            seller_sold_count=47,
            seller_good_rate="100%",
            seller_realname_verified=True,
            seller_reply_rate_24h="90%",
        )
        add_listing_snapshot(
            conn,
            listing_id=search_only_id,
            run_id=scoped_run,
            title="R9000P search only",
            description="R9000P search only",
            price_text="¥6500",
            location="上海",
            seller_name="卖家乙",
        )
        add_listing_snapshot(
            conn,
            listing_id=outside_id,
            run_id=unrelated_run,
            title="outside candidate",
            description="outside candidate",
            price_text="¥6000",
            location="北京",
        )
        add_detail_snapshot(
            conn,
            captured_id,
            scoped_run,
            "https://www.goofish.com/item?id=captured",
            "范围内详情",
            tmp_path / "scoped.png",
            tmp_path / "scoped.html",
            scoped_detail_text,
            tmp_path / "scoped.links.txt",
            tmp_path / "scoped.images.txt",
            0,
            2,
            False,
            attributes_json=json.dumps(
                {"成色": "几乎全新", "拆修": "无任何拆修", "型号": "R9000P"},
                ensure_ascii=False,
            ),
            attributes_source="xianyu_api_item_labels",
        )
        add_detail_snapshot(
            conn,
            captured_id,
            unrelated_run,
            "https://www.goofish.com/item?id=captured",
            "无关详情",
            tmp_path / "unrelated.png",
            tmp_path / "unrelated.html",
            unrelated_detail_text,
            tmp_path / "unrelated.links.txt",
            tmp_path / "unrelated.images.txt",
            0,
            0,
            False,
            attributes_json=json.dumps({"成色": "明显瑕疵"}, ensure_ascii=False),
            attributes_source="xianyu_api_item_labels",
        )
        add_seller_items(
            conn,
            seller_listing_id=captured_id,
            seller_name="卖家甲",
            source_run_id=scoped_run,
            items=[
                {"itemId": "other-1", "title": "其他游戏本", "link": "item://other-1"},
                {"itemId": "other-1", "title": "重复其他游戏本", "link": "item://other-1"},
            ],
        )
        media_id = add_media_asset(
            conn,
            listing_id=captured_id,
            media_type="product_image_url",
            source_url="https://img.example/captured.jpg",
            local_path="data/media/captured.jpg",
        )
        add_ocr_result(conn, media_id, "OCR text must not be returned")
        task_id = create_research_task(
            conn,
            title="R9000P",
            goal="上海 R9000P",
            city="上海",
        )
        attach_run_to_task(conn, task_id=task_id, run_id=scoped_run)
        conn.commit()
    return {
        "scoped_run": scoped_run,
        "unrelated_run": unrelated_run,
        "captured_id": captured_id,
        "search_only_id": search_only_id,
        "outside_id": outside_id,
        "task_id": task_id,
    }


def test_candidate_evidence_returns_scoped_detail_and_search_only_status(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)

    result = build_candidate_evidence(
        config,
        task_id=seeded["task_id"],
        listing_ids=[seeded["captured_id"], seeded["search_only_id"]],
    )

    assert result["requested_listing_ids"] == [
        seeded["captured_id"],
        seeded["search_only_id"],
    ]
    assert result["returned_count"] == 2
    captured, search_only = result["candidates"]
    assert captured["detail_status"] == "captured"
    assert captured["detail"]["description"] == "范围内完整详情描述"
    assert captured["detail"]["attributes_source"] == "xianyu_api_item_labels"
    assert captured["detail"]["attributes"]["成色"] == "几乎全新"
    assert captured["detail"]["attributes"]["成色"] != "明显瑕疵"
    assert captured["raw_text_excerpt"] is None
    assert captured["seller_fields"]["source"] == "platform_seller_field"
    assert captured["seller_fields"]["independently_verified"] is False
    assert captured["seller_other_items"] == [
        {"item_id_ext": "other-1", "title": "其他游戏本", "url": "item://other-1"}
    ]
    assert captured["collection_state"] == {
        "detail_snapshot_count": 1,
        "valid_detail_snapshot_count": 1,
        "blocked_detail_snapshot_count": 0,
        "listing_lifetime_product_image_count": 1,
        "listing_lifetime_downloaded_product_image_count": 1,
        "listing_lifetime_ocr_result_count": 1,
    }
    assert "ocr_text" not in captured
    assert search_only["detail_status"] == "not_captured"
    assert search_only["detail"] is None


def test_candidate_evidence_reports_blocked_when_scope_has_only_blocked_detail(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-blocked.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)
    blocked_text = tmp_path / "blocked-detail.txt"
    blocked_text.write_text("访问受限", encoding="utf-8")
    with connect(config.database_path) as conn:
        add_detail_snapshot(
            conn,
            seeded["search_only_id"],
            seeded["scoped_run"],
            "https://www.goofish.com/item?id=search-only",
            "访问受限",
            tmp_path / "blocked.png",
            tmp_path / "blocked.html",
            blocked_text,
            tmp_path / "blocked.links.txt",
            tmp_path / "blocked.images.txt",
            0,
            0,
            True,
        )
        conn.commit()

    index_candidate = build_candidate_index(
        config,
        run_ids=[seeded["scoped_run"]],
    )["candidates"][1]
    evidence_candidate = build_candidate_evidence(
        config,
        run_ids=[seeded["scoped_run"]],
        listing_ids=[seeded["search_only_id"]],
        raw_text_chars=20,
    )["candidates"][0]

    assert index_candidate["has_detail"] is False
    assert index_candidate["detail_status"] == "blocked"
    assert evidence_candidate["detail_status"] == "blocked"
    assert evidence_candidate["detail"] is None
    assert evidence_candidate["collection_state"]["detail_snapshot_count"] == 1
    assert evidence_candidate["collection_state"]["valid_detail_snapshot_count"] == 0
    assert evidence_candidate["collection_state"]["blocked_detail_snapshot_count"] == 1
    assert evidence_candidate["raw_text_excerpt"] is None


def test_candidate_evidence_prefers_latest_valid_detail_over_newer_blocked_snapshot(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-valid-before-block.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)
    blocked_text = tmp_path / "newer-blocked-detail.txt"
    blocked_text.write_text("较新的访问阻断页面", encoding="utf-8")
    with connect(config.database_path) as conn:
        blocked_snapshot_id = add_detail_snapshot(
            conn,
            seeded["captured_id"],
            seeded["scoped_run"],
            "https://www.goofish.com/item?id=captured",
            "访问受限",
            tmp_path / "newer-blocked.png",
            tmp_path / "newer-blocked.html",
            blocked_text,
            tmp_path / "newer-blocked.links.txt",
            tmp_path / "newer-blocked.images.txt",
            0,
            0,
            True,
        )
        conn.execute(
            "UPDATE detail_snapshots SET created_at = ? WHERE id = ?",
            ("2099-01-01T00:00:00+00:00", blocked_snapshot_id),
        )
        conn.commit()

    candidate = build_candidate_evidence(
        config,
        run_ids=[seeded["scoped_run"]],
        listing_ids=[seeded["captured_id"]],
        raw_text_chars=200,
    )["candidates"][0]

    assert candidate["detail_status"] == "captured"
    assert candidate["detail"]["description"] == "范围内完整详情描述"
    assert candidate["raw_text_excerpt"].startswith("卖家甲")
    assert "访问阻断" not in candidate["raw_text_excerpt"]
    assert candidate["collection_state"]["detail_snapshot_count"] == 2
    assert candidate["collection_state"]["valid_detail_snapshot_count"] == 1
    assert candidate["collection_state"]["blocked_detail_snapshot_count"] == 1


def test_candidate_evidence_marks_mixed_seller_field_sources(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-mixed-seller.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)
    with connect(config.database_path) as conn:
        conn.execute(
            """
            UPDATE listing_snapshots
            SET seller_registered_days = NULL, seller_sold_count = NULL
            WHERE listing_id = ? AND run_id = ?
            """,
            (seeded["captured_id"], seeded["scoped_run"]),
        )
        conn.commit()

    seller_fields = build_candidate_evidence(
        config,
        run_ids=[seeded["scoped_run"]],
        listing_ids=[seeded["captured_id"]],
    )["candidates"][0]["seller_fields"]

    assert seller_fields["data_source"] == "mixed"
    assert seller_fields["seller_credit_level"] == "信用极好"
    assert seller_fields["seller_registered_days"] == 2555
    assert seller_fields["seller_sold_count"] == 47
    assert seller_fields["field_sources"] == {
        "seller_credit_level": "db",
        "seller_registered_days": "detail_dom_fallback",
        "seller_sold_count": "detail_dom_fallback",
        "seller_good_rate": "db",
        "seller_realname_verified": "db",
        "seller_reply_rate_24h": "db",
    }


def test_candidate_evidence_labels_dom_attribute_fallback_source(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-dom-fallback.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)
    with connect(config.database_path) as conn:
        conn.execute(
            """
            UPDATE detail_snapshots
            SET attributes_json = '{}'
            WHERE listing_id = ? AND run_id = ?
            """,
            (seeded["captured_id"], seeded["scoped_run"]),
        )
        conn.commit()

    candidate = build_candidate_evidence(
        config,
        run_ids=[seeded["scoped_run"]],
        listing_ids=[seeded["captured_id"]],
    )["candidates"][0]

    assert candidate["detail"]["attributes"]["成色"] == "明显磕碰划痕"
    assert candidate["detail"]["attributes_source"] == "detail_dom_fallback"
    assert candidate["detail"]["evidence_source"] == "detail_dom_fallback"
    assert candidate["evidence_conflicts"] == []


def test_candidate_evidence_does_not_invent_source_for_missing_attributes(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-no-attributes.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)
    detail_text = tmp_path / "description-only-detail.txt"
    detail_text.write_text("卖家甲\n上海\n¥\n6188\n只有详情描述", encoding="utf-8")
    with connect(config.database_path) as conn:
        conn.execute(
            """
            UPDATE detail_snapshots
            SET attributes_json = '{}', attributes_source = NULL, text_path = ?
            WHERE listing_id = ? AND run_id = ?
            """,
            (str(detail_text), seeded["captured_id"], seeded["scoped_run"]),
        )
        conn.commit()

    detail = build_candidate_evidence(
        config,
        run_ids=[seeded["scoped_run"]],
        listing_ids=[seeded["captured_id"]],
    )["candidates"][0]["detail"]

    assert detail["description"] == "只有详情描述"
    assert detail["attributes"] == {}
    assert detail["attributes_source"] is None
    assert detail["evidence_source"] is None


def test_candidate_evidence_preserves_requested_order_and_deduplicates_ids(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-order.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)

    result = build_candidate_evidence(
        config,
        run_ids=[seeded["scoped_run"]],
        listing_ids=[
            seeded["search_only_id"],
            seeded["captured_id"],
            seeded["search_only_id"],
        ],
    )

    assert result["requested_listing_ids"] == [seeded["search_only_id"], seeded["captured_id"]]
    assert [item["listing_id"] for item in result["candidates"]] == [
        seeded["search_only_id"],
        seeded["captured_id"],
    ]


def test_candidate_evidence_rejects_any_out_of_scope_id_without_partial_result(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-scope.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)

    with pytest.raises(ValueError, match=f"outside the candidate scope: {seeded['outside_id']}"):
        build_candidate_evidence(
            config,
            task_id=seeded["task_id"],
            listing_ids=[seeded["captured_id"], seeded["outside_id"]],
        )


def test_candidate_evidence_raw_text_is_opt_in_and_exactly_bounded(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-raw.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)

    candidate = build_candidate_evidence(
        config,
        run_ids=[seeded["scoped_run"]],
        listing_ids=[seeded["captured_id"]],
        raw_text_chars=12,
    )["candidates"][0]

    assert candidate["raw_text_excerpt"] is not None
    assert len(candidate["raw_text_excerpt"]) == 12


def test_candidate_evidence_rejects_empty_ids_and_negative_raw_text(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "candidate-evidence-invalid.sqlite")
    seeded = _seed_evidence_scope(config, tmp_path)

    with pytest.raises(ValueError, match="At least one listing ID is required"):
        build_candidate_evidence(config, task_id=seeded["task_id"], listing_ids=[])
    with pytest.raises(ValueError, match="raw_text_chars must be non-negative"):
        build_candidate_evidence(
            config,
            task_id=seeded["task_id"],
            listing_ids=[seeded["captured_id"]],
            raw_text_chars=-1,
        )


def test_candidate_context_cli_parses_task_and_repeated_run_scopes() -> None:
    parser = build_parser()

    task_args = parser.parse_args(["candidate-index", "--task-id", "3", "--pretty"])
    run_args = parser.parse_args(
        [
            "candidate-index",
            "--run-id",
            "61",
            "--run-id",
            "62",
            "--limit",
            "25",
            "--cursor",
            "opaque-cursor",
        ]
    )

    assert task_args.command == "candidate-index"
    assert task_args.task_id == 3
    assert task_args.run_id is None
    assert task_args.limit is None
    assert task_args.cursor is None
    assert task_args.pretty is True
    assert run_args.task_id is None
    assert run_args.run_id == [61, 62]
    assert run_args.limit == 25
    assert run_args.cursor == "opaque-cursor"


def test_candidate_evidence_cli_parses_listing_ids_and_raw_text_limit() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "candidate-evidence",
            "--run-id",
            "61",
            "--listing-id",
            "3259",
            "--listing-id",
            "3268",
            "--raw-text-chars",
            "1000",
            "--pretty",
        ]
    )

    assert args.command == "candidate-evidence"
    assert args.task_id is None
    assert args.run_id == [61]
    assert args.listing_id == [3259, 3268]
    assert args.raw_text_chars == 1000
    assert args.pretty is True
