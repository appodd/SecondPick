from __future__ import annotations

from shopping_agent.region_preference import region_preference

import json
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_task_preference_revision,
    attach_run_to_task,
    connect,
    create_research_task,
    fetch_recent_tasks,
    fetch_research_task,
    fetch_queries_for_run,
    fetch_task_file_references,
    fetch_task_preference_revisions,
    fetch_task_reports,
    fetch_task_runs,
    fetch_unique_listing_ids_for_run,
    initialize,
)
from shopping_agent.task_coverage import build_search_coverage


@dataclass
class TaskExportResult:
    task_id: int
    export_dir: Path
    manifest_path: Path
    copied_files: int
    missing_files: int


def create_task(config: AppConfig, title: str, goal: str, city: str | None = None, notes: str | None = None) -> int:
    initialize(config.database_path)
    # A caller-supplied --city is explicit intent, unlike config.default_city.
    # Preserve that intent in the existing goal text so future readers need not
    # guess the provenance of the legacy city column. Existing tasks are untouched.
    if city and city.strip() and region_preference(goal)['city'] is None:
        goal += f"\n交易地区偏好：{city.strip()}优先"
    with connect(config.database_path) as conn:
        return create_research_task(conn, title=title, goal=goal, city=region_preference(goal, explicit_city=city)['city'] or '', notes=notes)


def attach_run(config: AppConfig, task_id: int, run_id: int, role: str = "search", notes: str | None = None) -> int:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        return attach_run_to_task(conn, task_id=task_id, run_id=run_id, role=role, notes=notes)


def update_task_preferences(
    config: AppConfig,
    task_id: int,
    user_message: str,
    effective_goal: str,
    added_preferences: list[str] | None = None,
    removed_preferences: list[str] | None = None,
) -> int:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        return add_task_preference_revision(
            conn,
            task_id=task_id,
            user_message=user_message,
            effective_goal=effective_goal,
            added_preferences_json=json.dumps(added_preferences or [], ensure_ascii=False),
            removed_preferences_json=json.dumps(removed_preferences or [], ensure_ascii=False),
        )


def build_task_summary(config: AppConfig, task_id: int) -> dict:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task = fetch_research_task(conn, task_id)
        if task is None:
            raise ValueError(f"Research task not found: {task_id}")
        runs = fetch_task_runs(conn, task_id)
        reports = fetch_task_reports(conn, task_id)
        preference_revision_rows = fetch_task_preference_revisions(conn, task_id)
        run_records = [
            {
                "run_id": int(row["run_id"]),
                "source_queries": fetch_queries_for_run(conn, int(row["run_id"])),
            }
            for row in runs
        ]
        listing_ids_by_run = {
            int(row["run_id"]): fetch_unique_listing_ids_for_run(conn, int(row["run_id"]))
            for row in runs
        }

    source_queries_by_run = {
        record["run_id"]: record["source_queries"] for record in run_records
    }
    preference_revisions = [
        {
            "id": row["id"],
            "task_id": row["task_id"],
            "user_message": row["user_message"],
            "effective_goal": row["effective_goal"],
            "added_preferences": json.loads(row["added_preferences_json"]),
            "removed_preferences": json.loads(row["removed_preferences_json"]),
            "created_at": row["created_at"],
        }
        for row in preference_revision_rows
    ]
    effective_goal = (
        preference_revisions[-1]["effective_goal"] if preference_revisions else task["goal"]
    )

    return {
        "task": {
            "id": task["id"],
            "title": task["title"],
            "goal": task["goal"],
            "original_goal": task["goal"],
            "effective_goal": effective_goal,
            "city": task["city"],
            "status": task["status"],
            "notes": task["notes"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        },
        "runs": [
            {
                "run_id": row["run_id"],
                "role": row["role"],
                "notes": row["notes"],
                "goal": row["goal"],
                "city": row["city"],
                "query_count": row["query_count"],
                "page_snapshot_count": row["page_snapshot_count"],
                "listing_snapshot_count": row["listing_snapshot_count"],
                "run_created_at": row["run_created_at"],
                "attached_at": row["attached_at"],
                "source_queries": source_queries_by_run[int(row["run_id"])],
            }
            for row in runs
        ],
        "reports": [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "listing_id": row["listing_id"],
                "title": row["title"],
                "goal": row["goal"],
                "format": row["format"],
                "path": row["path"],
                "created_at": row["created_at"],
            }
            for row in reports
        ],
        "preference_revisions": preference_revisions,
        "search_coverage": build_search_coverage(run_records, listing_ids_by_run),
    }


