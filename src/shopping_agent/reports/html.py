from __future__ import annotations

import html
from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.reports.markdown import ReportMetadata, build_report_filename


HTML_COMPARISON_ROWS = [
    "候选来源",
    "商品链接",
    "当前动作",
    "到手总成本",
    "年份/型号",
    "CPU/性能基准",
    "显卡/图形性能",
    "内存",
    "硬盘",
    "屏幕/外观",
    "配件/交易方式",
    "卖家类型倾向",
    "关键风险",
    "建议出价",
    "待问卖家",
]


def save_html_report(
    config: AppConfig,
    html_text: str,
    metadata: ReportMetadata,
    filename: str | None = None,
) -> Path:
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = config.reports_dir / (filename or build_report_filename(metadata))
    if report_path.suffix.lower() != ".html":
        report_path = report_path.with_suffix(".html")
    report_path.write_text(_ensure_html_document(html_text, metadata=metadata), encoding="utf-8")
    return report_path


def render_html_report_template(metadata: ReportMetadata) -> str:
    target_parts = []
    if metadata.run_id is not None:
        target_parts.append(f"run {metadata.run_id}")
    if metadata.listing_id is not None:
        target_parts.append(f"listing {metadata.listing_id}")
    target = ", ".join(target_parts) or "not specified"
    goal = metadata.goal or "not specified"
    extra_sections = "\n".join(_render_extra_html_section(section) for section in metadata.extra_sections)
    if not extra_sections:
        extra_sections = """<section>
  <h2>可选的商品专项分析</h2>
  <p>TODO: 只在确实有用时添加。例如 iMac 屏幕红边、笔记本电池循环、相机快门数、显卡矿卡风险、同城自提验机方案。不要加入工具运行日志。</p>
</section>"""

    return f"""<section>
  <h1>{html.escape(metadata.title)}</h1>
  <p><strong>日期：</strong>{html.escape(metadata.created_date)}</p>
  <p><strong>购买目标：</strong>{html.escape(goal)}</p>
  <p><strong>数据范围：</strong>{html.escape(target)}</p>
</section>

<section>
  <h2>横向对比总表</h2>
  <p>TODO: 第一屏先给购买决策表。候选列来自同一个候选池；不要引入没有证据的新商品。信息不足写“待确认”，不要假装确定。没有决策增量的行可以删除。</p>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>对比项</th>
          <th>候选 A</th>
          <th>候选 B</th>
          <th>候选 C</th>
        </tr>
      </thead>
      <tbody>
{_render_comparison_rows()}
      </tbody>
    </table>
  </div>
</section>

<section>
  <h2>一句话结论</h2>
  <p>TODO: 用 1-3 句话告诉用户最推荐谁、谁可以继续问、谁应该放弃。</p>
</section>

<section>
  <h2>推荐排序</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>排序</th>
          <th>候选</th>
          <th>推荐类型</th>
          <th>理由</th>
          <th>扣分点</th>
          <th>下一步</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>1</td>
          <td>TODO</td>
          <td>高性价比 / 高质量 / 低预算 / 暂不推荐</td>
          <td>TODO</td>
          <td>TODO</td>
          <td>TODO</td>
        </tr>
      </tbody>
    </table>
  </div>
</section>

<section>
  <h2>价格判断</h2>
  <p>TODO: 说明每个候选相对同配置样本是偏低、合理还是偏高。写清样本数、平台、时间范围、排除的异常样本和证据质量。</p>
</section>

<section>
  <h2>关键风险</h2>
  <ul>
    <li>TODO: 按影响购买决策的严重程度排序。每条风险写“为什么重要 / 当前证据 / 还缺什么证据”。</li>
  </ul>
</section>

<section>
  <h2>要问卖家的问题</h2>
  <ol>
    <li>TODO: 用户可以直接复制给卖家的问题，按优先级排序。</li>
  </ol>
</section>

<section>
  <h2>证据来源</h2>
  <p>TODO: 简短列出商品链接、OCR 图片、官方规格、市场样本。不放命令日志。</p>
</section>

{extra_sections}
"""


def _ensure_html_document(html_text: str, *, metadata: ReportMetadata) -> str:
    if _looks_like_full_html_document(html_text):
        return html_text
    return render_basic_html_document(metadata.title, html_text)


def _looks_like_full_html_document(html_text: str) -> bool:
    prefix = html_text.lstrip()[:300].lower()
    return "<!doctype html" in prefix or "<html" in prefix


def render_basic_html_document(title: str, body_html: str) -> str:
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    body {{
      margin: 0;
      background: #f6f7f9;
      color: #20242a;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      line-height: 1.55;
    }}
    main {{
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 44px;
    }}
    section {{
      background: #fff;
      border: 1px solid #e4e7eb;
      border-radius: 8px;
      padding: 18px;
      margin-top: 14px;
    }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid #e4e7eb;
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      min-width: 920px;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: 12px 14px;
      border: 1px solid #e4e7eb;
    }}
    th {{
      background: #f2f4f7;
    }}
    .best {{ color: #137a46; font-weight: 800; }}
    .warn {{ color: #9a5b00; font-weight: 700; }}
    .risk {{ color: #ad2f2f; font-weight: 700; }}
    a {{ color: #1d5fbf; }}
  </style>
</head>
<body>
  <main>
{body_html}
  </main>
</body>
</html>
"""


def _render_comparison_rows() -> str:
    return "\n".join(
        f"""        <tr>
          <th>{html.escape(row)}</th>
          <td>TODO</td>
          <td>TODO</td>
          <td>TODO</td>
        </tr>"""
        for row in HTML_COMPARISON_ROWS
    )


def _render_extra_html_section(section: str) -> str:
    return f"""<section>
  <h2>{html.escape(section)}</h2>
  <p>TODO: 如果这个专项分析能帮助用户做购买决策，就填写；否则删除。</p>
</section>"""
