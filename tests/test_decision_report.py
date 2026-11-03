from __future__ import annotations

from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.db import (
    add_detail_snapshot,
    add_listing_snapshot,
    connect,
    create_search_run,
    initialize,
    upsert_listing,
)
from shopping_agent.decision_report import (
    DecisionReportOptions,
    assess_price_risk,
    assess_seller_credit,
    assess_seller_type,
    build_decision_report,
    parse_dom_seller_stats,
    render_decision_report_markdown,
)


def _make_detail_text(
    seller_name: str,
    city: str,
    stats: list[str],
    price: str,
    description: str,
    condition: str,
    repair: str,
) -> str:
    """Build a minimal Xianyu detail page text that the DOM parser can read."""
    lines = [
        "搜索",
        "网页版发闲置功能又升级啦！",
        seller_name,
        city,
        "1小时前来过",
        *stats,
        "闲鱼号",
        "担保交易",
        "举报",
        "¥",
        price,
        "包邮",
        "2人想要",
        "50浏览",
        "下单后寄至验货中心先验后买",
        description,
        "品",
        "牌",
        "：",
        "Apple/苹果",
        "型",
        "号",
        "：",
        "MacBook Air 2022 13寸",
        "内",
        "存",
        "容",
        "量",
        "：",
        "8GB",
        "拆",
        "修",
        "：",
        repair,
        "成",
        "色",
        "：",
        condition,
        "硬",
        "盘",
        "容",
        "量",
        "：",
        "256GB",
        "聊一聊",
        "立即购买",
        "收藏",
    ]
    return "\n".join(lines)


def _seed_run(config: AppConfig, tmp_path: Path) -> tuple:
    """Create a run with three listings: bargain, damage-risk, and fair-price."""
    initialize(config.database_path)
    text_dir = tmp_path / "texts"
    text_dir.mkdir()
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="MacBook Air M2", city="上海")

        # Listing A: personal seller, near-new, fair price (good candidate)
        a_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=9001")
        add_listing_snapshot(
            conn,
            listing_id=a_id,
            run_id=run_id,
            title="MacBook Air M2 13寸 8+256",
            price_text="¥3666",
            location="深圳",
            seller_name="个人卖家甲",
            description="自用近新，电池循环16次，已有验机报告",
            seller_credit_level="信用极好",
            seller_registered_days=2190,
            seller_sold_count=5,
            seller_good_rate="100%",
            seller_realname_verified=True,
            seller_reply_rate_24h="95%",
        )
        a_text = text_dir / "a.txt"
        a_text.write_text(
            _make_detail_text("个人卖家甲", "深圳", ["来闲鱼6年", "卖出5件宝贝", "好评率100%"],
                             "3666", "自用近新电池循环16次已有验机报告", "几乎全新", "无任何拆修"),
            encoding="utf-8",
        )
        add_detail_snapshot(conn, a_id, run_id, "https://www.goofish.com/item?id=9001",
                            "MacBook Air M2", text_dir / "a_s.png", text_dir / "a.html",
                            a_text, text_dir / "a.links.txt", text_dir / "a.images.txt",
                            0, 0, False)

        # Listing B: professional merchant, low price, damaged (damage risk)
        b_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=9002")
        add_listing_snapshot(
            conn,
            listing_id=b_id,
            run_id=run_id,
            title="MacBook Air M2 13寸 低价",
            price_text="¥2499",
            location="惠州",
            seller_name="专业商家乙",
            description="屏幕碎角闪屏，便宜出",
            seller_credit_level="信用良好",
            seller_registered_days=3285,
            seller_sold_count=3829,
            seller_good_rate="93%",
            seller_realname_verified=False,
        )
        b_text = text_dir / "b.txt"
        b_text.write_text(
            _make_detail_text("专业商家乙", "惠州", ["来闲鱼9年", "卖出3829件宝贝", "好评率93%"],
                             "2499", "屏幕碎角闪屏便宜出", "明显磕碰划痕", "无任何拆修"),
            encoding="utf-8",
        )
        add_detail_snapshot(conn, b_id, run_id, "https://www.goofish.com/item?id=9002",
                            "MacBook Air M2 低价", text_dir / "b_s.png", text_dir / "b.html",
                            b_text, text_dir / "b.links.txt", text_dir / "b.images.txt",
                            0, 0, False)

        # Listing C: personal seller, minor wear, fair price
        c_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=9003")
        add_listing_snapshot(
            conn,
            listing_id=c_id,
            run_id=run_id,
            title="MacBook Air M2 13寸 灰",
            price_text="¥3690",
            location="上饶",
            seller_name="个人卖家丙",
            description="箱说全，可提供购买记录",
            seller_registered_days=2920,
            seller_sold_count=48,
            seller_good_rate="100%",
        )
        c_text = text_dir / "c.txt"
        c_text.write_text(
            _make_detail_text("个人卖家丙", "上饶", ["来闲鱼8年", "卖出48件宝贝", "好评率100%"],
                             "3690", "箱说全可提供购买记录", "细微磕碰划痕", "无任何拆修"),
            encoding="utf-8",
        )
        add_detail_snapshot(conn, c_id, run_id, "https://www.goofish.com/item?id=9003",
                            "MacBook Air M2 灰", text_dir / "c_s.png", text_dir / "c.html",
                            c_text, text_dir / "c.links.txt", text_dir / "c.images.txt",
                            0, 0, False)
        conn.commit()
    return run_id, {"a": a_id, "b": b_id, "c": c_id}


