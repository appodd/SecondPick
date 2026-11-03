from __future__ import annotations

from rich.console import Console
from rich.table import Table

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    connect,
    fetch_detail_snapshots_for_run,
    fetch_latest_listing_snapshots_for_run,
    fetch_listing_snapshots_for_run,
    fetch_page_snapshots_for_run,
    fetch_recent_runs,
    initialize,
)


def print_recent_history(config: AppConfig, console: Console, limit: int = 10) -> None:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        runs = fetch_recent_runs(conn, limit=limit)

    table = Table(title="Recent Search Runs")
    table.add_column("Run")
    table.add_column("Goal")
    table.add_column("City")
    table.add_column("Queries", justify="right")
    table.add_column("Pages", justify="right")
    table.add_column("Listing Snapshots", justify="right")
    table.add_column("Created")

    for run in runs:
        table.add_row(
            str(run["id"]),
            run["goal"],
            run["city"],
            str(run["query_count"]),
            str(run["page_snapshot_count"]),
            str(run["listing_snapshot_count"]),
            run["created_at"],
        )

    console.print(table)


def print_run_detail(config: AppConfig, console: Console, run_id: int) -> None:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        pages = fetch_page_snapshots_for_run(conn, run_id)

    table = Table(title=f"Page Snapshots for Run {run_id}")
    table.add_column("ID")
    table.add_column("Platform")
    table.add_column("Query")
    table.add_column("Blocked")
    table.add_column("Links", justify="right")
    table.add_column("Text")
    table.add_column("Screenshot")

    for page in pages:
        table.add_row(
            str(page["id"]),
            page["platform"],
            page["query_text"],
            "yes" if page["access_blocked"] else "no",
            str(page["link_count"]),
            page["text_path"] or "",
            page["screenshot_path"] or "",
        )

    console.print(table)


def print_run_listings(config: AppConfig, console: Console, run_id: int, limit: int = 20) -> None:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        listings = fetch_latest_listing_snapshots_for_run(conn, run_id)[:limit]

    table = Table(title=f"Listing Snapshots for Run {run_id}")
    table.add_column("#")
    table.add_column("Platform")
    table.add_column("Price")
    table.add_column("Location")
    table.add_column("Seller")
    table.add_column("Title")
    table.add_column("URL")

    for index, listing in enumerate(listings, start=1):
        table.add_row(
            str(index),
            listing["platform"],
            _safe_console_text(listing["price_text"] or ""),
            listing["location"] or "",
            listing["seller_name"] or "",
            _safe_console_text(listing["title"] or ""),
            listing["url"],
        )

    console.print(table)


def print_run_details(config: AppConfig, console: Console, run_id: int) -> None:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        details = fetch_detail_snapshots_for_run(conn, run_id)

    table = Table(title=f"Detail Snapshots for Run {run_id}")
    table.add_column("ID")
    table.add_column("Blocked")
    table.add_column("Images", justify="right")
    table.add_column("Title")
    table.add_column("Text")
    table.add_column("URL")

    for detail in details:
        table.add_row(
            str(detail["id"]),
            "yes" if detail["access_blocked"] else "no",
            str(detail["image_count"]),
            _safe_console_text(detail["title"] or ""),
            detail["text_path"] or "",
            detail["url"],
        )

    console.print(table)


def _safe_console_text(value: str) -> str:
    return value.replace("¥", "CNY ")
