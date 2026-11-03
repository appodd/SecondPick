from __future__ import annotations

from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_detail_snapshot,
    add_listing_snapshot,
    attach_run_to_task,
    connect,
    create_query,
    create_research_task,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.detail_candidates import DetailCandidateOptions, build_detail_candidates


def _add_listing(
    conn,
    run_id: int,
    item_id: str,
    *,
    title: str,
    description: str,
    price_text: str | None,
    location: str | None,
    condition: str | None = None,
) -> int:
    listing_id = upsert_listing(
        conn,
        platform="xianyu",
        url=f"https://www.goofish.com/item?id={item_id}",
    )
    add_listing_snapshot(
        conn,
        listing_id=listing_id,
        run_id=run_id,
        title=title,
        description=description,
        price_text=price_text,
        location=location,
        seller_name=f"卖家-{item_id}",
        search_condition=condition,
    )
    return listing_id


def _build_fixture(tmp_path: Path) -> tuple[AppConfig, int, dict[str, int]]:
    config = AppConfig(database_path=tmp_path / "shopping.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task_id = create_research_task(
            conn,
            title="R9000P",
            goal="找 R9000P 游戏本",
            city="上海",
        )
        run_1 = create_search_run(conn, goal="R9000P", city="上海")
        run_2 = create_search_run(conn, goal="R9000P 4060", city="上海")
        run_3 = create_search_run(conn, goal="R9000P 4060 上海", city="上海")
        create_query(conn, run_id=run_1, platform="xianyu", query_text="R9000P")
        create_query(conn, run_id=run_2, platform="xianyu", query_text="R9000P 4060")
        create_query(conn, run_id=run_3, platform="xianyu", query_text="R9000P 4060 上海")
        attach_run_to_task(conn, task_id=task_id, run_id=run_1)
        attach_run_to_task(conn, task_id=task_id, run_id=run_2)
        attach_run_to_task(conn, task_id=task_id, run_id=run_3)
        ids = {
            "low": _add_listing(
                conn,
                run_1,
                "low",
                title="R9000P 2022",
                description="R7 3060 16G+512G",
                price_text="¥3999",
                location="上海",
                condition="轻微使用痕迹",
            ),
            "mid": _add_listing(
                conn,
                run_1,
                "mid",
                title="R9000P 2023",
                description="R9-7945HX RTX 4060 16G+1T 自用无拆修",
                price_text="¥5299",
                location="杭州",
                condition="几乎全新",
            ),
            "high": _add_listing(
                conn,
                run_2,
                "high",
                title="R9000P 2024",
                description="R9 4060 32G+1T",
                price_text="¥6999",
                location="北京",
            ),
            "unknown": _add_listing(
                conn,
                run_2,
                "unknown",
                title="R9000P 面议",
                description="R9000P 面议",
                price_text=None,
                location=None,
            ),
            "detailed": _add_listing(
                conn,
                run_2,
                "detailed",
                title="R9000P 已抓详情",
                description="已有详情",
                price_text="¥5599",
                location="上海",
            ),
        }
        evidence_dir = tmp_path / "detail"
        evidence_dir.mkdir()
        paths = [evidence_dir / name for name in ("shot.png", "page.html", "page.txt", "links.txt", "images.txt")]
        for path in paths:
            path.write_text("evidence", encoding="utf-8")
        add_detail_snapshot(
            conn,
            listing_id=ids["detailed"],
            run_id=run_2,
            url="https://www.goofish.com/item?id=detailed",
            title="详情",
            screenshot_path=paths[0],
            html_path=paths[1],
            text_path=paths[2],
            links_path=paths[3],
            images_path=paths[4],
            link_count=0,
            image_count=0,
            access_blocked=False,
        )
        filler_paths = [
            evidence_dir / name
            for name in ("filler.png", "filler.html", "filler.txt", "filler.links.txt", "filler.images.txt")
        ]
        for index, (run_id, count) in enumerate(((run_1, 298), (run_2, 17), (run_3, 8))):
            for offset in range(count):
                filler_id = _add_listing(
                    conn,
                    run_id,
                    f"filler-{index}-{offset}",
                    title=f"已完成详情背景候选 {index}-{offset}",
                    description="用于构造任务覆盖状态",
                    price_text="¥5000",
                    location="上海",
                )
                add_detail_snapshot(
                    conn,
                    listing_id=filler_id,
                    run_id=run_id,
                    url=f"https://www.goofish.com/item?id=filler-{index}-{offset}",
                    title="背景详情",
                    screenshot_path=filler_paths[0],
                    html_path=filler_paths[1],
                    text_path=filler_paths[2],
                    links_path=filler_paths[3],
                    images_path=filler_paths[4],
                    link_count=0,
                    image_count=0,
                    access_blocked=False,
                )
    return config, task_id, ids


