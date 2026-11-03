from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    connect,
    fetch_detail_snapshots_for_run,
    fetch_latest_listing_snapshots_for_run,
    initialize,
    update_listing_snapshot_seller_fields,
)
from shopping_agent.extraction.listing_parser import parse_price_value
from shopping_agent.platforms.xianyu_detail_parser import parse_xianyu_detail_text


@dataclass
class DecisionReportOptions:
    goal: str | None = None
    target_city: str | None = None
    max_listings: int = 20
    detailed_review_count: int = 3
    current_date: str = field(default_factory=lambda: date.today().isoformat())


DAMAGE_KEYWORDS = (
    "碎", "坏", "磕碰", "闪屏", "背光", "修过", "维修",
    "瑕疵", "裂", "花屏", "黑屏", "断", "凹", "变形",
)
MINT_CONDITION_KEYWORDS = ("几乎全新", "99新", "98新", "97新", "96新", "95新", "全新")
MINOR_CONDITION_KEYWORDS = ("细微", "轻微", "小磕", "轻微使用")


def build_decision_report(
    config: AppConfig,
    run_id: int,
    options: DecisionReportOptions | None = None,
) -> dict:
    """Build a four-section evidence report for a run.

    Gathers structured candidate data (including seller fields) and detail-page
    text from the DB, derives evidence signals, and returns a structured report
    dict rendered by render_decision_report_markdown. Purchase judgments remain
    the driving model's responsibility.
    """
    options = options or DecisionReportOptions()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        rows = fetch_latest_listing_snapshots_for_run(conn, run_id)
        detail_rows = fetch_detail_snapshots_for_run(conn, run_id)

    detail_text_by_listing = _load_detail_text(detail_rows)

    candidates = []
    for row in rows:
        candidate = _row_to_report_candidate(row, detail_text_by_listing)
        if candidate is not None:
            candidates.append(candidate)

    priced = [c["price_value"] for c in candidates if c["price_value"] is not None]
    distribution = _price_distribution(priced)
    for candidate in candidates:
        _enrich_candidate_assessment(candidate, distribution.get("median"))

    candidates = sorted(
        candidates,
        key=lambda c: (not c["has_detail"], c["price_value"] or 10**12),
    )
    detail_candidates = [c for c in candidates if c["has_detail"]][: options.max_listings]
    other_candidates = [c for c in candidates if not c["has_detail"]][
        : max(options.max_listings - len(detail_candidates), 0)
    ]
    candidates = detail_candidates + other_candidates
    market_overview = _build_market_overview(candidates, distribution, options)
    comparison_table = _build_comparison_table(candidates)
    detailed_reviews = _build_detailed_reviews(detail_candidates, options.detailed_review_count)
    uncertainties = _build_uncertainties(candidates)

    goal = options.goal or _infer_goal(candidates)
    return {
        "title": f"{goal} 二手候选证据报告" if goal else "二手候选证据报告",
        "goal": goal,
        "run_id": run_id,
        "generated_at": options.current_date,
        "candidate_count": len(candidates),
        "detail_candidate_count": len(detail_candidates),
        "market_overview": market_overview,
        "comparison_table": comparison_table,
        "detailed_reviews": detailed_reviews,
        "uncertainties": uncertainties,
        "candidates": candidates,
        "price_distribution": distribution,
        "notes": [
            "本报告只整理结构化证据与不确定性；卖家类型、价格风险和购买判断由模型结合用户需求完成。",
        ],
    }