def test_decision_report_contains_evidence_sections_without_purchase_judgments(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test-decision-report.sqlite"
    config = AppConfig(database_path=db_path)
    run_id, ids = _seed_run(config, tmp_path)

    report = build_decision_report(
        config, run_id, DecisionReportOptions(goal="MacBook Air M2", max_listings=10)
    )
    markdown = render_decision_report_markdown(report)

    assert "## 一、市场证据" in markdown
    assert "## 二、候选对比" in markdown
    assert "## 三、重点候选证据" in markdown
    assert "## 四、不确定性" in markdown
    assert "purchase_advice" not in report
    for forbidden in ("购买建议", "首选", "备选", "不建议"):
        assert forbidden not in markdown

    assert "中位数" in markdown
    assert "卖家信用" in markdown
    assert "卖出" in markdown
    assert "碎" in markdown or "磕碰" in markdown or "瑕疵" in markdown

    candidates = {c["listing_id"]: c for c in report["candidates"]}
    a = candidates[ids["a"]]
    assert a["seller_credit"]["level"] in ("信用极好", "信用优秀", "信用良好", "信息不足")
    assert "type" not in a.get("seller_type_evidence", {})
    assert "category" not in a.get("price_evidence", {})
    b = candidates[ids["b"]]
    assert b["price_evidence"]["price_to_median"] < 0.75
    assert b["price_evidence"]["damage_keyword_hits"]


def test_decision_report_does_not_require_seller_db_fields(tmp_path: Path) -> None:
    """Report works when DB seller columns are NULL, falling back to DOM text."""
    db_path = tmp_path / "test-decision-report-dom.sqlite"
    config = AppConfig(database_path=db_path)
    initialize(config.database_path)
    text_dir = tmp_path / "dom_texts"
    text_dir.mkdir()
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="MacBook Air M2", city="上海")
        lid = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=9101")
        # No seller DB fields — all default to None
        add_listing_snapshot(
            conn, listing_id=lid, run_id=run_id, title="MacBook Air M2",
            price_text="¥3500", location="上海", seller_name="DOM回退卖家",
            description="自用机",
        )
        text = _make_detail_text("DOM回退卖家", "上海", ["来闲鱼3年", "卖出20件宝贝", "好评率98%"],
                                 "3500", "自用机功能正常", "几乎全新", "无任何拆修")
        tpath = text_dir / "d.txt"
        tpath.write_text(text, encoding="utf-8")
        add_detail_snapshot(conn, lid, run_id, "https://www.goofish.com/item?id=9101",
                            "MacBook Air M2", text_dir / "d_s.png", text_dir / "d.html",
                            tpath, text_dir / "d.links.txt", text_dir / "d.images.txt",
                            0, 0, False)
        conn.commit()

    report = build_decision_report(config, run_id, DecisionReportOptions(goal="MacBook Air M2"))
    c = report["candidates"][0]
    assert c["seller_fields"]["source"] == "dom"
    assert c["seller_fields"]["seller_sold_count"] == 20
    assert c["seller_fields"]["seller_registered_days"] == 1095
    assert c["seller_type_evidence"]["evidence"]  # evidence present, no label


