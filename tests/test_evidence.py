from __future__ import annotations

from pathlib import Path

from shopping_agent.config import AppConfig
from shopping_agent.db import add_listing_snapshot, connect, create_search_run, initialize, upsert_listing
from shopping_agent.evidence import OcrEvidence, _build_ocr_evidence, collect_evidence_flags, collect_seller_signals
from shopping_agent.evidence import build_listing_evidence, evidence_bundle_to_dict
from shopping_agent.evaluation.consistency import evaluate_listing_consistency
from shopping_agent.evidence import ListingEvidenceBundle
from shopping_agent.extraction.spec_parser import parse_imac_specs


def test_collect_evidence_flags_does_not_make_final_product_judgment() -> None:
    description = (
        "苹果 iMac 27寸一体机，2019款顶配，3.7GHz六核i5处理器，"
        "Radeon Pro 580X 8G独显，32GB DDR4内存，512GB Fusion HD固态。"
        "无拆无修功能正常，屏幕边缘有些泛红，屏幕一个小划痕，边框轻微磕碰。"
        "单机，有专用包装箱可以邮寄。"
    )
    flags = collect_evidence_flags(
        description=description,
        description_specs=parse_imac_specs(description),
        image_specs={
            "year": "2019",
            "screen_size_inch": "27",
            "memory": "32 GB 2667 MHz DDR4",
            "storage_capacity": "499.96GB",
        },
        ocr_evidence=[
            OcrEvidence(
                media_asset_id=54,
                local_path="data/media/listing-1/about-this-mac.webp",
                ocr_text="关于本机 27英寸，2019年 32 GB 2667 MHz DDR4 共499.96GB",
                detected_specs={"year": "2019"},
            )
        ],
    )

    codes = {flag.code for flag in flags}
    assert "mentions_fusion_drive" in codes
    assert "mixed_storage_wording" in codes
    assert "mentions_screen_redness" in codes
    assert "mentions_cosmetic_damage" in codes
    assert "memory_mismatch" not in codes
    assert "storage_capacity_mismatch" not in codes


def test_collect_evidence_flags_does_not_treat_missing_ocr_as_risk() -> None:
    flags = collect_evidence_flags(
        description="MacBook Air M2 16GB 256GB",
        description_specs={},
        image_specs={},
        ocr_evidence=[],
    )

    assert "missing_ocr_evidence" not in {flag.code for flag in flags}


def test_build_ocr_evidence_reparses_raw_text_instead_of_stale_specs() -> None:
    evidence = _build_ocr_evidence(
        [
            {
                "media_asset_id": 1,
                "local_path": "image.webp",
                "status": "ok",
                "ocr_text": "内存\nap\n图形卡/显示器",
                "detected_specs_json": '{"width": 790, "height": 1053, "memory": "ap"}',
            },
            {
                "media_asset_id": 2,
                "local_path": "about.webp",
                "status": "ok",
                "ocr_text": "关于本机\nM2, 2022年\n内存\n16GB",
                "detected_specs_json": '{"width": 790, "height": 1053}',
            },
        ]
    )

    assert "memory" not in evidence[0].detected_specs
    assert evidence[0].detected_specs["width"] == "790"
    assert evidence[1].detected_specs["memory"] == "16GB"


def test_heuristic_interpreter_reads_evidence_flags() -> None:
    description = "2019 iMac 27寸，512GB Fusion HD固态，屏幕泛红。"
    bundle = ListingEvidenceBundle(
        listing_id=1,
        url="https://example.test/item/1",
        platform="xianyu",
        source_type="web_search",
        source_label="网页搜索",
        price_text="¥3550",
        location="上海",
        seller_name="seller",
        description=description,
        description_specs=parse_imac_specs(description),
        image_specs={"year": "2019"},
        seller_signals={},
        ocr_evidence=[],
        flags=collect_evidence_flags(
            description=description,
            description_specs=parse_imac_specs(description),
            image_specs={"year": "2019"},
            ocr_evidence=[],
        ),
    )

    report = evaluate_listing_consistency(bundle)

    assert any("Fusion Drive" in risk for risk in report.risks)
    assert any("硬盘类型" in question for question in report.questions)
    assert report.flags


def test_collect_seller_signals_extracts_evidence_without_final_label() -> None:
    signals = collect_seller_signals(
        seller_name="seller",
        description=(
            "公司回购工作机，卖出123件，必须走验货宝。"
            "也可以上海自提，个人自用说法需进一步确认。"
        ),
    )

    assert signals["sold_count"] == 123
    assert "公司回购" in signals["merchant_keyword_hits"]
    assert "工作机" in signals["merchant_keyword_hits"]
    assert "自用" in signals["personal_keyword_hits"]
    assert "验货宝" in signals["trust_keyword_hits"]
    assert "seller_type" not in signals
    assert "The LLM must decide seller type" in signals["extraction_note"]


def test_build_listing_evidence_includes_manual_mobile_source() -> None:
    config = AppConfig(database_path=Path("data/test-evidence-source.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="Manual candidate URL", city="上海")
        listing_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=manual")
        add_listing_snapshot(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            title="MacBook Pro M1 Pro",
            price_text="¥5900",
            location="深圳",
            seller_name="seller",
            description="MacBook Pro 16寸 M1 Pro 32G 512GB",
            source_type="mobile_manual",
            source_label="手机端手动加入",
        )

    bundle = evidence_bundle_to_dict(build_listing_evidence(config, listing_id))

    assert bundle["source_type"] == "mobile_manual"
    assert bundle["source_label"] == "手机端手动加入"