def export_task(config: AppConfig, task_id: int, output_dir: Path | None = None) -> TaskExportResult:
    summary = build_task_summary(config, task_id)
    task = summary["task"]
    export_root = output_dir or Path("data/exports")
    export_dir = export_root / f"{date.today().isoformat()}-task-{task_id}-{_slugify(task['title'])}"
    files_dir = export_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    initialize(config.database_path)
    with connect(config.database_path) as conn:
        file_refs = fetch_task_file_references(conn, task_id)

    copied: list[dict] = []
    missing: list[dict] = []
    seen_destinations: set[Path] = set()
    for row in file_refs:
        raw_path = str(row["path"] or "").strip()
        if not raw_path:
            continue
        source_path = Path(raw_path)
        if not source_path.exists():
            missing.append(_file_ref_dict(row, source_path=source_path, exported_path=None))
            continue
        relative_path = _safe_relative_path(source_path)
        destination = files_dir / relative_path
        destination = _deduplicate_destination(destination, seen_destinations)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        seen_destinations.add(destination)
        copied.append(_file_ref_dict(row, source_path=source_path, exported_path=destination))

    manifest = {
        "summary": summary,
        "export": {
            "task_id": task_id,
            "export_dir": str(export_dir),
            "copied_files": len(copied),
            "missing_files": len(missing),
        },
        "copied_files": copied,
        "missing_files": missing,
    }
    manifest_path = export_dir / "task-summary.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return TaskExportResult(
        task_id=task_id,
        export_dir=export_dir,
        manifest_path=manifest_path,
        copied_files=len(copied),
        missing_files=len(missing),
    )


def print_recent_tasks(config: AppConfig, console: Console, limit: int = 10) -> None:
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        tasks = fetch_recent_tasks(conn, limit=limit)

    table = Table(title="Recent Research Tasks")
    table.add_column("Task")
    table.add_column("Title")
    table.add_column("City")
    table.add_column("Status")
    table.add_column("Runs", justify="right")
    table.add_column("Reports", justify="right")
    table.add_column("Updated")

    for task in tasks:
        table.add_row(
            str(task["id"]),
            task["title"],
            task["city"],
            task["status"],
            str(task["run_count"]),
            str(task["report_count"]),
            task["updated_at"],
        )

    console.print(table)


def print_task_summary(config: AppConfig, console: Console, task_id: int) -> None:
    summary = build_task_summary(config, task_id)
    task = summary["task"]
    console.print(f"[bold]Task {task['id']}:[/bold] {task['title']}")
    console.print(f"Goal: {task['goal']}")
    console.print(f"City: {task['city']}")
    console.print(f"Status: {task['status']}")
    if task["notes"]:
        console.print(f"Notes: {task['notes']}")

    coverage = summary["search_coverage"]
    console.print(
        f"[bold]Search Coverage:[/bold] {coverage['unique_candidates']} unique candidates "
        f"({coverage['status']})"
    )
    coverage_table = Table(title="Search Coverage by Run")
    coverage_table.add_column("Run")
    coverage_table.add_column("Queries")
    coverage_table.add_column("Unique", justify="right")
    coverage_table.add_column("New", justify="right")
    coverage_table.add_column("Cumulative", justify="right")
    coverage_table.add_column("Gain", justify="right")
    for run in coverage["runs"]:
        gain = run["new_unique_ratio"]
        coverage_table.add_row(
            str(run["run_id"]),
            ", ".join(run["source_queries"]) or "-",
            str(run["unique_in_run"]),
            str(run["new_unique_count"]),
            str(run["cumulative_unique_count"]),
            "-" if gain is None else f"{gain:.2%}",
        )
    console.print(coverage_table)

    run_table = Table(title=f"Runs for Task {task_id}")
    run_table.add_column("Run")
    run_table.add_column("Role")
    run_table.add_column("Goal")
    run_table.add_column("Listings", justify="right")
    run_table.add_column("Created")
    for run in summary["runs"]:
        run_table.add_row(
            str(run["run_id"]),
            run["role"],
            run["goal"],
            str(run["listing_snapshot_count"]),
            run["run_created_at"],
        )
    console.print(run_table)

    report_table = Table(title=f"Reports for Task {task_id}")
    report_table.add_column("ID")
    report_table.add_column("Format")
    report_table.add_column("Title")
    report_table.add_column("Path")
    report_table.add_column("Created")
    for report in summary["reports"]:
        report_table.add_row(
            str(report["id"]),
            report["format"],
            report["title"],
            report["path"],
            report["created_at"],
        )
    console.print(report_table)


def _file_ref_dict(row, *, source_path: Path, exported_path: Path | None) -> dict:
    return {
        "source": row["source"],
        "source_id": row["source_id"],
        "source_path": str(source_path),
        "exported_path": str(exported_path) if exported_path is not None else None,
    }


def _safe_relative_path(path: Path) -> Path:
    parts = [part for part in path.parts if part not in {"", ".", ".."}]
    if path.drive:
        parts = [part.replace(":", "") for part in parts if part != path.anchor]
    return Path(*parts[-4:]) if len(parts) > 4 else Path(*parts)


def _deduplicate_destination(destination: Path, seen_destinations: set[Path]) -> Path:
    if destination not in seen_destinations and not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if candidate not in seen_destinations and not candidate.exists():
            return candidate
        index += 1


def _slugify(value: str) -> str:
    chars = []
    previous_dash = False
    for char in value.lower():
        if char.isascii() and char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")
    return slug or "shopping-task"
