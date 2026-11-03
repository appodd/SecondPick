from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from shopping_agent.config import AppConfig


@dataclass
class ReportMetadata:
    title: str
    goal: str | None = None
    run_id: int | None = None
    listing_id: int | None = None
    created_date: str = field(default_factory=lambda: date.today().isoformat())
    extra_sections: list[str] = field(default_factory=list)


CORE_REPORT_SECTIONS = [
    "横向对比总表",
    "一句话结论",
    "排序和理由",
    "价格判断",
    "关键风险",
    "建议出价和下一步",
    "要问卖家的问题",
    "证据来源",
]


def render_placeholder_report(goal: str) -> str:
    return f"""# Shopping Research Report

## Goal

{goal}

## Status

The report renderer is scaffolded. Platform collection and evaluation are not implemented yet.
"""


def render_report_template(metadata: ReportMetadata) -> str:
    target_parts = []
    if metadata.run_id is not None:
        target_parts.append(f"run {metadata.run_id}")
    if metadata.listing_id is not None:
        target_parts.append(f"listing {metadata.listing_id}")
    target = ", ".join(target_parts) or "not specified"
    goal = metadata.goal or "not specified"
    core_sections = "\n".join(_render_core_section(section) for section in CORE_REPORT_SECTIONS)
    extra_sections = "\n".join(_render_extra_section(section) for section in metadata.extra_sections)
    if not extra_sections:
        extra_sections = """## 可选的商品专项分析

TODO: 只在确实有用时添加。例如：iMac 屏幕红边检查、笔记本电池循环、相机快门数、显卡矿卡风险、同城自提验机方案。不要加入工具运行日志。
"""
    return f"""# {metadata.title}

日期：{metadata.created_date}
购买目标：{goal}
数据范围：{target}

{core_sections}
{extra_sections}
"""


def save_markdown_report(
    config: AppConfig,
    markdown_text: str,
    metadata: ReportMetadata,
    filename: str | None = None,
) -> Path:
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = config.reports_dir / (filename or build_report_filename(metadata))
    if report_path.suffix.lower() != ".md":
        report_path = report_path.with_suffix(".md")
    report_path.write_text(markdown_text, encoding="utf-8")
    return report_path


def build_report_filename(metadata: ReportMetadata) -> str:
    parts = [metadata.created_date]
    if metadata.run_id is not None:
        parts.append(f"run-{metadata.run_id}")
    if metadata.listing_id is not None:
        parts.append(f"listing-{metadata.listing_id}")
    parts.append(_slugify(metadata.title))
    return "-".join(part for part in parts if part) + ".md"


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    normalized = re.sub(r"-+", "-", normalized)
    return normalized or "shopping-report"


def _render_core_section(section: str) -> str:
    guidance = {
        "横向对比总表": "这是报告核心。用 Markdown 表格横向比较：第一列是“对比项”，后续列是候选商品。第一行必须包含商品链接。行可以包括年份、CPU、CPU 多核性能、显卡、显卡性能、内存、硬盘、屏幕/体验、配件、交易方式、到手总成本、性价比。不要死板保留所有行；如果某一行所有候选都一样且没有决策增量，就删掉或合并到说明里。最优或最关键项用加粗。信息不足要写“待确认”，不要假装确定。",
        "一句话结论": "用 1-3 句话告诉用户最推荐谁、谁可以继续问、谁应该放弃。",
        "排序和理由": "给出排名表。每个候选只写购买理由和扣分点，不要重复参数。",
        "价格判断": "说明每个候选相对配置是否贵、合理或便宜，必须结合到手总成本。",
        "关键风险": "按影响购买决策的严重程度排序。每条风险要说明为什么重要、当前证据、还缺什么证据。",
        "建议出价和下一步": "给出可接受价、砍价目标、放弃条件和下一步动作。",
        "要问卖家的问题": "列出用户可以直接复制去问的问题，按优先级排序。",
        "证据来源": "简短列出链接、OCR 图片、官方规格、市场样本。不放命令日志；命令日志属于机器运行记录。",
    }
    return f"""## {section}

TODO: {guidance[section]}
"""


def _render_extra_section(section: str) -> str:
    return f"""## {section}

TODO: 如果这个专项分析能帮助用户做购买决策，就填写；否则删除。
"""