def test_assess_seller_credit_passes_through_platform_level() -> None:
    # Platform level passed through directly; other signals are evidence only
    high = assess_seller_credit({
        "seller_credit_level": "信用极好", "seller_good_rate": "100%",
        "seller_registered_days": 2920, "seller_realname_verified": True,
        "seller_reply_rate_24h": "95%", "seller_sold_count": 5,
    })
    assert high["level"] == "信用极好"
    assert high["rank"] == 0
    assert "信用极好" in high["evidence"]
    assert "实人认证" in high["evidence"]

    fair = assess_seller_credit({
        "seller_credit_level": "信用良好", "seller_good_rate": "93%",
        "seller_registered_days": 3285, "seller_realname_verified": False,
        "seller_reply_rate_24h": None, "seller_sold_count": 3829,
    })
    assert fair["level"] == "信用良好"
    assert fair["rank"] == 2

    poor = assess_seller_credit({
        "seller_credit_level": "信用较差", "seller_good_rate": None,
        "seller_registered_days": None, "seller_realname_verified": None,
        "seller_reply_rate_24h": None, "seller_sold_count": None,
    })
    assert poor["level"] == "信用较差"
    assert poor["rank"] == 3

    empty = assess_seller_credit({
        "seller_credit_level": None, "seller_good_rate": None,
        "seller_registered_days": None, "seller_realname_verified": None,
        "seller_reply_rate_24h": None, "seller_sold_count": None,
    })
    assert empty["level"] == "信息不足"
    assert empty["rank"] is None

def test_assess_seller_type_returns_evidence_only() -> None:
    # No label/type field — evidence only, model decides personal vs professional
    r = assess_seller_type({"seller_sold_count": 5, "seller_registered_days": 2190})
    assert "type" not in r
    assert any("5" in e for e in r["evidence"])
    assert any("6" in e for e in r["evidence"])  # ~2190/365=6 years

    r2 = assess_seller_type({"seller_sold_count": 3829, "seller_registered_days": 3285})
    assert any("3829" in e for e in r2["evidence"])

    r3 = assess_seller_type({"seller_sold_count": None, "seller_registered_days": None})
    assert r3["evidence"] == []


def test_assess_price_risk_returns_evidence_only() -> None:
    # No category label — price-to-median ratio + damage keyword hits as evidence
    damage = assess_price_risk(
        price_value=2499, median=3690, condition="明显磕碰划痕",
        repair="无任何拆修", description="屏幕碎角",
    )
    assert "category" not in damage
    assert damage["price_to_median"] is not None
    assert damage["price_to_median"] < 0.75
    assert "碎" in damage["damage_keyword_hits"]

    fair = assess_price_risk(
        price_value=3666, median=3690, condition="几乎全新",
        repair="无任何拆修", description="自用",
    )
    assert fair["price_to_median"] is not None
    assert 0.9 < fair["price_to_median"] < 1.1
    assert fair["damage_keyword_hits"] == []

    no_price = assess_price_risk(price_value=None, median=3690, condition=None, repair=None, description="")
    assert no_price["price_to_median"] is None


def test_parse_dom_seller_stats() -> None:
    stats = ["1小时前来过", "来闲鱼8年", "卖出1249件宝贝", "好评率98%", "实人认证"]
    result = parse_dom_seller_stats(stats)
    assert result["seller_registered_days"] == 2920
    assert result["seller_sold_count"] == 1249
    assert result["seller_good_rate"] == "98%"
    assert result["seller_realname_verified"] is True
