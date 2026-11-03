from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from shopping_agent.cli import build_parser
from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_listing_snapshot,
    add_saved_report,
    add_page_snapshot,
    attach_run_to_task,
    connect,
    create_query,
    create_research_task,
    create_search_run,
    fetch_recent_tasks,
    initialize,
    upsert_listing,
)
from shopping_agent.tasks import (
    build_task_summary,
    export_task,
    print_task_summary,
    update_task_preferences,
)


def test_task_schema_groups_runs_and_reports() -> None:
    config = AppConfig(database_path=Path("data/test-tasks.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)

    with connect(config.database_path) as conn:
        task_id = create_research_task(
            conn,
            title="MacBook M1 Pro",
            goal="帮我找一台 MacBook，M1 Pro，上海优先",
            city="上海",
        )
        run_id = create_search_run(conn, goal="MacBook Pro M1", city="上海")
        create_query(conn, run_id=run_id, platform="xianyu", query_text="MacBook Pro M1")
        attachment_id = attach_run_to_task(conn, task_id=task_id, run_id=run_id, role="search")
        report_id = add_saved_report(
            conn,
            task_id=task_id,
            run_id=run_id,
            path=Path("data/reports/macbook.html"),
            title="MacBook report",
            report_format="html",
            goal="帮我找一台 MacBook，M1 Pro，上海优先",
        )

    summary = build_task_summary(config, task_id)

    assert attachment_id > 0
    assert report_id > 0
    assert summary["task"]["id"] == task_id
    assert summary["runs"][0]["run_id"] == run_id
    assert summary["runs"][0]["role"] == "search"
    assert summary["runs"][0]["query_count"] == 1
    assert Path(summary["reports"][0]["path"]) == Path("data/reports/macbook.html")
    assert summary["reports"][0]["format"] == "html"


def test_recent_tasks_counts_attached_runs_and_reports() -> None:
    config = AppConfig(database_path=Path("data/test-tasks-recent.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)

    with connect(config.database_path) as conn:
        task_id = create_research_task(conn, title="iMac", goal="找 2019 iMac 27寸", city="上海")
        run_id = create_search_run(conn, goal="iMac 27", city="上海")
        attach_run_to_task(conn, task_id=task_id, run_id=run_id, role="search")
        add_saved_report(
            conn,
            task_id=task_id,
            run_id=run_id,
            path=Path("data/reports/imac.html"),
            title="iMac report",
            report_format="html",
        )
        tasks = fetch_recent_tasks(conn, limit=5)

    assert tasks[0]["id"] == task_id
    assert tasks[0]["run_count"] == 1
    assert tasks[0]["report_count"] == 1


def test_export_task_copies_referenced_files_and_manifest() -> None:
    root = Path("data/test-task-export")
    database_path = root / "shopping.sqlite"
    evidence_dir = root / "evidence"
    export_root = root / "exports"
    if root.exists():
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    search_html = evidence_dir / "search.html"
    search_txt = evidence_dir / "search.txt"
    search_png = evidence_dir / "search.png"
    search_links = evidence_dir / "search.links.txt"
    report_html = evidence_dir / "report.html"
    for path, text in [
        (search_html, "<html>search</html>"),
        (search_txt, "visible text"),
        (search_png, "not really png"),
        (search_links, "https://example.test/item/1"),
        (report_html, "<html>report</html>"),
    ]:
        path.write_text(text, encoding="utf-8")
    config = AppConfig(database_path=database_path)
    initialize(config.database_path)

    with connect(config.database_path) as conn:
        task_id = create_research_task(conn, title="MacBook Export", goal="找 MacBook", city="上海")
        run_id = create_search_run(conn, goal="MacBook", city="上海")
        attach_run_to_task(conn, task_id=task_id, run_id=run_id, role="search")
        add_page_snapshot(
            conn,
            run_id=run_id,
            platform="xianyu",
            query_text="MacBook",
            url="https://www.goofish.com/search?q=MacBook",
            title="MacBook",
            screenshot_path=search_png,
            html_path=search_html,
            text_path=search_txt,
            links_path=search_links,
            link_count=1,
            access_blocked=False,
        )
        add_saved_report(
            conn,
            task_id=task_id,
            run_id=run_id,
            path=report_html,
            title="MacBook report",
            report_format="html",
        )

    result = export_task(config, task_id=task_id, output_dir=export_root)

    assert result.copied_files == 5
    assert result.missing_files == 0
    assert result.manifest_path.exists()
    manifest_text = result.manifest_path.read_text(encoding="utf-8")
    assert "MacBook Export" in manifest_text
    assert len(list((result.export_dir / "files").rglob("*.*"))) == 5


def test_task_cli_parsers_accept_grouping_options() -> None:
    parser = build_parser()

    create_args = parser.parse_args(
        [
            "task-create",
            "--title",
            "MacBook",
            "--goal",
            "找 MacBook Pro M1",
            "--city",
            "上海",
        ]
    )
    attach_args = parser.parse_args(["task-attach-run", "--task-id", "2", "--run-id", "33", "--role", "baseline"])
    summary_args = parser.parse_args(["task-summary", "--task-id", "2", "--pretty"])
    detail_args = parser.parse_args(["detail-candidates", "--task-id", "2", "--limit", "20", "--pretty"])
    update_args = parser.parse_args(
        [
            "task-update",
            "--task-id",
            "2",
            "--user-message",
            "价格不再优先，可靠性更重要",
            "--effective-goal",
            "找可靠的上海自提 iPhone 15 Pro",
            "--add-preference",
            "可靠性优先",
            "--add-preference",
            "上海自提",
            "--remove-preference",
            "极致低价",
        ]
    )
    export_args = parser.parse_args(["export-task", "--task-id", "2", "--output-dir", "data/exports"])
    spike_args = parser.parse_args(
        ["spike-search", "xianyu", "MacBook Pro M1", "--task-id", "2", "--i-understand-account-risk"]
    )
    save_args = parser.parse_args(["save-html-report", "--stdin", "--task-id", "2"])

    assert create_args.command == "task-create"
    assert create_args.title == "MacBook"
    assert attach_args.role == "baseline"
    assert summary_args.pretty is True
    assert detail_args.limit == 20
    assert update_args.user_message == "价格不再优先，可靠性更重要"
    assert update_args.effective_goal == "找可靠的上海自提 iPhone 15 Pro"
    assert update_args.add_preference == ["可靠性优先", "上海自提"]
    assert update_args.remove_preference == ["极致低价"]
    assert export_args.command == "export-task"
    assert export_args.task_id == 2
    assert spike_args.task_id == 2
    assert save_args.task_id == 2


def test_task_summary_includes_deduplicated_search_coverage(tmp_path: Path) -> None:
    config = AppConfig(database_path=tmp_path / "shopping.sqlite")
    initialize(config.database_path)

    with connect(config.database_path) as conn:
        task_id = create_research_task(
            conn,
            title="R9000P",
            goal="找一台 R9000P",
            city="上海",
        )
        run_1 = create_search_run(conn, goal="R9000P", city="上海")
        run_2 = create_search_run(conn, goal="R9000P 4060", city="上海")
        create_query(conn, run_id=run_1, platform="xianyu", query_text="R9000P")
        create_query(conn, run_id=run_2, platform="xianyu", query_text="R9000P 4060")
        attach_run_to_task(conn, task_id=task_id, run_id=run_1)
        attach_run_to_task(conn, task_id=task_id, run_id=run_2)
        shared_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=shared",
        )
        new_id = upsert_listing(
            conn,
            platform="xianyu",
            url="https://www.goofish.com/item?id=new",
        )
        add_listing_snapshot(conn, listing_id=shared_id, run_id=run_1, title="shared")
        add_listing_snapshot(conn, listing_id=shared_id, run_id=run_2, title="shared")
        add_listing_snapshot(conn, listing_id=new_id, run_id=run_2, title="new")

    coverage = build_task_summary(config, task_id)["search_coverage"]

    assert coverage["unique_candidates"] == 2
    assert coverage["runs"][0]["source_queries"] == ["R9000P"]
    assert coverage["runs"][1]["new_unique_count"] == 1
    assert coverage["runs"][1]["new_unique_ratio"] == 1.0

    output = StringIO()
    console = Console(file=output, force_terminal=False, width=200)
    print_task_summary(config, console, task_id)

    rendered = output.getvalue()
    assert "Search Coverage" in rendered
    assert "2 unique candidates" in rendered
    assert "collecting" in rendered
    assert "R9000P 4060" in rendered
    assert "1" in rendered
    assert "100.00%" in rendered


def test_task_preference_revisions_are_append_only_and_update_effective_goal(
    tmp_path: Path,
) -> None:
    config = AppConfig(database_path=tmp_path / "task-preferences.sqlite")
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        task_id = create_research_task(
            conn,
            title="iPhone 15 Pro 上海",
            goal="想看 iPhone 15 Pro，最好别太贵",
            city="上海",
        )

    first_revision_id = update_task_preferences(
        config,
        task_id=task_id,
        user_message="四千以内，有正常使用痕迹可以接受",
        effective_goal="找上海优先、四千以内、可接受正常痕迹的 iPhone 15 Pro",
        added_preferences=["四千以内", "接受正常使用痕迹"],
        removed_preferences=["无明显划痕"],
    )
    second_revision_id = update_task_preferences(
        config,
        task_id=task_id,
        user_message="太便宜的不考虑，可靠性优先，128GB 够用",
        effective_goal="找可靠性优先、上海自提、四千左右、128GB 可接受的 iPhone 15 Pro",
        added_preferences=["可靠性优先", "128GB 可接受"],
        removed_preferences=["低价优先"],
    )

    summary = build_task_summary(config, task_id)

    assert second_revision_id > first_revision_id
    assert summary["task"]["goal"] == "想看 iPhone 15 Pro，最好别太贵"
    assert summary["task"]["original_goal"] == "想看 iPhone 15 Pro，最好别太贵"
    assert summary["task"]["effective_goal"] == (
        "找可靠性优先、上海自提、四千左右、128GB 可接受的 iPhone 15 Pro"
    )
    assert [item["user_message"] for item in summary["preference_revisions"]] == [
        "四千以内，有正常使用痕迹可以接受",
        "太便宜的不考虑，可靠性优先，128GB 够用",
    ]
    assert summary["preference_revisions"][0]["added_preferences"] == [
        "四千以内",
        "接受正常使用痕迹",
    ]
    assert summary["preference_revisions"][0]["removed_preferences"] == [
        "无明显划痕"
    ]
    assert summary["preference_revisions"][1]["added_preferences"] == [
        "可靠性优先",
        "128GB 可接受",
    ]