def render_decision_report_markdown(report: dict) -> str:
    """Render a four-section Markdown evidence report."""
    lines: list[str] = []
    lines.append(f"# {report['title']}")
    lines.append("")
    detail_count = report.get("detail_candidate_count", 0)
    total = report.get("candidate_count", 0)
    lines.append(
        f"> 基于 {detail_count} 台含详情证据的候选商品结构化文本生成"
        f"（共 {total} 台候选）。报告生成时间：{report['generated_at']}。"
    )
    lines.append("")
    lines.append("## 一、市场证据")
    lines.append("")
    lines.append(report["market_overview"]["summary"])
    lines.append("")
    lines.append("## 二、候选对比")
    lines.append("")
    lines.append(_render_comparison_table(report["comparison_table"]))
    lines.append("")
    lines.append("## 三、重点候选证据")
    lines.append("")
    reviews = report["detailed_reviews"]
    if not reviews:
        lines.append("暂无含详情证据的候选。")
    for review in reviews:
        lines.append(f"### {review['label']}")
        lines.append("")
        for bullet in review["bullets"]:
            lines.append(f"- {bullet}")
        lines.append("")
    lines.append("## 四、不确定性")
    lines.append("")
    if not report["uncertainties"]:
        lines.append("暂无明显不确定性。")
    for item in report["uncertainties"]:
        lines.append(f"{item['index']}. {item['text']}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Candidate enrichment
# ---------------------------------------------------------------------------


def _row_to_report_candidate(row, detail_text_by_listing: dict) -> dict | None:
    listing_id = row["listing_id"]
    price_value = parse_price_value(row["price_text"])
    detail_text = detail_text_by_listing.get(listing_id, "")
    attributes, dom_seller = _parse_detail_text(detail_text)
    seller_fields = _merge_seller_fields(row, dom_seller)
    return {
        "listing_id": listing_id,
        "platform": row["platform"],
        "url": row["url"],
        "title": row["title"] or "",
        "price_text": row["price_text"],
        "price_value": price_value,
        "location": row["location"],
        "seller_name": row["seller_name"],
        "seller_fields": seller_fields,
        "attributes": attributes,
        "condition": attributes.get("成色"),
        "repair": attributes.get("拆修"),
        "memory": attributes.get("内存容量"),
        "storage": attributes.get("硬盘容量"),
        "model": attributes.get("型号"),
        "description": _truncate(row["description"] or "", 400),
        "has_detail": bool(detail_text),
        "source_type": row["source_type"],
        "collected_at": row["collected_at"],
    }


def _load_detail_text(detail_rows) -> dict[int, str]:
    result: dict[int, str] = {}
    for drow in detail_rows:
        listing_id = drow["listing_id"] if "listing_id" in drow.keys() else None
        text = _read_text_file(drow["text_path"])
        if text and listing_id is not None:
            result[listing_id] = text
    return result


def _read_text_file(text_path: str | None) -> str:
    if not text_path:
        return ""
    path = Path(text_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_detail_text(detail_text: str) -> tuple[dict, dict]:
    if not detail_text:
        return {}, {}
    try:
        parsed = parse_xianyu_detail_text(detail_text)
    except Exception:
        return {}, {}
    return parsed.attributes, parse_dom_seller_stats(parsed.seller_stats)


def backfill_seller_fields_from_detail_text(config: AppConfig, run_id: int) -> dict:
    """Backfill structured seller columns from DOM detail text for old runs.

    For runs collected before the MTOP pc.detail sellerDO parser was wired up,
    the seller DB columns are NULL but the saved detail-page text still carries
    seller stats (注册年限/卖出件数/好评率/实人认证). This parses those and updates
    the listing_snapshots rows in place; it never overwrites non-NULL DB fields.
    """
    initialize(config.database_path)
    backfilled: list[dict] = []
    with connect(config.database_path) as conn:
        rows = {row["listing_id"]: row for row in fetch_latest_listing_snapshots_for_run(conn, run_id)}
        detail_rows = fetch_detail_snapshots_for_run(conn, run_id)
        field_map = {
            "seller_registered_days": "seller_registered_days",
            "seller_sold_count": "seller_sold_count",
            "seller_good_rate": "seller_good_rate",
            "seller_realname_verified": "seller_realname_verified",
        }
        for drow in detail_rows:
            listing_id = drow["listing_id"] if "listing_id" in drow.keys() else None
            if listing_id is None:
                continue
            text = _read_text_file(drow["text_path"])
            if not text:
                continue
            _, dom_seller = _parse_detail_text(text)
            if not dom_seller:
                continue
            row = rows.get(listing_id)
            if row is None:
                continue
            update_fields: dict = {}
            for db_key, dom_key in field_map.items():
                if row[db_key] is None and dom_key in dom_seller:
                    update_fields[db_key] = dom_seller[dom_key]
            if update_fields:
                update_listing_snapshot_seller_fields(conn, row["id"], **update_fields)
                backfilled.append({"listing_id": listing_id, "fields": sorted(update_fields.keys())})
        conn.commit()
    return {"run_id": run_id, "backfilled_count": len(backfilled), "details": backfilled}


def parse_dom_seller_stats(seller_stats: list[str]) -> dict:
    """Extract structured seller signals from DOM-visible seller stat lines."""
    result: dict = {}
    for line in seller_stats or []:
        m = re.search(r"来闲鱼(\d+)年", line)
        if m:
            result["seller_registered_days"] = int(m.group(1)) * 365
            continue
        m = re.search(r"来闲鱼(\d+)天", line)
        if m:
            result["seller_registered_days"] = int(m.group(1))
            continue
        m = re.search(r"卖出(\d+)件", line)
        if m:
            result["seller_sold_count"] = int(m.group(1))
            continue
        m = re.search(r"好评率(\d+(?:\.\d+)?)%", line)
        if m:
            result["seller_good_rate"] = m.group(1) + "%"
            continue
        if "实人" in line or "认证" in line:
            result["seller_realname_verified"] = True
    return result


def _merge_seller_fields(row, dom_seller: dict) -> dict:
    """Merge DB seller columns with DOM-parsed fallbacks; DB takes priority."""
    db_fields = {
        "seller_credit_level": row["seller_credit_level"],
        "seller_registered_days": row["seller_registered_days"],
        "seller_sold_count": row["seller_sold_count"],
        "seller_good_rate": row["seller_good_rate"],
        "seller_realname_verified": bool(row["seller_realname_verified"])
        if row["seller_realname_verified"] is not None
        else None,
        "seller_reply_rate_24h": row["seller_reply_rate_24h"],
    }
    merged = {}
    has_db = False
    for key, value in db_fields.items():
        if value is not None:
            merged[key] = value
            has_db = True
        elif key in dom_seller:
            merged[key] = dom_seller[key]
        else:
            merged[key] = None
    merged["source"] = "db" if has_db else ("dom" if dom_seller else "none")
    return merged


def _enrich_candidate_assessment(candidate: dict, median: float | None) -> None:
    seller = candidate["seller_fields"]
    candidate["seller_credit"] = assess_seller_credit(seller)
    candidate["seller_type_evidence"] = assess_seller_type(seller)
    candidate["price_evidence"] = assess_price_risk(
        price_value=candidate["price_value"],
        median=median,
        condition=candidate["condition"],
        repair=candidate["repair"],
        description=candidate["description"],
    )


# ---------------------------------------------------------------------------
# Three seller judgments
# ---------------------------------------------------------------------------


# Platform credit levels as returned by MTOP sellerDO.zhimaLevelInfo.levelName,
# ordered best->worst. The page renders these as "卖家信用极好/优秀/良好/较差".
CREDIT_LEVEL_RANK = ["信用极好", "信用优秀", "信用良好", "信用较差"]


def assess_seller_credit(seller: dict) -> dict:
    """Pass through the platform seller credit level with supporting evidence.

    The credit level comes straight from MTOP sellerDO.zhimaLevelInfo.levelName
    (信用极好/优秀/良好/较差), which is what the Xianyu page renders as "卖家信用".
    Other structured signals are listed as evidence only; this function does NOT
    invent its own 高/中/低 tier, keeping judgment in the model's hands.
    """
    evidence: list[str] = []
    credit_level = seller.get("seller_credit_level")
    level = credit_level if credit_level else "信息不足"
    if credit_level:
        evidence.append(credit_level)
    good_rate = seller.get("seller_good_rate")
    if good_rate:
        evidence.append(f"好评率{good_rate}")
    days = seller.get("seller_registered_days")
    if days is not None:
        evidence.append(f"注册约{days / 365:.0f}年")
    if seller.get("seller_realname_verified"):
        evidence.append("实人认证")
    reply = seller.get("seller_reply_rate_24h")
    if reply:
        evidence.append(f"24h回复率{reply}")
    rank = CREDIT_LEVEL_RANK.index(credit_level) if credit_level in CREDIT_LEVEL_RANK else None
    return {"level": level, "rank": rank, "evidence": evidence}


def assess_seller_type(seller: dict) -> dict:
    """Return seller volume evidence; the model decides personal vs professional."""
    sold = seller.get("seller_sold_count")
    days = seller.get("seller_registered_days")
    evidence: list[str] = []
    if sold is not None:
        evidence.append(f"卖出{sold}件")
    if days is not None:
        evidence.append(f"注册约{days / 365:.0f}年")
    return {"evidence": evidence}


def _damage_keyword_hits(condition: str | None, repair: str | None, description: str) -> list[str]:
    """Detect damage keywords, treating negated repair phrases (无任何拆修) as clean.

    Returns the list of matched keywords (empty if clean)."""
    parts = [description or ""]
    if condition:
        parts.append(condition)
    if repair and not any(neg in repair for neg in ("无", "未", "没")):
        parts.append(repair)
    text_pool = " ".join(parts)
    return [kw for kw in DAMAGE_KEYWORDS if kw in text_pool]


def assess_price_risk(
    price_value: int | None,
    median: float | None,
    condition: str | None,
    repair: str | None,
    description: str,
) -> dict:
    """Return price-vs-median and damage signals; the model judges risk.

    Demoted from category labels (捡漏/硬伤/翻新) to evidence only, per the
    project principle that code gathers evidence and the model makes judgments.
    """
    evidence: list[str] = []
    if price_value is None or median is None or median == 0:
        return {"price_to_median": None, "damage_keyword_hits": [], "evidence": evidence}
    ratio = price_value / median
    evidence.append(f"价格约为中位数{ratio:.0%}")
    damage_hits = _damage_keyword_hits(condition, repair, description)
    if damage_hits:
        evidence.append(f"成色/描述含瑕疵关键词({', '.join(damage_hits[:3])})")
    if ratio < 0.75:
        evidence.append("低于中位数75%")
    elif ratio > 1.25:
        evidence.append("高于中位数125%")
    return {"price_to_median": round(ratio, 3), "damage_keyword_hits": damage_hits, "evidence": evidence}



# ---------------------------------------------------------------------------


def _build_market_overview(candidates: list[dict], distribution: dict, options) -> dict:
    dist = distribution
    parts: list[str] = []
    if dist["priced_count"] == 0:
        parts.append("本批候选无有效价格数据。")
        return {"summary": " ".join(parts)}
    parts.append(
        f"本批 {dist['priced_count']} 台候选价格区间 **¥{dist['min']} – ¥{dist['max']}**，"
        f"中位数约 ¥{dist['median']}，四分位 ¥{dist['p25']}–¥{dist['p75']}。"
    )
    detail = [c for c in candidates if c["has_detail"]]
    if detail:
        configs = _config_distribution(detail)
        if configs:
            parts.append("按配置/尺寸分布：" + "；".join(configs) + "。")
    low_price = [c for c in candidates if c["price_evidence"]["price_to_median"] is not None and c["price_evidence"]["price_to_median"] < 0.75]
    damaged = [c for c in candidates if c["price_evidence"]["damage_keyword_hits"]]
    if low_price:
        parts.append(f"其中 {len(low_price)} 台价格低于中位数75%")
    if damaged:
        parts.append(f"{len(damaged)} 台成色/描述含瑕疵关键词，需关注。")
    return {"summary": " ".join(parts)}


def _config_distribution(candidates: list[dict]) -> list[str]:
    groups: dict[str, list[dict]] = {}
    for c in candidates:
        key = _config_key(c)
        groups.setdefault(key, []).append(c)
    result = []
    for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        prices = [i["price_value"] for i in items if i["price_value"] is not None]
        avg = round(sum(prices) / len(prices)) if prices else None
        avg_text = f"，均价约 ¥{avg}" if avg else ""
        result.append(f"{key}（{len(items)}台{avg_text}）")
    return result


def _config_key(candidate: dict) -> str:
    mem = candidate.get("memory") or "未知内存"
    storage = candidate.get("storage") or "未知硬盘"
    model = candidate.get("model") or ""
    size = ""
    if "13" in model or "13寸" in (candidate.get("title") or ""):
        size = "13寸"
    elif "15" in model or "15寸" in (candidate.get("title") or ""):
        size = "15寸"
    return f"{size} {mem}+{storage}".strip()


def _build_comparison_table(candidates: list[dict]) -> list[dict]:
    rows = []
    for idx, c in enumerate(candidates, start=1):
        rows.append({
            "index": idx,
            "listing_id": c["listing_id"],
            "price": c["price_text"] or "—",
            "config": _config_key(c),
            "condition": c["condition"] or "未明确",
            "repair": c["repair"] or "未标",
            "seller_credit": _format_seller_credit(c),
            "seller_volume": _format_seller_volume(c),
            "price_vs_median": _format_price_evidence(c),
        })
    return rows


def _format_seller_credit(candidate: dict) -> str:
    credit = candidate["seller_credit"]
    ev = "，".join(credit["evidence"]) if credit["evidence"] else "无"
    return f"{credit['level']}（{ev}）"


def _format_seller_volume(candidate: dict) -> str:
    ev = candidate["seller_type_evidence"]["evidence"]
    return "，".join(ev) if ev else "信息不足"


def _format_price_evidence(candidate: dict) -> str:
    pe = candidate["price_evidence"]
    ratio = pe["price_to_median"]
    if ratio is None:
        return "无中位数"
    parts = [f"中位数{ratio:.0%}"]
    if pe["damage_keyword_hits"]:
        parts.append(f"瑕疵({','.join(pe['damage_keyword_hits'][:2])})")
    return "，".join(parts)


def _build_detailed_reviews(candidates: list[dict], count: int) -> list[dict]:
    reviews = []
    for c in candidates[:count]:
        label = _candidate_label(c)
        bullets: list[str] = []
        bullets.append(f"**配置**：{_config_key(c)}（listing {c['listing_id']}，{c['location'] or '地区未知'}）")
        pe = c["price_evidence"]
        bullets.append(f"**价格**：{c['price_text'] or '—'}（{'，'.join(pe['evidence']) or '无价格基准'}）")
        cond = c["condition"] or "未明确"
        repair = c["repair"] or "未标"
        bullets.append(f"**成色/拆修**：{cond} / {repair}")
        st = c["seller_type_evidence"]
        bullets.append(f"**卖家信号**：{'，'.join(st['evidence']) or '信息不足'}（个人vs专业由模型判断）")
        credit = c["seller_credit"]
        bullets.append(f"**卖家信用**：{credit['level']}（{'，'.join(credit['evidence']) or '信息不足'}）")
        if c["description"]:
            bullets.append(f"**描述摘要**：{c['description'][:120]}")
        reviews.append({"label": label, "bullets": bullets, "listing_id": c["listing_id"]})
    return reviews


def _build_uncertainties(candidates: list[dict]) -> list[dict]:
    items: list[str] = []
    no_detail = [c for c in candidates if not c["has_detail"]]
    if no_detail:
        items.append(f"{len(no_detail)} 台候选缺详情文本，成色/拆修/卖家信号不完整，无法充分评估。")
    no_seller = [c for c in candidates if c["seller_fields"]["source"] == "none"]
    if no_seller:
        items.append(f"{len(no_seller)} 台候选缺卖家结构化字段，卖家信用/类型判断依赖 DOM 文本回退或为空。")
    missing_condition = [c for c in candidates if c["has_detail"] and not c["condition"]]
    if missing_condition:
        ids = "，".join(str(c["listing_id"]) for c in missing_condition[:5])
        items.append(f"候选 {ids} 等成色字段缺失，外观状态无法核实。")
    low_credit = [c for c in candidates if c["seller_credit"]["level"] == "信用较差"]
    if low_credit:
        items.append(f"{len(low_credit)} 台卖家信用偏低，需额外核实。")
    items.append("本报告未采集/分析商品图片，现有外观证据仅来自文本。")
    items.append("闲鱼价格波动快，本报告基于采集时刻快照。")
    return [{"index": i + 1, "text": text} for i, text in enumerate(items)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _price_distribution(prices: list[int | float]) -> dict:
    priced = sorted(prices)
    count = len(priced)
    if count == 0:
        return {"priced_count": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None}

    def _quantile(fraction: float):
        if count == 1:
            return priced[0]
        index = min(int(round(fraction * (count - 1))), count - 1)
        return priced[index]

    return {
        "priced_count": count,
        "min": priced[0],
        "p25": _quantile(0.25),
        "median": _quantile(0.5),
        "p75": _quantile(0.75),
        "max": priced[-1],
    }
def _parse_rate_percent(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    if not match:
        return None
    return float(match.group(1))


def _truncate(value: str, max_chars: int) -> str:
    value = " ".join(value.split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _infer_goal(candidates: list[dict]) -> str | None:
    for c in candidates:
        title = c.get("title") or ""
        if title:
            return title.split("_")[0].strip()
    return None


def _candidate_label(candidate: dict) -> str:
    title = candidate.get("title") or ""
    short = title.split("_")[0][:24]
    return f"listing {candidate['listing_id']}（{candidate['price_text'] or '—'}，{short}）"


def _render_comparison_table(rows: list[dict]) -> str:
    if not rows:
        return "（无候选数据）"
    header = "| # | listing | 价格 | 配置 | 成色 | 拆修 | 卖家信用 | 卖家信号 | 价格vs中位 |\n"
    header += "|---|---------|------|------|------|------|----------|----------|----------|\n"
    body = "\n".join(
        f"| {r['index']} | {r['listing_id']} | {r['price']} | {r['config']} | "
        f"{r['condition']} | {r['repair']} | {r['seller_credit']} | {r['seller_volume']} | "
        f"{r['price_vs_median']} |"
        for r in rows
    )
    return header + body
