from __future__ import annotations

from pathlib import Path

from shopping_agent.cli import build_parser
from shopping_agent.config import AppConfig
from shopping_agent.db import connect, create_search_run, initialize, upsert_listing
from shopping_agent.reference_evidence import (
    ReferenceEvidenceInput,
    build_reference_evidence_summary,
    parse_price_value,
    save_reference_evidence,
)


def test_reference_evidence_saves_defaults_and_summarizes_prices() -> None:
    config = AppConfig(database_path=Path("data/test-reference-evidence.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    initialize(config.database_path)
    with connect(config.database_path) as conn:
        run_id = create_search_run(conn, goal="2019 iMac 27", city="Shanghai")
        listing_id = upsert_listing(conn, platform="xianyu", url="https://www.goofish.com/item?id=101")

    spec = save_reference_evidence(
        config,
        ReferenceEvidenceInput(
            run_id=run_id,
            listing_id=listing_id,
            goal="2019 iMac 27",
            source_type="official_specs",
            platform="apple",
            title="Apple iMac 27-inch 2019 technical specifications",
            url="https://support.apple.com/specs",
            spec_summary="iMac Retina 5K 27-inch 2019 official configuration range",
            checked_at="2026-06-18",
        ),
    )
    market = save_reference_evidence(
        config,
        ReferenceEvidenceInput(
            run_id=run_id,
            listing_id=listing_id,
            goal="2019 iMac 27",
            source_type="current_listing",
            platform="taobao",
            title="Comparable current merchant listing",
            url="https://example.com/current",
            price_text="¥4,688",
            comparable_scope="same family, similar storage, merchant/refurbished context",
            notes="Current listing, not sold evidence.",
            checked_at="2026-06-18",
        ),
    )

    summary = build_reference_evidence_summary(
        config,
        run_id=run_id,
        listing_id=listing_id,
        goal="2019 iMac 27",
    )

    assert spec["evidence_level"] == "spec_reference"
    assert market["evidence_level"] == "A_external_current_listing_unverified"
    assert market["price_value"] == 4688
    assert summary["decision_owner"] == "llm"
    assert summary["is_final_recommendation"] is False
    assert summary["reference_count"] == 2
    assert summary["priced_sample_count"] == 1
    assert {"value": "official_specs", "count": 1} in summary["source_type_counts"]
    assert {"value": "current_listing", "count": 1} in summary["source_type_counts"]
    assert summary["official_spec_sources"][0]["source_type"] == "official_specs"
    assert summary["market_price_sources"][0]["price_value"] == 4688
    assert summary["price_summary_by_source_type"][0]["source_type"] == "current_listing"
    assert summary["price_summary_by_source_type"][0]["price_summary"]["median"] == 4688


def test_reference_evidence_goal_filter_limits_rows() -> None:
    config = AppConfig(database_path=Path("data/test-reference-evidence-filter.sqlite"))
    if config.database_path.exists():
        config.database_path.unlink()
    save_reference_evidence(
        config,
        ReferenceEvidenceInput(
            goal="iMac",
            source_type="current_listing",
            title="iMac sample",
            url="https://example.com/imac",
            price_value=4000,
        ),
    )
    save_reference_evidence(
        config,
        ReferenceEvidenceInput(
            goal="MacBook",
            source_type="current_listing",
            title="MacBook sample",
            url="https://example.com/macbook",
            price_value=6000,
        ),
    )

    summary = build_reference_evidence_summary(config, goal="iMac")

    assert summary["reference_count"] == 1
    assert summary["entries"][0]["title"] == "iMac sample"


def test_reference_cli_accepts_add_and_list_arguments() -> None:
    parser = build_parser()

    add_args = parser.parse_args(
        [
            "reference-add",
            "--run-id",
            "4",
            "--listing-id",
            "9",
            "--goal",
            "2019 iMac 27",
            "--source-type",
            "sold_history",
            "--platform",
            "ebay",
            "--title",
            "Recent sold iMac sample",
            "--url",
            "https://example.com/sold",
            "--price-text",
            "¥4,500",
            "--model-key",
            "imac-27-2019-i5-32g-1tb",
            "--pretty",
        ]
    )
    list_args = parser.parse_args(
        [
            "reference-list",
            "--run-id",
            "4",
            "--goal",
            "2019 iMac 27",
            "--limit",
            "20",
            "--pretty",
        ]
    )

    assert add_args.command == "reference-add"
    assert add_args.source_type == "sold_history"
    assert add_args.price_text == "¥4,500"
    assert add_args.model_key == "imac-27-2019-i5-32g-1tb"
    assert list_args.command == "reference-list"
    assert list_args.run_id == 4
    assert list_args.limit == 20


def test_parse_price_value() -> None:
    assert parse_price_value("¥4,688") == 4688
    assert parse_price_value("RMB 5800 起") == 5800
    assert parse_price_value(None) is None