def test_detail_candidates_return_complete_search_card_and_counts(tmp_path: Path) -> None:
    config, task_id, ids = _build_fixture(tmp_path)

    result = build_detail_candidates(
        config,
        task_id,
        DetailCandidateOptions(limit=3),
    )

    assert result["task_id"] == task_id
    assert result["coverage_status"] == "sufficient"
    assert result["suggested_action"] == "stop_expansion"
    assert result["ready_for_detail_selection"] is True
    assert result["eligible_count"] == 4
    assert result["returned_count"] == 3
    assert result["market_context"]["priced_count"] == 3
    assert ids["detailed"] not in {item["listing_id"] for item in result["candidates"]}
    candidate = next(item for item in result["candidates"] if item["listing_id"] == ids["mid"])
    assert candidate["search_card"] == {
        "title": "R9000P 2023",
        "description": "R9-7945HX RTX 4060 16G+1T 自用无拆修",
        "price_text": "¥5299",
        "price_value": 5299,
        "location": "杭州",
        "seller_name": "卖家-mid",
        "condition": "几乎全新",
        "collected_at": candidate["search_card"]["collected_at"],
    }
    assert candidate["provenance"]["source_run_ids"] == [1]
    assert candidate["provenance"]["source_queries"] == ["R9000P"]
    assert candidate["collection_state"]["has_detail"] is False


def test_detail_candidates_keep_missing_fields_and_are_deterministic(tmp_path: Path) -> None:
    config, task_id, ids = _build_fixture(tmp_path)

    first = build_detail_candidates(config, task_id, DetailCandidateOptions(limit=20))
    second = build_detail_candidates(config, task_id, DetailCandidateOptions(limit=20))

    assert first == second
    unknown = next(item for item in first["candidates"] if item["listing_id"] == ids["unknown"])
    assert unknown["search_card"]["price_value"] is None
    assert unknown["search_card"]["location"] is None
    assert unknown["card_metadata"]["price_band"] == "unknown"
    serialized = str(first).lower()
    for forbidden in ("tool_priority_score", "personal", "professional", "purchase", "risk_score"):
        assert forbidden not in serialized


def test_detail_candidates_reject_missing_task(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "shopping.sqlite")

    try:
        build_detail_candidates(config, task_id=999)
    except ValueError as exc:
        assert str(exc) == "Research task not found: 999"
    else:
        raise AssertionError("Expected missing task error")


def test_detail_candidates_blocks_normal_selection_while_collecting(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "collecting.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task_id = create_research_task(
            conn,
            title="iPhone 15 Pro",
            goal="找 iPhone 15 Pro",
            city="上海",
        )
        run_id = create_search_run(conn, goal="iPhone 15 Pro", city="上海")
        create_query(conn, run_id=run_id, platform="xianyu", query_text="iPhone 15 Pro")
        attach_run_to_task(conn, task_id=task_id, run_id=run_id)
        _add_listing(
            conn,
            run_id,
            "collecting",
            title="iPhone 15 Pro",
            description="搜索覆盖尚不足",
            price_text="¥3500",
            location="上海",
        )

    result = build_detail_candidates(config, task_id, DetailCandidateOptions(limit=20))

    assert result == {
        "task_id": task_id,
        "coverage_status": "collecting",
        "suggested_action": "continue_search",
        "ready_for_detail_selection": False,
        "eligible_count": 0,
        "returned_count": 0,
        "market_context": {
            "unique_candidates": 0,
            "priced_count": 0,
            "price_min": None,
            "price_p25": None,
            "price_median": None,
            "price_p75": None,
            "price_max": None,
        },
        "candidates": [],
    }
