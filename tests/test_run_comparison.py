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
from shopping_agent.run_comparison import RunComparisonOptions, build_run_comparison


def test_build_run_comparison_surfaces_filter_effectiveness_metrics() -> None:
    config = AppConfig(database_path=Path("data/test-run-comparison.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        broad_run = create_search_run(conn, goal="macbook", city="Shanghai")
        filtered_run = create_search_run(conn, goal="macbook min_price=3000", city="Shanghai")
        _add_page(conn, broad_run, "macbook")
        _add_page(conn, filtered_run, "macbook min_price=3000")

        _add_listing(
            conn,
            broad_run,
            url="https://www.goofish.com/item?id=1",
            title="MacBook Pro 14 M1 Pro 32G",
            price_text="6000",
            location="Shanghai",
            description="MacBook Pro 14 M1 Pro 32G 512G",
        )
        _add_listing(
            conn,
            broad_run,
            url="https://www.goofish.com/item?id=2",
            title="mfi carplay cable",
            price_text="39",
            location="Guangdong",
            description="mfi carplay cable for phone",
        )
        _add_listing(
            conn,
            broad_run,
            url="https://www.goofish.com/item?id=3",
            title="MacBook Pro keyboard film",
            price_text="19",
            location="Shanghai",
            description="MacBook Pro accessory mfi film",
        )

        _add_listing(
            conn,
            filtered_run,
            url="https://www.goofish.com/item?id=4",
            title="MacBook Pro 14 M1 Pro 32G",
            price_text="6200",
            location="Shanghai",
            description="MacBook Pro 14 M1 Pro 32G 512G",
        )
        _add_listing(
            conn,
            filtered_run,
            url="https://www.goofish.com/item?id=5",
            title="MacBook Pro 14 M2 Pro 16G",
            price_text="7600",
            location="Suzhou",
            description="MacBook Pro 14 M2 Pro 16G 512G",
        )

    comparison = build_run_comparison(
        config,
        run_ids=[broad_run, filtered_run],
        options=RunComparisonOptions(goal="MacBook Pro M1", target_city="Shanghai"),
    )

    broad_metrics = comparison["run_metrics"][0]
    filtered_metrics = comparison["run_metrics"][1]

    assert comparison["decision_owner"] == "llm"
    assert comparison["is_final_recommendation"] is False
    assert broad_metrics["unique_candidate_count"] == 3
    assert broad_metrics["noisy_candidate_count"] == 2
    assert broad_metrics["useful_candidate_count"] == 1
    assert filtered_metrics["unique_candidate_count"] == 2
    assert filtered_metrics["noise_ratio"] == 0.0
    assert filtered_metrics["useful_candidate_count"] == 2
    assert filtered_metrics["price_stats"]["median"] == 6900
    assert comparison["relative_to_first_run"][0]["useful_candidate_delta"] == 1
    assert comparison["relative_to_first_run"][0]["noise_ratio_delta"] < 0
    assert comparison["metric_leaders"]["highest_useful_candidate_count_run_id"] == filtered_run
    assert comparison["metric_leaders"]["lowest_noise_ratio_run_id"] == filtered_run


def test_compare_runs_cli_accepts_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "compare-runs",
            "--run-id",
            "10",
            "--run-id",
            "11",
            "--goal",
            "MacBook Pro M1",
            "--target-city",
            "Shanghai",
            "--pretty",
        ]
    )

    assert args.command == "compare-runs"
    assert args.run_id == [10, 11]
    assert args.goal == "MacBook Pro M1"
    assert args.target_city == "Shanghai"
    assert args.pretty is True


def _add_page(conn, run_id: int, query: str) -> None:
    create_query(conn, run_id=run_id, platform="xianyu", query_text=query)
    add_page_snapshot(
        conn,
        run_id=run_id,
        platform="xianyu",
        query_text=query,
        url=f"https://www.goofish.com/search?q={query}",
        title=query,
        screenshot_path=Path("data/screenshots/search.png"),
        html_path=Path("data/screenshots/search.html"),
        text_path=Path("data/screenshots/search.txt"),
        links_path=Path("data/screenshots/search.links.txt"),
        link_count=10,
        access_blocked=False,
    )


def _add_listing(
    conn,
    run_id: int,
    *,
    url: str,
    title: str,
    price_text: str,
    location: str,
    description: str,
) -> int:
    listing_id = upsert_listing(conn, platform="xianyu", url=url)
    add_listing_snapshot(
        conn,
        listing_id=listing_id,
        run_id=run_id,
        title=title,
        price_text=price_text,
        location=location,
        description=description,
    )
    return listing_id
