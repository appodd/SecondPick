from __future__ import annotations

from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.reports.markdown import (
    ReportMetadata,
    build_report_filename,
    render_report_template,
    save_markdown_report,
)
from shopping_agent.reports.html import render_html_report_template


def test_render_report_template_contains_required_sections() -> None:
    report = render_report_template(
        ReportMetadata(
            title="iMac report",
            goal="找 2019 iMac 27 寸",
            run_id=4,
            listing_id=1,
            created_date="2026-06-17",
        )
    )

    assert "# iMac report" in report
    assert "购买目标：找 2019 iMac 27 寸" in report
    assert "数据范围：run 4, listing 1" in report
    assert "## 横向对比总表" in report
    assert "## 价格判断" in report
    assert "## 要问卖家的问题" in report
    assert "## 可选的商品专项分析" in report


def test_render_report_template_accepts_extra_sections() -> None:
    report = render_report_template(
        ReportMetadata(
            title="iMac report",
            created_date="2026-06-17",
            extra_sections=["iMac-Specific Hardware Checks", "Local Pickup Plan"],
        )
    )

    assert "## 横向对比总表" in report
    assert "## iMac-Specific Hardware Checks" in report
    assert "## Local Pickup Plan" in report
    assert "## 可选的商品专项分析" not in report


def test_build_report_filename_is_stable_and_ascii() -> None:
    filename = build_report_filename(
        ReportMetadata(
            title="找 2019 iMac 27 寸",
            run_id=4,
            listing_id=1,
            created_date="2026-06-17",
        )
    )

    assert filename == "2026-06-17-run-4-listing-1-2019-imac-27.md"


def test_save_markdown_report_writes_utf8() -> None:
    reports_dir = Path("data/test-reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "2026-06-17-listing-1-imac-report.md"
    if report_path.exists():
        report_path.unlink()
    config = AppConfig(reports_dir=reports_dir)
    metadata = ReportMetadata(title="iMac report", listing_id=1, created_date="2026-06-17")

    saved_path = save_markdown_report(config, "# 报告\n\n价格 ¥3550\n", metadata)

    assert saved_path == report_path
    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8") == "# 报告\n\n价格 ¥3550\n"


def test_render_html_report_template_marks_candidate_source() -> None:
    report = render_html_report_template(
        ReportMetadata(
            title="MacBook report",
            goal="找 MacBook Pro M1 Pro",
            run_id=7,
            created_date="2026-06-22",
        )
    )

    assert "候选来源" in report
    assert "横向对比总表" in report
