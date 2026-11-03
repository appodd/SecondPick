from __future__ import annotations

from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.reports.html import render_basic_html_document, render_html_report_template, save_html_report
from shopping_agent.reports.markdown import ReportMetadata


def test_save_html_report_writes_utf8() -> None:
    reports_dir = Path("data/test-reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "2026-06-17-listing-1-imac-report.html"
    if report_path.exists():
        report_path.unlink()
    config = AppConfig(reports_dir=reports_dir)
    metadata = ReportMetadata(title="iMac report", listing_id=1, created_date="2026-06-17")

    saved_path = save_html_report(config, "<h1>报告</h1><p>价格 ¥3550</p>", metadata)

    assert saved_path == report_path
    assert saved_path.exists()
    saved_html = saved_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in saved_html
    assert "<title>iMac report</title>" in saved_html
    assert "<h1>报告</h1><p>价格 ¥3550</p>" in saved_html


def test_save_html_report_preserves_full_html_document() -> None:
    reports_dir = Path("data/test-reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "2026-06-17-listing-1-full-report.html"
    if report_path.exists():
        report_path.unlink()
    config = AppConfig(reports_dir=reports_dir)
    metadata = ReportMetadata(title="full report", listing_id=1, created_date="2026-06-17")
    html = '<!doctype html><html lang="zh-CN"><head><title>自定义</title></head><body>报告</body></html>'

    saved_path = save_html_report(config, html, metadata, filename="2026-06-17-listing-1-full-report.html")

    assert saved_path == report_path
    assert saved_path.read_text(encoding="utf-8") == html


def test_render_basic_html_document_contains_responsive_table_styles() -> None:
    html = render_basic_html_document("iMac 对比", "<section><h1>内容</h1></section>")

    assert "<title>iMac 对比</title>" in html
    assert 'lang="zh-CN"' in html
    assert ".table-wrap" in html
    assert "<section><h1>内容</h1></section>" in html


def test_render_html_report_template_contains_purchase_comparison_table() -> None:
    html = render_html_report_template(
        ReportMetadata(
            title="iMac 对比",
            goal="找 2019 iMac 27 寸",
            run_id=4,
            created_date="2026-06-17",
        )
    )

    assert "<h1>iMac 对比</h1>" in html
    assert "购买目标：</strong>找 2019 iMac 27 寸" in html
    assert "数据范围：</strong>run 4" in html
    assert "<h2>横向对比总表</h2>" in html
    assert "<th>对比项</th>" in html
    assert "<th>候选 A</th>" in html
    assert "<th>商品链接</th>" in html
    assert "<th>CPU/性能基准</th>" in html
    assert "<h2>要问卖家的问题</h2>" in html
    assert "不要加入工具运行日志" in html
